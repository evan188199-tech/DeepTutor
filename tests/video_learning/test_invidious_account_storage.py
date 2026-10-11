"""Focused tests for invidious_account_storage (FT35).

Covers three branch families of the owner-private persistence layer, entirely
on tmp_path-isolated state with no network and no real accounts:

1. Account CRUD and persistence round-trips (write/read/forget/overwrite).
2. Sensitive-field handling: private file modes, owner-private directory
   modes, and state values that never surface in pending-flow filenames.
3. Corruption / missing-field degradation: tolerant reads, field validation,
   expiry purging, same-instance flow replacement, and one-time claims.
"""

from __future__ import annotations

import json
from pathlib import Path
import stat
import time

import pytest

from deeptutor.multi_user import paths
from deeptutor.video_learning import invidious_account_storage as storage
from deeptutor.video_learning.invidious_account_storage import PendingFlow


@pytest.fixture
def system_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "data" / "system").resolve()
    monkeypatch.setattr(paths, "SYSTEM_ROOT", root)
    return root


def _flow_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "owner_id": "u_ada",
        "api_base_url": "https://invidious.example.test",
        "callback_url": "https://app.example.test/callback",
        "expires_at": time.time() + 3600,
    }
    payload.update(overrides)
    return payload


def _write_flow(owner_id: str, state: str, payload: dict[str, object]) -> Path:
    target = storage.flow_path(owner_id, state)
    storage.write_private_json(target, payload)
    return target


# ---------------------------------------------------------------------------
# 1. Account CRUD and persistence round-trips
# ---------------------------------------------------------------------------


def test_account_round_trip_overwrite_and_forget(system_root: Path) -> None:
    first = {
        "version": 1,
        "api_base_url": "https://invidious.example.test",
        "token": {"session": "v1:round-trip+值", "signature": "sig-1"},
    }
    storage.write_account("u_ada", first)
    assert storage.read_account("u_ada") == first

    second = {"version": 1, "api_base_url": "https://other.example.test", "token": {}}
    storage.write_account("u_ada", second)
    assert storage.read_account("u_ada") == second

    storage.forget_account("u_ada")
    assert storage.read_account("u_ada") == {}
    # Forgetting twice stays a no-op.
    storage.forget_account("u_ada")
    assert not storage.account_path("u_ada").exists()


def test_account_reads_are_owner_scoped(system_root: Path) -> None:
    storage.write_account("u_ada", {"version": 1, "token": {"session": "ada"}})
    storage.write_account("u_bob", {"version": 1, "token": {"session": "bob"}})
    assert storage.read_account("u_ada")["token"] == {"session": "ada"}
    assert storage.read_account("u_bob")["token"] == {"session": "bob"}
    storage.forget_account("u_ada")
    assert storage.read_account("u_bob")["token"] == {"session": "bob"}


# ---------------------------------------------------------------------------
# 2. Sensitive-field handling: private modes and state never in filenames
# ---------------------------------------------------------------------------


def test_storage_layout_is_owner_private_and_files_are_0600(system_root: Path) -> None:
    path = storage.account_path("u_ada")
    storage.write_private_json(path, {"version": 1})

    asset_dir = storage.asset_dir("u_ada")
    assert path.parent == asset_dir
    owner_dir = asset_dir.parent.parent
    assert asset_dir.name == "video-learning-invidious"
    assert asset_dir.parent.name == "private"
    for directory in (asset_dir, asset_dir.parent, owner_dir):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    pending = storage.pending_dir("u_ada")
    assert stat.S_IMODE(pending.stat().st_mode) == 0o700
    _write_flow("u_ada", "state-live", _flow_payload())
    written = list(pending.glob("*.json"))[0]
    assert stat.S_IMODE(written.stat().st_mode) == 0o600


def test_flow_path_hashes_state_and_stays_inside_pending_dir(system_root: Path) -> None:
    hostile_state = "../../etc/passwd\nv1:state-with/slashes"
    path = storage.flow_path("u_ada", hostile_state)
    pending = storage.pending_dir("u_ada")

    assert path.parent.resolve() == pending.resolve()
    assert path.suffix == ".json"
    stem = path.stem
    assert len(stem) == 64
    assert all(character in "0123456789abcdef" for character in stem)
    for fragment in ("..", "etc", "passwd", "v1:state"):
        assert fragment not in stem

    assert storage.flow_path("u_ada", hostile_state) == path
    assert storage.flow_path("u_ada", "different") != path
    assert storage.flow_path("u_bob", hostile_state) != path


def test_write_private_json_cleans_up_temporaries_on_success_and_failure(
    system_root: Path,
) -> None:
    target = storage.account_path("u_ada")
    good = {"version": 1, "token": {"session": "keep-me"}}
    storage.write_private_json(target, good)

    with pytest.raises(TypeError):
        storage.write_private_json(target, {"token": object()})

    assert storage.read_account("u_ada") == good
    assert list(target.parent.glob(f".{target.name}.*")) == []


# ---------------------------------------------------------------------------
# 3. Corruption and missing-field degradation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        None,
        "{not json",
        b"\xff\xfe\x00broken-utf8",
        json.dumps([1, 2, 3]),
        json.dumps("a string"),
        "42",
    ],
)
def test_read_json_degrades_to_empty_dict(
    system_root: Path, tmp_path: Path, content: bytes | str | None
) -> None:
    path = tmp_path / "broken.json"
    if content is None:
        pass
    elif isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    assert storage.read_json(path) == {}


def test_pending_flow_rejects_missing_or_mistyped_fields(system_root: Path, tmp_path: Path) -> None:
    base = _flow_payload()
    bad_payloads = [
        {},
        {**base, "owner_id": ""},
        {**base, "owner_id": 7},
        {**base, "api_base_url": ""},
        {**base, "api_base_url": None},
        {**base, "callback_url": ""},
        {**base, "callback_url": ["list"]},
        {**base, "expires_at": "soon"},
        {**base, "expires_at": None},
        {key: value for key, value in base.items() if key != "expires_at"},
    ]
    for index, payload in enumerate(bad_payloads):
        path = tmp_path / f"bad-{index}.json"
        storage.write_private_json(path, payload)
        assert storage.pending_flow(path) is None, f"case {index} must degrade"

    path = tmp_path / "good.json"
    storage.write_private_json(path, {**base, "expires_at": 123})
    flow = storage.pending_flow(path)
    assert flow == PendingFlow(
        owner_id="u_ada",
        api_base_url=base["api_base_url"],
        callback_url=base["callback_url"],
        expires_at=123.0,
    )


def test_purge_expired_removes_dead_files_and_keeps_live_ones(
    system_root: Path,
) -> None:
    now = 1000.0
    live = _write_flow("u_ada", "state-live", _flow_payload(expires_at=2000.0))
    expired = _write_flow("u_ada", "state-old", _flow_payload(expires_at=999.0))
    corrupt = storage.pending_dir("u_ada") / "corrupt.json"
    corrupt.write_text("{truncated", encoding="utf-8")
    foreign = _write_flow("u_ada", "state-foreign", _flow_payload(owner_id="u_bob"))

    storage.purge_expired("u_ada", now=now)

    assert live.is_file()
    for gone in (expired, corrupt, foreign):
        assert not gone.exists()


def test_replace_pending_flow_invalidates_only_the_same_instance(
    system_root: Path,
) -> None:
    corrupt = storage.pending_dir("u_ada") / "corrupt.json"
    corrupt.write_text("][]", encoding="utf-8")
    foreign = _write_flow("u_ada", "state-foreign", _flow_payload(owner_id="u_bob"))
    other_instance = _write_flow(
        "u_ada",
        "state-other-instance",
        _flow_payload(api_base_url="https://other.example.test"),
    )

    flow = PendingFlow(
        owner_id="u_ada",
        api_base_url="https://invidious.example.test",
        callback_url="https://app.example.test/callback",
        expires_at=time.time() + 3600,
    )
    storage.replace_pending_flow(state="state-new", flow=flow)

    assert not corrupt.exists()
    assert not foreign.exists()
    assert other_instance.is_file()

    claimed = storage.consume_pending_flow("u_ada", "state-new")
    assert claimed == flow


def test_consume_pending_flow_is_one_time_and_degrades_safely(
    system_root: Path,
) -> None:
    pending = storage.pending_dir("u_ada")

    assert storage.consume_pending_flow("u_ada", "") is None
    assert storage.consume_pending_flow("u_ada", "never-issued") is None
    assert list(pending.glob(".*")) == []

    corrupt = storage.flow_path("u_ada", "state-corrupt")
    corrupt.write_text("{oops", encoding="utf-8")
    assert storage.consume_pending_flow("u_ada", "state-corrupt") is None
    assert not corrupt.exists()

    expired = _write_flow("u_ada", "state-expired", _flow_payload(expires_at=time.time() - 1))
    assert storage.consume_pending_flow("u_ada", "state-expired") is None
    assert not expired.exists()

    foreign = _write_flow("u_ada", "state-foreign", _flow_payload(owner_id="u_bob"))
    assert storage.consume_pending_flow("u_ada", "state-foreign") is None
    assert not foreign.exists()

    live_payload = _flow_payload()
    live = _write_flow("u_ada", "state-live", live_payload)
    claimed = storage.consume_pending_flow("u_ada", "state-live")
    assert claimed is not None
    assert claimed.owner_id == "u_ada"
    assert claimed.api_base_url == live_payload["api_base_url"]
    assert claimed.callback_url == live_payload["callback_url"]
    assert claimed.expires_at == pytest.approx(live_payload["expires_at"])
    assert not live.exists()
    assert storage.consume_pending_flow("u_ada", "state-live") is None
    assert list(pending.glob("*")) == []

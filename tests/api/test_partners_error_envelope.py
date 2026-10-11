"""The partners router refuses requests with the structured error envelope.

Every refusal in ``deeptutor/api/routers/partners.py`` goes through the shared
``structured_error`` helper: the message text is the historical free-text
detail (byte-identical, so string matching keeps working) and every response
gains a machine-readable ``partner.*`` code. The tests pin three halves: the
raise-site invariant (no bare ``HTTPException`` escapes without a code), the
envelope on representative refusals (table-driven: status, code, message,
extras), and the in-process WebSocket consumers that read the message back
out of either shape.
"""

from __future__ import annotations

import ast
import base64
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

from deeptutor.api.routers import partners as partners_router

ROUTER_PATH = Path(partners_router.__file__)


@pytest.fixture
def isolated_root(tmp_path, monkeypatch) -> Path:
    from deeptutor.multi_user import paths

    project_root = tmp_path
    admin_root = (project_root / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root


@pytest.fixture
def client(isolated_root, monkeypatch) -> TestClient:
    from deeptutor.api.routers import auth as auth_module
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.services.partners.manager import PartnerManager

    monkeypatch.setattr(auth_module, "AUTH_ENABLED", False)
    token = set_current_user(
        CurrentUser(
            id="test-admin",
            username="test-admin",
            role="admin",
            scope=UserScope(
                kind="admin",
                user_id="test-admin",
                root=isolated_root,
            ),
        )
    )
    mgr = PartnerManager()
    monkeypatch.setattr(partners_router, "get_partner_manager", lambda: mgr)
    partners_router._start_locks.clear()

    app = FastAPI()
    app.include_router(partners_router.router, prefix="/api/partners")
    app.include_router(partners_router.ws_router, prefix="/ws/partners")
    try:
        yield TestClient(app)
    finally:
        reset_current_user(token)


def _create(client: TestClient, **overrides):
    payload = {
        "name": "Ada",
        "description": "study partner",
        "soul": {"source": "custom", "content": "# Soul\nBe rigorous."},
        "start": False,
        **overrides,
    }
    return client.post("/api/partners", json=payload)


def _seed_session(isolated_root: Path, key: str, content: str) -> None:
    sessions = isolated_root / "partners" / "ada" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{key}.jsonl").write_text(
        json.dumps({"role": "user", "content": content, "timestamp": "t"}) + "\n",
        encoding="utf-8",
    )


# ── Raise-site invariant ────────────────────────────────────────


def test_every_refusal_in_partners_router_carries_the_envelope() -> None:
    tree = ast.parse(ROUTER_PATH.read_text())
    bare = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "HTTPException"
    ]
    assert not bare, (
        "refusals must be raised through structured_error so every response "
        "carries a machine-readable code; found bare HTTPException raises"
    )
    helpers = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "structured_error"
    ]
    assert helpers, "expected the partners router to refuse via structured_error"
    for call in helpers:
        codes = [kw for kw in call.keywords if kw.arg == "code"]
        assert len(codes) == 1, "every structured_error call must pass code="
        value = codes[0].value
        assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
            "the error code must be a string literal, not a computed value"
        )
        assert value.value.startswith("partner."), (
            f"the partners router owns the partner.* code namespace, got {value.value!r}"
        )


# ── Table-driven refusal contract ───────────────────────────────


@dataclass
class Refusal:
    """One representative refusal: what triggers it and what must answer."""

    label: str
    act: Callable[..., Any]
    status: int
    code: str
    message: str | None = None
    message_startswith: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    extra_keys: set[str] = field(default_factory=set)
    arrange: Callable[..., None] = lambda client, root, monkeypatch: None


def _arrange_partner(**create_overrides):
    def arrange(client, root, monkeypatch):
        assert _create(client, **create_overrides).status_code == 200

    return arrange


def _arrange_stale_selected_key(client, root, monkeypatch):
    assert _create(client, start=False).status_code == 200
    manager = partners_router.get_partner_manager()

    async def reply(_partner_id, _content, **_kwargs):
        return "answer"

    monkeypatch.setattr(manager, "send_message", reply)
    enabled = client.put(
        "/api/partners/ada/web-continuity",
        json={"enabled": True, "session_key": "web-current"},
    )
    assert enabled.status_code == 200


def _arrange_onboarding_refusal(client, root, monkeypatch):
    from deeptutor.services.partners.channel_onboarding import ChannelOnboardingError

    class StubManager:
        async def start(self, partner_id, channel):
            raise ChannelOnboardingError("Unsupported onboarding channel", status_code=422)

    assert _create(client).status_code == 200
    monkeypatch.setattr(partners_router, "get_channel_onboarding_manager", lambda: StubManager())


def _arrange_weixin_qr_failure(client, root, monkeypatch):
    from deeptutor.services.partners import weixin_onboarding

    async def explode(partner_id):
        raise RuntimeError("bridge down")

    assert _create(client).status_code == 200
    monkeypatch.setattr(weixin_onboarding, "start_login", explode)


REFUSALS = [
    Refusal(
        label="unknown partner reads as absent",
        act=lambda c, r: c.get("/api/partners/ghost"),
        status=404,
        code="partner.not_found",
        message="Partner not found",
    ),
    Refusal(
        label="unknown soul template",
        act=lambda c, r: c.get("/api/partners/souls/ghost"),
        status=404,
        code="partner.soul_not_found",
        message="Soul not found",
    ),
    Refusal(
        label="unknown draft",
        act=lambda c, r: c.get("/api/partners/drafts/ghost"),
        status=404,
        code="partner.draft_not_found",
        message="Partner draft not found",
    ),
    Refusal(
        label="duplicate partner id",
        arrange=_arrange_partner(),
        act=lambda c, r: _create(c),
        status=409,
        code="partner.already_exists",
        message="Partner 'ada' already exists",
    ),
    Refusal(
        label="duplicate soul template",
        arrange=_arrange_partner(),
        act=lambda c, r: (
            c.post(
                "/api/partners/souls",
                json={"id": "focus", "name": "Focus", "content": "# Focus"},
            ),
            c.post(
                "/api/partners/souls",
                json={"id": "focus", "name": "Focus", "content": "# Focus"},
            ),
        )[1],
        status=409,
        code="partner.soul_already_exists",
        message="Soul 'focus' already exists",
    ),
    Refusal(
        label="legacy top-level delivery flags rejected",
        act=lambda c, r: _create(c, channels={"send_progress": False}),
        status=422,
        code="partner.channels_legacy_delivery_keys",
        message_startswith=(
            "Delivery flags are configured per channel; remove top-level channel keys:"
        ),
    ),
    Refusal(
        label="channels payload fails its config model",
        act=lambda c, r: _create(c, channels={"telegram": 5}),
        status=422,
        code="partner.channels_invalid",
        message="Invalid channels config",
        extra_keys={"errors"},
    ),
    Refusal(
        label="enabled channel without allowed senders",
        act=lambda c, r: _create(c, channels={"telegram": {"enabled": True, "allow_from": []}}),
        status=422,
        code="partner.channels_allow_from_required",
        message="Enabled channels require at least one allowed sender: telegram",
        extras={"channels": ["telegram"]},
    ),
    Refusal(
        label="avatar must be a data url",
        act=lambda c, r: _create(c, avatar="https://example.com/face.png"),
        status=422,
        code="partner.avatar_invalid",
        message="Avatar must be a data:image/* URL",
    ),
    Refusal(
        label="avatar too large",
        act=lambda c, r: _create(c, avatar="data:image/png;base64," + "A" * 200_001),
        status=422,
        code="partner.avatar_too_large",
        message="Avatar too large — resize the image before uploading",
    ),
    Refusal(
        label="custom soul content empty",
        act=lambda c, r: _create(c, soul={"source": "custom", "content": "   "}),
        status=422,
        code="partner.soul_content_empty",
        message="Custom soul content is empty",
    ),
    Refusal(
        label="library soul missing",
        act=lambda c, r: _create(c, soul={"source": "library", "id": "ghost"}),
        status=404,
        code="partner.soul_library_not_found",
        message="Soul 'ghost' not found in library",
    ),
    Refusal(
        label="persona soul without a name",
        act=lambda c, r: _create(c, soul={"source": "persona", "id": "  "}),
        status=422,
        code="partner.persona_name_required",
        message="Persona name is required",
    ),
    Refusal(
        label="persona soul not found",
        act=lambda c, r: _create(c, soul={"source": "persona", "id": "ghost"}),
        status=404,
        code="partner.persona_not_found",
        message="Persona not found: ghost",
    ),
    Refusal(
        label="unknown linked account",
        arrange=_arrange_partner(),
        act=lambda c, r: c.delete("/api/partners/ada/links/ghost"),
        status=404,
        code="partner.link_not_found",
        message="No such linked account",
    ),
    Refusal(
        label="unknown asset",
        arrange=_arrange_partner(),
        act=lambda c, r: c.delete("/api/partners/ada/assets/skill/ghost"),
        status=404,
        code="partner.asset_not_found",
        message="Asset not found",
    ),
    Refusal(
        label="archiving a missing session",
        arrange=_arrange_partner(),
        act=lambda c, r: c.post("/api/partners/ada/sessions/archive", json={"session_key": "x"}),
        status=404,
        code="partner.session_not_found",
        message="Session not found",
    ),
    Refusal(
        label="branching onto the same key",
        arrange=_arrange_partner(),
        act=lambda c, r: (
            _seed_session(r, "web-a", "hi"),
            c.post(
                "/api/partners/ada/sessions/branch",
                json={"source_key": "web-a", "new_key": "web-a"},
            ),
        )[1],
        status=400,
        code="partner.branch_same_key",
        message="Branch needs a different session key",
    ),
    Refusal(
        label="branch target key invalid",
        arrange=_arrange_partner(),
        act=lambda c, r: c.post(
            "/api/partners/ada/sessions/branch",
            json={"source_key": "web-a", "new_key": "../bad"},
        ),
        status=422,
        code="partner.session_key_invalid",
        message="Invalid Partner session key",
    ),
    Refusal(
        label="branching an empty source",
        arrange=_arrange_partner(),
        act=lambda c, r: c.post(
            "/api/partners/ada/sessions/branch",
            json={"source_key": "web-nothing", "new_key": "web-b"},
        ),
        status=400,
        code="partner.branch_source_empty",
        message="Nothing to branch (source is empty)",
    ),
    Refusal(
        label="chat without content",
        arrange=_arrange_partner(start=False),
        act=lambda c, r: c.post("/api/partners/ada/chat", json={"content": "   "}),
        status=400,
        code="partner.content_required",
        message="content is required",
    ),
    Refusal(
        label="stream without content",
        arrange=_arrange_partner(start=False),
        act=lambda c, r: c.post("/api/partners/ada/chat/execute-stream", json={"content": ""}),
        status=400,
        code="partner.content_required",
        message="content is required",
    ),
    Refusal(
        label="stale selected web session",
        arrange=_arrange_stale_selected_key,
        act=lambda c, r: c.post(
            "/api/partners/ada/chat",
            json={"content": "hello", "session_key": "web-old"},
        ),
        status=409,
        code="partner.stale_session",
        message="The active conversation changed in another browser.",
        extras={"active_session_key": "web-current"},
    ),
    Refusal(
        label="channel onboarding refusal keeps its status",
        arrange=_arrange_onboarding_refusal,
        act=lambda c, r: c.post(
            "/api/partners/ada/channel-onboarding/start", json={"channel": "feishu"}
        ),
        status=422,
        code="partner.channel_onboarding_failed",
        message="Unsupported onboarding channel",
    ),
    Refusal(
        label="weixin qr start failure surfaces the reason",
        arrange=_arrange_weixin_qr_failure,
        act=lambda c, r: c.post("/api/partners/ada/channels/weixin/qr"),
        status=502,
        code="partner.weixin_qr_start_failed",
        message="bridge down",
    ),
]


@pytest.mark.parametrize("case", REFUSALS, ids=[c.label for c in REFUSALS])
def test_refusals_answer_with_the_envelope(case, client, isolated_root, monkeypatch):
    case.arrange(client, isolated_root, monkeypatch)
    response = case.act(client, isolated_root)

    assert response.status_code == case.status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), f"detail must be the envelope, got {detail!r}"
    assert detail["code"] == case.code
    if case.message is not None:
        assert detail["message"] == case.message
    if case.message_startswith is not None:
        assert detail["message"].startswith(case.message_startswith)
    for key, value in case.extras.items():
        assert detail[key] == value
    assert set(detail) == {"code", "message"} | set(case.extras) | case.extra_keys


# ── In-process consumers ────────────────────────────────────────


def test_busy_turn_refusal_carries_the_code(client, isolated_root):
    assert _create(client).status_code == 200
    manager = partners_router.get_partner_manager()
    manager.session_store("ada").append("web-active", "user", "being answered")
    enabled = client.put(
        "/api/partners/ada/web-continuity",
        json={"enabled": True, "session_key": "web-active"},
    )
    assert enabled.status_code == 200

    with manager.web_session_idle_lock("ada", "web-active"):
        busy = client.put(
            "/api/partners/ada/web-continuity",
            json={"enabled": True, "session_key": "web-other"},
        )

    assert busy.status_code == 409
    assert busy.json()["detail"] == {
        "code": "partner.turn_busy",
        "message": "This conversation is already replying. Please wait.",
    }


def test_attachment_over_cap_reports_the_offending_file(client, isolated_root, monkeypatch):
    monkeypatch.setattr(partners_router, "_partner_upload_caps", lambda: (8, 1024))
    assert _create(client, start=False).status_code == 200

    too_big = base64.b64encode(b"more than eight bytes").decode()
    response = client.post(
        "/api/partners/ada/chat",
        json={
            "content": "hi",
            "attachments": [
                {
                    "type": "image",
                    "filename": "shot.png",
                    "mime_type": "image/png",
                    "base64": too_big,
                }
            ],
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "partner.attachment_too_large",
        "message": "Attachment too large: shot.png",
    }


def test_websocket_frames_carry_the_message_not_the_dict_repr(client, isolated_root, monkeypatch):
    from deeptutor.api.utils.error_responses import structured_error

    assert _create(client, start=False).status_code == 200

    async def refuse(_partner_id, **_kwargs):
        raise structured_error(500, "runtime exploded", code="partner.start_failed")

    monkeypatch.setattr(partners_router, "_ensure_running_partner", refuse)

    with client.websocket_connect("/ws/partners/ada") as socket:
        frame = socket.receive_json()

    assert frame == {"type": "error", "content": "runtime exploded"}


def test_websocket_attachment_error_frame_keeps_the_message(client, isolated_root, monkeypatch):
    assert _create(client, start=False).status_code == 200

    with client.websocket_connect("/ws/partners/ada") as socket:
        assert socket.receive_json()["type"] == "ready"
        socket.send_json(
            {
                "content": "hi",
                "attachments": [
                    {
                        "type": "image",
                        "filename": "broken.png",
                        "mime_type": "image/png",
                        "base64": "abc",
                    }
                ],
            }
        )
        frame = socket.receive_json()

    assert frame == {
        "type": "error",
        "content": "Invalid attachment data for broken.png",
    }

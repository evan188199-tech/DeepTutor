"""The snapshot builder regenerates vendored catalog data, so it is tested like code.

``build_snapshot.py`` is a script that runs at import time — no functions, just
top-level steps — so each test copies it into a ``tmp_path`` sandbox, writes
fixture registries next to it, and runs it as a subprocess the way a vendor
re-sync does. The contract under test: input collection trims the upstream
registries to the fields DeepTutor reads, an empty registry set still yields a
valid catalog, and a rejected registry set fails without leaving a snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from deeptutor.services.cli_apps.catalog import CATALOG_PATH, catalog_pin

SCRIPT_PATH = CATALOG_PATH.parent / "build_snapshot.py"
OUTPUT_NAME = "cli_apps_snapshot.json"
HARNESS_REGISTRY = "cli-registry.json"
PUBLIC_REGISTRY = "cli-public_registry.json"


def _write_registry(path: Path, clis: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"clis": clis}), encoding="utf-8")


def _run_build(
    tmp_path: Path,
    harness: list[dict[str, Any]],
    public: list[dict[str, Any]] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Copy the builder into the sandbox, feed it fixture registries, run it.

    ``public=None`` leaves that registry file unwritten, exercising a build
    whose input collection cannot even start.
    """
    _write_registry(tmp_path / HARNESS_REGISTRY, harness)
    if public is not None:
        _write_registry(tmp_path / PUBLIC_REGISTRY, public)
    (tmp_path / "build_snapshot.py").write_bytes(SCRIPT_PATH.read_bytes())
    return subprocess.run(
        [sys.executable, "build_snapshot.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_output(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / OUTPUT_NAME).read_text(encoding="utf-8"))


def test_build_merges_both_registries_and_stamps_origin(tmp_path: Path) -> None:
    """Each row carries the registry it came from, and both registries land."""
    run = _run_build(
        tmp_path,
        [{"name": "alpha", "description": "from the harness registry"}],
        [{"name": "zulu", "description": "from the public registry"}],
    )

    assert run.returncode == 0, run.stderr
    payload = _read_output(tmp_path)
    by_name = {row["name"]: row for row in payload["apps"]}
    assert by_name["alpha"]["origin"] == "harness"
    assert by_name["zulu"]["origin"] == "public"


def test_build_trims_to_kept_fields_and_drops_falsy_values(tmp_path: Path) -> None:
    """Unknown upstream fields are trimmed and blank fields dropped: the catalog
    only carries what DeepTutor reads, and turning install commands into specs is
    ``loader.py``'s job, never vendored data's."""
    noisy = {
        "name": "alpha",
        "description": "kept",
        "version": "1.2.3",
        "install_cmd": "",
        "upstream_only_field": "must not survive the trim",
    }
    run = _run_build(tmp_path, [noisy], [])

    assert run.returncode == 0, run.stderr
    (row,) = _read_output(tmp_path)["apps"]
    assert set(row) == {"name", "description", "version", "origin"}
    assert row["origin"] == "harness"


def test_build_output_is_deterministic_sorted_json(tmp_path: Path) -> None:
    """A re-run must not churn the vendored file, and rows are name-sorted."""
    clis = [{"name": name} for name in ("mid", "zebra", "anchor")]
    first = _run_build(tmp_path, list(clis), [])
    second = _run_build(tmp_path, list(clis), [])

    assert first.returncode == second.returncode == 0, first.stderr
    first_bytes = (tmp_path / OUTPUT_NAME).read_bytes()
    payload = json.loads(first_bytes.decode("utf-8"))
    assert [row["name"] for row in payload["apps"]] == ["anchor", "mid", "zebra"]
    assert first_bytes == (tmp_path / OUTPUT_NAME).read_bytes(), (
        "re-running the builder on identical registries must produce identical bytes"
    )
    assert first_bytes.endswith(b"\n")
    assert "3 apps" in first.stdout


def test_build_stamps_the_same_pin_the_shipped_catalog_carries(tmp_path: Path) -> None:
    """First-party installs resolve against the shipped catalog's pin, so the
    builder must stamp exactly that commit — never a branch or a moving tag."""
    run = _run_build(tmp_path, [{"name": "alpha"}], [])

    assert run.returncode == 0, run.stderr
    meta = _read_output(tmp_path)["meta"]
    assert meta["commit"] == catalog_pin()
    assert meta["commit_date"], "the pin needs a date for review context"
    assert "CLI-Anything" in meta["source"]


def test_build_with_empty_registries_writes_an_empty_catalog(tmp_path: Path) -> None:
    run = _run_build(tmp_path, [], [])

    assert run.returncode == 0, run.stderr
    payload = _read_output(tmp_path)
    assert payload["apps"] == []
    assert payload["meta"]["commit"], "the pin survives even with no apps"
    assert "0 apps" in run.stdout


def test_build_with_duplicate_app_id_fails_and_writes_nothing(tmp_path: Path) -> None:
    """Two registries agreeing on one app id is a data error the build refuses."""
    dup = {"name": "alpha", "description": "declared in both registries"}
    run = _run_build(tmp_path, [dup], [dup])

    assert run.returncode != 0
    assert "alpha" in run.stderr
    assert not (tmp_path / OUTPUT_NAME).exists(), (
        "a rejected registry set must not leave a snapshot behind"
    )


def test_build_with_a_missing_registry_fails_before_writing(tmp_path: Path) -> None:
    """Input collection cannot proceed when a registry file is absent."""
    run = _run_build(tmp_path, [{"name": "alpha"}], public=None)

    assert run.returncode != 0
    assert not (tmp_path / OUTPUT_NAME).exists()

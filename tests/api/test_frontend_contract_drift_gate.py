from __future__ import annotations

import json
from pathlib import Path

from deeptutor.api.contracts.export import write_contracts


def test_gate_passes_when_contracts_match_the_app(tmp_path: Path) -> None:
    write_contracts(tmp_path)

    assert write_contracts(tmp_path, check=True) == []


def test_gate_flags_stale_openapi_schema_without_rewriting_it(tmp_path: Path) -> None:
    write_contracts(tmp_path)
    target = tmp_path / "openapi.json"
    stale = json.loads(target.read_text(encoding="utf-8"))
    stale["info"]["title"] = stale["info"]["title"] + " (stale)"
    target.write_text(
        json.dumps(stale, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    changed = write_contracts(tmp_path, check=True)

    assert changed == ["openapi.json"]
    kept = json.loads(target.read_text(encoding="utf-8"))
    assert kept["info"]["title"].endswith(" (stale)")

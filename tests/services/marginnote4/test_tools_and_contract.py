from __future__ import annotations

import asyncio
import json
from pathlib import Path

from deeptutor.services.marginnote4.service import MarginNote4Service
from deeptutor.services.marginnote4.tools import MARGINNOTE4_TOOL_TYPES


def test_protocol_fixture_matches_runtime_contract() -> None:
    fixture = json.loads(Path("contracts/marginnote4/protocol-v1.json").read_text(encoding="utf-8"))
    assert fixture["protocol_version"] == 1
    assert fixture["security"]["database_selection_header"] is None
    assert "operation_id" in fixture["push_example"]
    assert set(fixture["object_fields"]) >= {
        "protocol_version",
        "library_id",
        "device_id",
        "object_id",
        "object_type",
        "revision",
        "updated_at",
        "source_locator",
    }


def test_seven_read_tools_have_stable_names() -> None:
    assert [tool().name for tool in MARGINNOTE4_TOOL_TYPES] == [
        "marginnote_search",
        "marginnote_read",
        "marginnote_list",
        "marginnote_documents",
        "marginnote_links",
        "marginnote_tags",
        "marginnote_cards",
    ]


def test_read_tools_require_server_injected_context(tmp_path: Path) -> None:
    service = MarginNote4Service(tmp_path / "bridge.sqlite3")
    search = next(tool for tool in MARGINNOTE4_TOOL_TYPES if tool().name == "marginnote_search")
    unavailable = asyncio.run(search().execute(query="anything"))
    assert unavailable.success is False

    token, claim = None, None
    session, code = service.create_pairing_session(
        user_id="user-a", library_id="library-a", library_name="Library A"
    )
    claimed = service.claim_pairing_session(
        pairing_code=code, device_name="Mac", device_kind="macos"
    )
    service.confirm_pairing_session(user_id="user-a", session_id=session.session_id)
    token, _ = service.complete_pairing(
        device_id=claimed["device_id"], claim_secret=claimed["claim_secret"]
    )
    device = service.authenticate_device(token)
    service.push(
        device,
        protocol_version=1,
        operation_id="op-1",
        objects=[
            {
                "object_id": "note-1",
                "object_type": "note",
                "revision": 1,
                "title": "resilience",
                "content": "Systems fail in combination.",
                "source_locator": {"uri": "marginnote3app://note/1"},
            }
        ],
        deletions=[],
    )

    result = asyncio.run(
        search().execute(
            query="systems",
            _service=service,
            _user_id="user-a",
            _library_id="library-a",
        )
    )
    assert result.success is True
    assert result.metadata[0]["object_id"] == "note-1"

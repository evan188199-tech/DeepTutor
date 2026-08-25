from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.notebook.service import NotebookManager, RecordType
from deeptutor.video_learning import notebook_notes


def test_video_note_crud_and_default_notebook(tmp_path: Path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path / "notebooks"))

    created = notebook_notes.create_video_note(
        video_id="dQw4w9WgXcQ",
        position_ms=15_000,
        body="important beat",
        title="Demo",
        instance_origin="http://127.0.0.1:3000",
        manager=manager,
    )
    assert created["notebook_id"]
    assert created["record_id"]
    assert created["position_ms"] == 15_000
    assert created["body"] == "important beat"
    assert "15:00" in created["title"] or created["title"].startswith("0:15")

    notebook = manager.get_notebook(created["notebook_id"])
    assert notebook is not None
    assert notebook["name"] == "Video Learning"
    assert notebook["records"][0]["type"] in {RecordType.VIDEO_NOTE, RecordType.VIDEO_NOTE.value, "video_note"}

    listed = notebook_notes.list_video_notes("dQw4w9WgXcQ", manager=manager)
    assert len(listed) == 1
    assert listed[0]["record_id"] == created["record_id"]

    updated = notebook_notes.update_video_note(
        created["notebook_id"],
        created["record_id"],
        "updated body",
        manager=manager,
    )
    assert updated["body"] == "updated body"

    assert notebook_notes.delete_video_note(
        created["notebook_id"],
        created["record_id"],
        manager=manager,
    )
    assert notebook_notes.list_video_notes("dQw4w9WgXcQ", manager=manager) == []


def test_old_notebook_json_remains_readable(tmp_path: Path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    notebook = manager.create_notebook(name="Legacy", description="pre-video-note")
    notebook_path = tmp_path / "notebooks" / f"{notebook['id']}.json"
    payload = json.loads(notebook_path.read_text())
    payload["records"] = [
        {
            "id": "abcd1234",
            "type": "chat",
            "title": "Old chat",
            "summary": "hello",
            "user_query": "hi",
            "output": "hello there",
            "metadata": {},
            "created_at": 1.0,
            "kb_name": None,
        }
    ]
    notebook_path.write_text(json.dumps(payload, indent=2) + "\n")

    loaded = manager.get_notebook(notebook["id"])
    assert loaded is not None
    assert loaded["records"][0]["type"] == "chat"
    assert notebook_notes.list_video_notes("missing", notebook_id=notebook["id"], manager=manager) == []

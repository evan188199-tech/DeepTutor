"""CLI tests for ``deeptutor notebook`` list/create/show/remove-record commands."""

from __future__ import annotations

import json
from pathlib import Path
import time
import uuid

from typer.testing import CliRunner

from deeptutor.services.notebook.service import NotebookCorruptedError
from deeptutor_cli.main import app

runner = CliRunner()


class FakeNotebookManager:
    """Fake NotebookManager covering list/create/show/remove-record paths."""

    def __init__(self) -> None:
        self.notebooks: dict[str, dict] = {}
        self.corrupted_ids: set[str] = set()

    def _raise_if_corrupted(self, notebook_id: str) -> None:
        if notebook_id in self.corrupted_ids:
            raise NotebookCorruptedError(
                notebook_id,
                Path(f"{notebook_id}.json"),
                ValueError("Expecting value: line 1 column 1 (char 0)"),
            )

    def list_notebooks(self) -> list[dict]:
        return [
            {**notebook, "record_count": len(notebook["records"])}
            for notebook in self.notebooks.values()
        ]

    def create_notebook(
        self,
        name: str,
        description: str = "",
        color: str = "#3B82F6",
        icon: str = "book",
    ) -> dict:
        notebook = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "description": description,
            "color": color,
            "icon": icon,
            "created_at": time.time(),
            "updated_at": time.time(),
            "records": [],
        }
        self.notebooks[notebook["id"]] = notebook
        return notebook

    def get_notebook(self, notebook_id: str) -> dict | None:
        self._raise_if_corrupted(notebook_id)
        return self.notebooks.get(notebook_id)

    def add_record(
        self,
        notebook_ids: list[str],
        record_type: str,
        title: str,
        user_query: str,
        output: str,
    ) -> dict:
        record = {
            "id": str(uuid.uuid4())[:8],
            "type": record_type,
            "title": title,
            "user_query": user_query,
            "output": output,
        }
        for notebook_id in notebook_ids:
            if notebook_id in self.notebooks:
                self.notebooks[notebook_id]["records"].append(record)
        return {"record": record, "added_to_notebooks": notebook_ids}

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        self._raise_if_corrupted(notebook_id)
        notebook = self.notebooks.get(notebook_id)
        if not notebook:
            return False
        for index, record in enumerate(notebook["records"]):
            if record["id"] == record_id:
                notebook["records"].pop(index)
                return True
        return False


_fake_manager = FakeNotebookManager()


def _reset_fake_state() -> None:
    _fake_manager.notebooks.clear()
    _fake_manager.corrupted_ids.clear()


def _patch_facade(monkeypatch) -> None:
    """Patch DeepTutorApp methods to use the shared fake manager."""

    def _list_notebooks(self):
        return _fake_manager.list_notebooks()

    def _create_notebook(self, name, description="", **kwargs):
        return _fake_manager.create_notebook(name=name, description=description)

    def _get_notebook(self, notebook_id):
        return _fake_manager.get_notebook(notebook_id)

    def _remove_record(self, notebook_id, record_id):
        return _fake_manager.remove_record(notebook_id, record_id)

    from deeptutor.app import facade

    monkeypatch.setattr(facade.DeepTutorApp, "list_notebooks", _list_notebooks)
    monkeypatch.setattr(facade.DeepTutorApp, "create_notebook", _create_notebook)
    monkeypatch.setattr(facade.DeepTutorApp, "get_notebook", _get_notebook)
    monkeypatch.setattr(facade.DeepTutorApp, "remove_record", _remove_record)


def test_notebook_list_prints_notebook_table(monkeypatch) -> None:
    """list should render one table row per notebook with its id and name."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    first = _fake_manager.create_notebook("Physics", description="mechanics")
    second = _fake_manager.create_notebook("Chemistry")

    result = runner.invoke(app, ["notebook", "list"])

    assert result.exit_code == 0, result.output
    assert "Notebooks" in result.output
    assert first["id"] in result.output
    assert "Physics" in result.output
    assert second["id"] in result.output
    assert "Chemistry" in result.output


def test_notebook_list_empty_store_still_succeeds(monkeypatch) -> None:
    """list on an empty store should exit 0 and still render the table header."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    result = runner.invoke(app, ["notebook", "list"])

    assert result.exit_code == 0, result.output
    assert "Notebooks" in result.output


def test_notebook_create_persists_and_prints_details(monkeypatch) -> None:
    """create should store the notebook and print its details as JSON."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    result = runner.invoke(
        app,
        ["notebook", "create", "Physics", "--description", "mechanics"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["name"] == "Physics"
    assert payload["description"] == "mechanics"

    stored = _fake_manager.notebooks.get(payload["id"])
    assert stored is not None
    assert stored["name"] == "Physics"
    assert stored["description"] == "mechanics"
    assert stored["records"] == []


def test_notebook_show_rich_prints_notebook_and_records(monkeypatch) -> None:
    """show (rich format) should print the notebook header and each record."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    notebook = _fake_manager.create_notebook("Physics", description="mechanics")
    added = _fake_manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="chat",
        title="Fourier notes",
        user_query="q",
        output="a",
    )
    record = added["record"]

    result = runner.invoke(app, ["notebook", "show", notebook["id"]])

    assert result.exit_code == 0, result.output
    assert "Physics" in result.output
    assert notebook["id"] in result.output
    assert record["id"] in result.output
    assert "chat" in result.output
    assert "Fourier notes" in result.output


def test_notebook_show_json_format_outputs_notebook_payload(monkeypatch) -> None:
    """show --format json should print the notebook dict as parseable JSON."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    notebook = _fake_manager.create_notebook("Physics")
    added = _fake_manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="chat",
        title="Fourier",
        user_query="q",
        output="a",
    )
    record = added["record"]

    result = runner.invoke(app, ["notebook", "show", notebook["id"], "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == notebook["id"]
    assert payload["name"] == "Physics"
    assert [item["id"] for item in payload["records"]] == [record["id"]]


def test_notebook_show_corrupted_notebook_exits_1(monkeypatch) -> None:
    """show should exit 1 with a friendly message on NotebookCorruptedError."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    notebook = _fake_manager.create_notebook("Physics")
    _fake_manager.corrupted_ids.add(notebook["id"])

    result = runner.invoke(app, ["notebook", "show", notebook["id"]])

    assert result.exit_code == 1
    assert "Notebook file is damaged" in result.output


def test_notebook_show_missing_notebook_exits_1(monkeypatch) -> None:
    """show should exit 1 when the notebook does not exist."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    result = runner.invoke(app, ["notebook", "show", "no-such-nb"])

    assert result.exit_code == 1
    assert "Notebook not found" in result.output


def test_notebook_remove_record_removes_only_target_record(monkeypatch) -> None:
    """remove-record should delete the target record and keep the rest."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    notebook = _fake_manager.create_notebook("Physics")
    first = _fake_manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="chat",
        title="keep-a",
        user_query="",
        output="",
    )["record"]
    second = _fake_manager.add_record(
        notebook_ids=[notebook["id"]],
        record_type="chat",
        title="drop-b",
        user_query="",
        output="",
    )["record"]

    result = runner.invoke(app, ["notebook", "remove-record", notebook["id"], second["id"]])

    assert result.exit_code == 0, result.output
    assert f"Removed record {second['id']}" in result.output

    stored = _fake_manager.notebooks[notebook["id"]]
    assert [record["id"] for record in stored["records"]] == [first["id"]]


def test_notebook_remove_record_corrupted_notebook_exits_1(monkeypatch) -> None:
    """remove-record should exit 1 with a friendly message on NotebookCorruptedError."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    notebook = _fake_manager.create_notebook("Physics")
    _fake_manager.corrupted_ids.add(notebook["id"])

    result = runner.invoke(app, ["notebook", "remove-record", notebook["id"], "any-record"])

    assert result.exit_code == 1
    assert "Notebook file is damaged" in result.output


def test_notebook_remove_record_missing_record_exits_1(monkeypatch) -> None:
    """remove-record should exit 1 when the record does not exist."""
    _patch_facade(monkeypatch)
    _reset_fake_state()

    notebook = _fake_manager.create_notebook("Physics")

    result = runner.invoke(
        app,
        ["notebook", "remove-record", notebook["id"], "no-such-record"],
    )

    assert result.exit_code == 1
    assert "Record not found" in result.output

from __future__ import annotations

import json

import pytest

from deeptutor.services.rag import provider_binding as binding
from deeptutor.services.rag.factory import DEFAULT_PROVIDER


def write_kb_config(root, entry=None, *, raw=None):
    payload = {"knowledge_bases": {"kb": entry}} if entry is not None else raw
    path = root / "kb_config.json"
    path.write_text(json.dumps(payload) if raw is None else raw)
    return path


def write_metadata(root, provider=None, *, raw=None, name="kb"):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "metadata.json"
    if raw is not None:
        path.write_text(raw)
    else:
        payload = {"rag_provider": provider}
        path.write_text(json.dumps(payload))
    return path


def test_kb_config_entry_returns_bound_entry(tmp_path):
    entry = {"rag_provider": "pageindex", "status": "ready"}
    write_kb_config(tmp_path, entry)
    assert binding.load_kb_config_entry(tmp_path, "kb") == entry


@pytest.mark.parametrize("scenario", ["no_file", "unknown_kb", "entry_list", "entry_null"])
def test_kb_config_entry_missing_or_non_dict_returns_empty(tmp_path, scenario):
    if scenario != "no_file":
        entry = [] if scenario == "entry_list" else None
        write_kb_config(tmp_path, entry)
    assert binding.load_kb_config_entry(tmp_path, "kb") == {}


@pytest.mark.parametrize("scenario", ["corrupt_json", "top_level_list", "config_is_dir"])
def test_kb_config_entry_unreadable_returns_empty(tmp_path, scenario):
    if scenario == "corrupt_json":
        write_kb_config(tmp_path, raw='{"knowledge_bases": broken')
    elif scenario == "top_level_list":
        write_kb_config(tmp_path, raw="[]")
    else:
        (tmp_path / "kb_config.json").mkdir()
    assert binding.load_kb_config_entry(tmp_path, "kb") == {}


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (" PageIndex ", "pageindex"),
        ("graphrag", "graphrag"),
        ("vanished-provider", DEFAULT_PROVIDER),
    ],
)
def test_metadata_provider_normalizes_known_and_unknown(tmp_path, stored, expected):
    write_metadata(tmp_path, stored)
    assert binding.load_metadata_provider(tmp_path, "kb") == expected


@pytest.mark.parametrize(
    "scenario", ["no_file", "no_key", "empty_value", "corrupt_json", "metadata_is_dir"]
)
def test_metadata_provider_missing_or_invalid_returns_none(tmp_path, scenario):
    if scenario == "no_key":
        write_metadata(tmp_path, raw=json.dumps({"provider": "pageindex"}))
    elif scenario == "empty_value":
        write_metadata(tmp_path, "")
    elif scenario == "corrupt_json":
        write_metadata(tmp_path, raw="{broken")
    elif scenario == "metadata_is_dir":
        (tmp_path / "kb").mkdir(parents=True)
        (tmp_path / "kb" / "metadata.json").mkdir()
    assert binding.load_metadata_provider(tmp_path, "kb") is None


def test_resolve_prefers_kb_config_entry_over_legacy_metadata(tmp_path):
    write_kb_config(tmp_path, {"rag_provider": "lightrag"})
    write_metadata(tmp_path, "pageindex")
    assert binding.resolve_bound_provider(tmp_path, "kb") == "lightrag"


@pytest.mark.parametrize("scenario", ["entry_without_provider", "entry_not_dict"])
def test_resolve_falls_back_to_metadata_when_config_entry_has_no_provider(tmp_path, scenario):
    write_kb_config(tmp_path, {} if scenario == "entry_without_provider" else "not-a-dict")
    write_metadata(tmp_path, "PageIndex")
    assert binding.resolve_bound_provider(tmp_path, "kb") == "pageindex"


def test_resolve_normalizes_provider_stored_in_kb_config(tmp_path):
    write_kb_config(tmp_path, {"rag_provider": " PageIndex "})
    assert binding.resolve_bound_provider(tmp_path, "kb") == "pageindex"


@pytest.mark.parametrize("scenario", ["no_binding_at_all", "null_kb_name", "empty_kb_name"])
def test_resolve_defaults_when_nothing_is_bound(tmp_path, scenario):
    if scenario == "no_binding_at_all":
        write_kb_config(tmp_path, {"status": "ready"})
    name = None if scenario == "null_kb_name" else ""
    assert binding.resolve_bound_provider(tmp_path, name) == DEFAULT_PROVIDER

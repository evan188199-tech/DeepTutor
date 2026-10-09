"""Contract and boundary tests for workspace resource selections.

Covers the missing-input and illegal-input branches of
``WorkspaceResources``, ``turn_resource_selection``,
``current_resources`` and ``validate_resources``. The resource catalog is
stubbed so the contract is tested without skills, MCP servers or knowledge
bases being present.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import pytest

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import get_account_path_service, user_context
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError
from deeptutor.services.workspace.context import WorkspaceScope, workspace_context
from deeptutor.services.workspace.resources import (
    WorkspaceResources,
    current_resources,
    turn_resource_selection,
    validate_resources,
)

STUB_CATALOG = {
    "skills": [{"id": "alpha"}, {"id": "beta"}],
    "mcp": [{"id": "deployment:tools"}],
    "knowledge_bases": [{"id": "account:kb:notes"}],
}


@pytest.fixture(autouse=True)
def stubbed_resource_catalog(monkeypatch):
    import deeptutor.services.workspace.resources as resources_module

    monkeypatch.setattr(
        resources_module,
        "resource_catalog",
        lambda *, workspace_id="": {kind: list(items) for kind, items in STUB_CATALOG.items()},
    )


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)
    user = CurrentUser(
        "resources-test", "test", "admin", UserScope("admin", "resources-test", tmp_path)
    )
    with user_context(user):
        get_account_path_service().ensure_all_directories()
        yield ContentWorkspaceService()


# --- WorkspaceResources model contract --------------------------------------


def test_missing_fields_default_to_unrestricted() -> None:
    assert WorkspaceResources().model_dump() == {
        "skills": None,
        "mcp": None,
        "knowledge_bases": None,
    }
    assert WorkspaceResources.model_validate({}).model_dump() == WorkspaceResources().model_dump()


def test_empty_selection_is_valid_and_stays_empty() -> None:
    row = WorkspaceResources.model_validate({"skills": [], "mcp": [], "knowledge_bases": []})
    assert row.model_dump() == {"skills": [], "mcp": [], "knowledge_bases": []}


def test_ids_are_stripped_and_deduplicated_in_first_seen_order() -> None:
    row = WorkspaceResources(skills=[" beta ", "alpha", "beta", " alpha "])
    assert row.skills == ["beta", "alpha"]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        WorkspaceResources(skills=["alpha"], knowledge_bases=["account:kb:notes"], other=["x"])


def test_non_string_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkspaceResources(skills=[1])
    with pytest.raises(ValidationError):
        WorkspaceResources(mcp=[None])


def test_selections_must_be_lists() -> None:
    with pytest.raises(ValidationError):
        WorkspaceResources(skills="alpha")


def test_blank_and_overlong_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkspaceResources(skills=["   "])
    with pytest.raises(ValidationError):
        WorkspaceResources(knowledge_bases=["a" * 513])
    assert WorkspaceResources(skills=["a" * 512]).skills == ["a" * 512]


def test_selection_length_boundary_is_enforced() -> None:
    thousand = [f"s{i:04d}" for i in range(1000)]
    assert WorkspaceResources(skills=thousand).skills == thousand
    with pytest.raises(ValidationError):
        WorkspaceResources(skills=[*thousand, "overflow"])


# --- validate_resources contract --------------------------------------------


def test_missing_value_validates_to_all_unrestricted() -> None:
    assert validate_resources(None) == {
        "skills": None,
        "mcp": None,
        "knowledge_bases": None,
    }
    assert validate_resources({}) == validate_resources(None)


def test_non_mapping_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_resources(42)


def test_invalid_selections_are_rejected_before_catalog_lookup() -> None:
    with pytest.raises(ValidationError):
        validate_resources({"skills": ["   "]})
    with pytest.raises(ValidationError):
        validate_resources({"mcp": ["a" * 513]})


def test_output_normalizes_and_preserves_unrestricted_kinds() -> None:
    policy = validate_resources({"skills": [" beta ", "alpha", "beta"], "mcp": None})
    assert policy == {
        "skills": ["beta", "alpha"],
        "mcp": None,
        "knowledge_bases": None,
    }


def test_unknown_ids_are_rejected_for_every_kind() -> None:
    with pytest.raises(WorkspaceError, match="Unknown or inaccessible skills resource."):
        validate_resources({"skills": ["ghost"]})
    with pytest.raises(WorkspaceError, match="Unknown or inaccessible mcp resource."):
        validate_resources({"mcp": ["deployment:missing"]})
    with pytest.raises(WorkspaceError, match="Unknown or inaccessible knowledge_bases resource."):
        validate_resources({"knowledge_bases": ["account:kb:ghost"]})


def test_previous_selection_preserves_stale_but_not_new_unknown_ids() -> None:
    previous = {"skills": ["legacy"], "mcp": None, "knowledge_bases": None}
    policy = validate_resources({"skills": ["alpha", "legacy"]}, previous=previous)
    assert policy["skills"] == ["alpha", "legacy"]
    with pytest.raises(WorkspaceError):
        validate_resources({"skills": ["legacy", "ghost"]}, previous=previous)


def test_unrestricted_kinds_skip_catalog_validation() -> None:
    policy = validate_resources({"skills": None, "mcp": None, "knowledge_bases": None})
    assert policy == {"skills": None, "mcp": None, "knowledge_bases": None}


# --- turn_resource_selection and current_resources contract -----------------


def test_current_resources_defaults_without_scope_and_narrows_to_turn() -> None:
    assert current_resources().model_dump() == {
        "skills": None,
        "mcp": None,
        "knowledge_bases": None,
    }
    with turn_resource_selection(skills=["outside", "outside", "inside"]):
        row = current_resources()
    assert row.skills == ["outside", "inside"]
    assert row.mcp is None
    assert row.knowledge_bases is None


def test_turn_selection_intersects_workspace_allowlist(account) -> None:
    wid = account.create_workspace(
        "Selected", resources={"skills": ["alpha", "beta"], "mcp": ["deployment:tools"]}
    )["workspace_id"]
    with (
        workspace_context(wid),
        turn_resource_selection(
            skills=["beta", "ghost"], mcp=["deployment:tools", "deployment:ghost"]
        ),
    ):
        row = current_resources()
    assert row.skills == ["beta"]
    assert row.mcp == ["deployment:tools"]
    assert row.knowledge_bases is None


def test_turn_selection_passes_through_unrestricted_workspace(account) -> None:
    wid = account.create_workspace("Open")["workspace_id"]
    with workspace_context(wid), turn_resource_selection(skills=["zeta", "zeta", "y"]):
        row = current_resources()
    assert row.skills == ["zeta", "y"]
    assert row.mcp is None


def test_turn_selection_clips_to_empty_workspace_selection(account) -> None:
    wid = account.create_workspace("Locked", resources={"skills": []})["workspace_id"]
    with workspace_context(wid), turn_resource_selection(skills=["alpha"]):
        row = current_resources()
    assert row.skills == []
    assert row.mcp is None


def test_turn_selection_is_reset_after_the_context(account) -> None:
    wid = account.create_workspace("Reset", resources={"skills": ["alpha", "beta"], "mcp": []})[
        "workspace_id"
    ]
    with workspace_context(wid), turn_resource_selection(skills=["beta"]):
        assert current_resources().skills == ["beta"]
    with workspace_context(wid):
        row = current_resources()
    assert row.skills == ["alpha", "beta"]
    assert row.mcp == []


def test_nested_turn_selection_replaces_outer_and_restores_it() -> None:
    with turn_resource_selection(skills=["outer"]):
        assert current_resources().skills == ["outer"]
        with turn_resource_selection(mcp=["inner"]):
            row = current_resources()
            assert row.skills is None
            assert row.mcp == ["inner"]
        assert current_resources().skills == ["outer"]


def test_missing_workspace_row_raises(account, tmp_path) -> None:
    scope = WorkspaceScope("ws_missing", tmp_path, tmp_path)
    with workspace_context(scope), pytest.raises(WorkspaceError, match="Workspace not found."):
        current_resources()


def test_missing_row_without_explicit_workspace_inherits_default(account) -> None:
    with workspace_context():
        row = current_resources()
    assert row.model_dump() == {"skills": None, "mcp": None, "knowledge_bases": None}

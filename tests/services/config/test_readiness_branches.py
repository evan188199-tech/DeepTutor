"""Branch coverage for the readiness matrix's failure, degradation and
aggregation paths.

Complements ``test_readiness.py`` (happy paths, value-freeness, code
declarations) and stays clear of the router layer (see the settings-router
fallback card) and of ``core.config_manager``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deeptutor.services.config.model_catalog import SERVICE_NAMES
from deeptutor.services.config.readiness import (
    READINESS_STATES,
    SEVERITIES,
    _module_available,
    _redis_reachable,
    _selected_remote_parser_reachable,
    catalog_service_rows,
    coordination_rows,
    document_parser_rows,
    knowledge_base_rows,
    readiness_snapshot,
    row_severity,
    tool_rows,
    video_learning_rows,
    visualizer_rows,
)


def _notice_codes(snapshot: dict, severity: str) -> list[str]:
    return [notice["code"] for notice in snapshot["notices"] if notice["severity"] == severity]


def _row(rows: list[dict], row_id: str) -> dict:
    return next(row for row in rows if row["id"] == row_id)


def _catalog_with(**service_overrides) -> dict:
    services = {
        name: {"active_profile_id": None, "active_model_id": None, "profiles": []}
        for name in SERVICE_NAMES
    }
    services.update(service_overrides)
    return {"services": services}


# ---------------------------------------------------------------------------
# catalog_service_rows: malformed payloads degrade instead of crashing
# ---------------------------------------------------------------------------


def test_malformed_catalog_payloads_degrade_to_not_selected() -> None:
    for catalog in ({}, {"services": None}, {"services": "garbage"}):
        rows = catalog_service_rows(catalog)
        assert len(rows) == len(SERVICE_NAMES)
        assert {row["state"] for row in rows} == {"not_selected"}
        assert {row["detail_code"] for row in rows} == {"active_profile_not_selected"}
        assert all(row["available"] is False for row in rows)


def test_service_entries_with_junk_shapes_still_produce_rows() -> None:
    catalog = _catalog_with(
        llm={"active_profile_id": "gone", "profiles": ["not-a-dict"]},
        embedding={"active_profile_id": None, "profiles": "not-a-list"},
    )

    rows = catalog_service_rows(catalog)

    llm = _row(rows, "catalog.llm")
    assert llm["state"] == "misconfigured"
    assert llm["detail_code"] == "active_profile_missing"
    assert llm["available"] is False
    embedding = _row(rows, "catalog.embedding")
    assert embedding["state"] == "not_selected"
    assert embedding["detail_code"] == "active_profile_not_selected"
    assert embedding["available"] is False


# ---------------------------------------------------------------------------
# catalog_service_rows: search provider degradation ladder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "api_key", "base_url", "state", "detail_code"),
    [
        ("", "", "", "not_selected", "provider_not_selected"),
        ("none", "unused-key", "", "not_selected", "provider_not_selected"),
        ("brave", "", "", "misconfigured", "required_credential_missing"),
        ("searxng", "some-key", "", "misconfigured", "required_credential_missing"),
        ("brave", "test-key", "", "enabled_verified", "configuration_verified"),
        ("duckduckgo", "", "", "enabled_verified", "configuration_verified"),
    ],
)
def test_search_provider_states_degrade_by_configuration(
    provider: str, api_key: str, base_url: str, state: str, detail_code: str
) -> None:
    catalog = _catalog_with(
        search={
            "active_profile_id": "search-profile",
            "active_model_id": None,
            "profiles": [
                {
                    "id": "search-profile",
                    "provider": provider,
                    "api_key": api_key,
                    "base_url": base_url,
                }
            ],
        }
    )

    search = _row(catalog_service_rows(catalog), "catalog.search")

    assert search["state"] == state
    assert search["detail_code"] == detail_code
    ready = state == "enabled_verified"
    assert search["available"] is ready
    assert search["configured"] is ready
    assert search["verified"] is ready


def test_search_row_serialization_stays_value_free() -> None:
    catalog = _catalog_with(
        search={
            "active_profile_id": "search-profile",
            "profiles": [
                {
                    "id": "search-profile",
                    "provider": "brave",
                    "api_key": "super-secret-key",
                    "base_url": "https://secret.example.test",
                }
            ],
        }
    )

    serialized = json.dumps(catalog_service_rows(catalog))

    assert "super-secret-key" not in serialized
    assert "secret.example.test" not in serialized


# ---------------------------------------------------------------------------
# catalog_service_rows: model selection failures and provider-link success
# ---------------------------------------------------------------------------


def test_selected_profile_without_active_model_reports_not_selected() -> None:
    catalog = _catalog_with(
        llm={
            "active_profile_id": "llm-profile",
            "active_model_id": None,
            "profiles": [{"id": "llm-profile", "models": [{"id": "m1", "model": "some-model"}]}],
        }
    )

    llm = _row(catalog_service_rows(catalog), "catalog.llm")

    assert llm["state"] == "not_selected"
    assert llm["detail_code"] == "active_model_not_selected"
    assert llm["enabled"] is False
    assert llm["available"] is False


def test_provider_linked_profile_resolves_and_stays_verified() -> None:
    catalog = _catalog_with(
        llm={
            "active_profile_id": "llm-profile",
            "active_model_id": "m1",
            "provider_ref": {"connection_id": "conn-1"},
            "profiles": [
                {
                    "id": "llm-profile",
                    "provider_ref": {"connection_id": "conn-1"},
                    "models": [{"id": "m1", "model": "some-model"}],
                }
            ],
        }
    )
    catalog["connections"] = [
        {
            "id": "conn-1",
            "name": "Shared connection",
            "api_key": "linked-secret",
            "base_url": "",
        }
    ]

    rows = catalog_service_rows(catalog)

    llm = _row(rows, "catalog.llm")
    assert llm["state"] == "enabled_verified"
    assert llm["detail_code"] == "configuration_verified"
    assert llm["available"] is True
    assert "linked-secret" not in json.dumps(rows)


# ---------------------------------------------------------------------------
# document_parser_rows: unselected engines, blank ids, unknown selection
# ---------------------------------------------------------------------------


def test_parser_rows_grade_unselected_installed_and_missing_engines() -> None:
    entries = [
        {"id": "", "name": "Blank entry", "available": True},
        {"id": "tika", "name": "Tika", "available": True},
        {"id": "docling", "name": "Docling", "available": False},
    ]

    rows = document_parser_rows(entries, "", {})

    assert [row["id"] for row in rows] == ["parser.tika", "parser.docling"]
    tika = rows[0]
    assert tika["state"] == "available_disabled"
    assert tika["detail_code"] == "parser_not_selected"
    assert tika["required"] is False
    assert tika["available"] is True
    assert tika["configured"] is False
    docling = rows[1]
    assert docling["state"] == "unavailable"
    assert docling["detail_code"] == "parser_package_missing"
    assert docling["available"] is False


def test_unknown_selected_parser_gets_its_own_row_and_blocks() -> None:
    rows = document_parser_rows(
        [{"id": "tika", "name": "Tika", "available": True}],
        "removed-engine",
        {"tika": {"ready": True}},
    )

    selected = _row(rows, "parser.removed-engine")
    assert selected["state"] == "misconfigured"
    assert selected["detail_code"] == "selected_parser_unknown"
    assert selected["required"] is True

    snapshot = readiness_snapshot(rows)
    assert snapshot["ok"] is False
    assert _notice_codes(snapshot, "blocker") == ["selected_parser_unknown"]


@pytest.mark.parametrize(
    ("report", "reachable", "state", "detail_code"),
    [
        ({"ready": False, "reason": "update_required"}, None, "misconfigured", "update_required"),
        ({"ready": False}, None, "misconfigured", "parser_not_ready"),
        ({"ready": True}, True, "enabled_verified", "remote_endpoint_verified"),
        ({"ready": True}, None, "enabled_verified", "configuration_verified"),
    ],
)
def test_selected_parser_outcome_codes_follow_report_and_reachability(
    report: dict, reachable, state: str, detail_code: str
) -> None:
    rows = document_parser_rows(
        [{"id": "tika", "name": "Tika", "available": True}],
        "tika",
        {"tika": report},
        selected_remote_reachable=reachable,
    )

    tika = rows[0]
    assert tika["state"] == state
    assert tika["detail_code"] == detail_code
    assert tika["verified"] is (state == "enabled_verified")


# ---------------------------------------------------------------------------
# knowledge_base_rows: every status grade
# ---------------------------------------------------------------------------


def test_no_knowledge_base_is_neutral_not_a_fault() -> None:
    rows = knowledge_base_rows([])

    assert len(rows) == 1
    assert rows[0]["id"] == "knowledge.none"
    assert rows[0]["state"] == "not_selected"
    assert rows[0]["detail_code"] == "no_knowledge_base"
    assert rows[0]["available"] is True
    assert readiness_snapshot(rows)["ok"] is True


def test_knowledge_base_rows_grade_each_status() -> None:
    entries = [
        {"label": "Ready KB", "status": "ready", "needs_reindex": False},
        {"status": "READY", "needs_reindex": False},
        {"label": "Building KB", "status": "processing"},
        {"label": "Stale KB", "status": "ready", "needs_reindex": True},
        {"label": "Unbound KB", "status": "ready", "prerequisites_ready": False},
        {"label": "Broken KB", "status": "error"},
    ]

    rows = knowledge_base_rows(entries)

    assert rows[0]["state"] == "enabled_verified"
    assert rows[0]["detail_code"] == "knowledge_base_ready"
    assert rows[1]["label"] == "Knowledge base 2"
    assert rows[1]["detail_code"] == "knowledge_base_ready"
    assert rows[2]["state"] == "unavailable"
    assert rows[2]["detail_code"] == "knowledge_base_building"
    assert rows[2]["available"] is False
    assert rows[3]["state"] == "misconfigured"
    assert rows[3]["detail_code"] == "knowledge_base_needs_reindex"
    assert rows[3]["configured"] is False
    assert rows[4]["detail_code"] == "rag_prerequisite_missing"
    assert rows[5]["state"] == "misconfigured"
    assert rows[5]["detail_code"] == "knowledge_base_not_ready"

    snapshot = readiness_snapshot(rows)
    assert snapshot["ok"] is False
    assert _notice_codes(snapshot, "warning") == [
        "knowledge_base_needs_reindex",
        "rag_prerequisite_missing",
        "knowledge_base_not_ready",
    ]


# ---------------------------------------------------------------------------
# visualizer_rows: ready, missing runtime, not installed, disabled, blank ids
# ---------------------------------------------------------------------------


def test_visualizer_rows_cover_ready_missing_disabled_and_blank_ids() -> None:
    entries = [
        {"id": "", "installed": True, "enabled": True},
        {"id": "mermaid", "display_name": "Mermaid", "installed": True, "enabled": True},
        {"id": "manim_video", "installed": True, "enabled": True},
        {"id": "chartjs", "installed": False, "enabled": True},
        {"id": "geogebra", "installed": True, "enabled": False},
    ]

    rows = visualizer_rows(entries, manim_available=True)

    assert [row["id"] for row in rows] == [
        "visualizer.mermaid",
        "visualizer.manim_video",
        "visualizer.chartjs",
        "visualizer.geogebra",
    ]
    assert rows[0]["state"] == "enabled_verified"
    assert rows[0]["detail_code"] == "visualizer_ready"
    assert rows[0]["label"] == "Mermaid"
    # A manim-family visualizer with manim installed is ready like any other.
    assert rows[1]["state"] == "enabled_verified"
    assert rows[2]["state"] == "unavailable"
    assert rows[2]["detail_code"] == "visualizer_not_installed"
    assert rows[2]["available"] is False
    assert rows[3]["state"] == "available_disabled"
    assert rows[3]["detail_code"] == "visualizer_disabled"
    assert readiness_snapshot(rows)["ok"] is True


# ---------------------------------------------------------------------------
# tool_rows: disabled tools follow their backend's usability
# ---------------------------------------------------------------------------


def test_tool_rows_disabled_states_follow_backend_usability() -> None:
    dependency_rows = {
        "catalog.search": {"id": "catalog.search", "state": "available_disabled"},
        "catalog.imagegen": {"id": "catalog.imagegen", "state": "misconfigured"},
    }

    tools = tool_rows(["paper_search", "reason"], dependency_rows)

    # Disabled with a usable backend: one toggle away, so available.
    web_search = _row(tools, "tool.web_search")
    assert web_search["state"] == "available_disabled"
    assert web_search["detail_code"] == "tool_disabled"
    assert web_search["available"] is True
    # Disabled whose backend was configured and broke: not offered at all.
    imagegen = _row(tools, "tool.imagegen")
    assert imagegen["state"] == "unavailable"
    assert imagegen["detail_code"] == "tool_backend_unavailable"
    assert imagegen["available"] is False
    # Enabled tool without a backing service dependency is simply ready.
    paper_search = _row(tools, "tool.paper_search")
    assert paper_search["state"] == "enabled_verified"
    assert paper_search["detail_code"] == "tool_ready"
    # Enabled with a usable backend: ready too.
    reason = _row(tools, "tool.reason")
    assert reason["state"] == "enabled_verified"
    assert reason["detail_code"] == "tool_ready"


# ---------------------------------------------------------------------------
# video_learning_rows: selection/configuration ladder and unknown providers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("settings", "selected_provider", "invidious_state", "invidious_code"),
    [
        ({}, "youtube", "not_selected", "video_provider_not_configured"),
        (
            {"default_provider": "invidious"},
            "invidious",
            "misconfigured",
            "selected_video_provider_not_configured",
        ),
        (
            {
                "default_provider": "invidious",
                "invidious": {"api_base_url": "https://inv.example.test"},
            },
            "invidious",
            "enabled_verified",
            "configuration_verified",
        ),
        (
            {"invidious": {"api_base_url": "https://inv.example.test"}},
            "youtube",
            "available_disabled",
            "video_provider_not_selected",
        ),
    ],
)
def test_video_learning_rows_follow_selection_and_configuration(
    settings: dict, selected_provider: str, invidious_state: str, invidious_code: str
) -> None:
    rows = video_learning_rows(settings)

    youtube = rows[0]
    assert youtube["id"] == "video.youtube"
    assert youtube["state"] == (
        "enabled_verified" if selected_provider == "youtube" else "available_disabled"
    )
    assert youtube["verified"] is (selected_provider == "youtube")

    invidious = rows[1]
    assert invidious["id"] == "video.invidious"
    assert invidious["state"] == invidious_state
    assert invidious["detail_code"] == invidious_code
    assert len(rows) == 2


def test_unknown_selected_video_provider_adds_a_warning_row() -> None:
    rows = video_learning_rows({"default_provider": "bunny"})

    assert [row["id"] for row in rows] == ["video.youtube", "video.invidious", "video.selected"]
    selected = rows[2]
    assert selected["state"] == "misconfigured"
    assert selected["detail_code"] == "selected_video_provider_unknown"
    assert row_severity(selected) == "warning"


# ---------------------------------------------------------------------------
# coordination_rows: every backend/dual-axis state
# ---------------------------------------------------------------------------


def test_memory_coordination_with_multiple_workers_is_a_blocker() -> None:
    rows, notices = coordination_rows(
        backend="memory",
        backend_workers=2,
        redis_configured=False,
        redis_reachable=False,
    )

    memory = rows[0]
    assert memory["state"] == "misconfigured"
    assert memory["detail_code"] == "multiple_workers_require_redis"
    assert memory["required"] is True
    redis_row = rows[1]
    assert redis_row["state"] == "not_selected"
    assert redis_row["detail_code"] == "redis_not_configured"
    assert notices == []

    snapshot = readiness_snapshot(rows, extra_notices=notices)
    assert snapshot["ok"] is False
    assert _notice_codes(snapshot, "blocker") == ["multiple_workers_require_redis"]


def test_selected_redis_that_is_ready_verifies_and_suggestion_stays_quiet() -> None:
    rows, notices = coordination_rows(
        backend="redis",
        backend_workers=4,
        redis_configured=True,
        redis_reachable=True,
    )

    redis_row = rows[1]
    assert redis_row["state"] == "enabled_verified"
    assert redis_row["detail_code"] == "coordination_ready"
    assert redis_row["verified"] is True
    assert redis_row["required"] is True
    memory = rows[0]
    assert memory["state"] == "available_disabled"
    assert memory["detail_code"] == "coordination_not_selected"
    assert notices == []
    assert readiness_snapshot(rows, extra_notices=notices)["ok"] is True


def test_redis_selected_without_url_blocks_before_any_dial() -> None:
    rows, notices = coordination_rows(
        backend="redis",
        backend_workers=1,
        redis_configured=False,
        redis_reachable=False,
    )

    redis_row = rows[1]
    assert redis_row["state"] == "misconfigured"
    assert redis_row["detail_code"] == "redis_url_missing"
    assert notices == []
    snapshot = readiness_snapshot(rows, extra_notices=notices)
    assert snapshot["ok"] is False
    assert _notice_codes(snapshot, "blocker") == ["redis_url_missing"]


def test_unselected_redis_configured_but_down_reports_unavailable() -> None:
    rows, notices = coordination_rows(
        backend="memory",
        backend_workers=1,
        redis_configured=True,
        redis_reachable=False,
    )

    redis_row = rows[1]
    assert redis_row["state"] == "unavailable"
    assert redis_row["detail_code"] == "redis_unreachable"
    assert redis_row["available"] is False
    # In-memory coordination still carries the install: no fault anywhere.
    assert rows[0]["state"] == "enabled_verified"
    assert notices == []
    assert readiness_snapshot(rows, extra_notices=notices)["ok"] is True


# ---------------------------------------------------------------------------
# readiness_snapshot: aggregation and ordering
# ---------------------------------------------------------------------------


def _blocker_row() -> dict:
    return {
        "id": "catalog.llm",
        "section": "catalog",
        "state": "not_selected",
        "detail_code": "active_profile_not_selected",
        "required": True,
    }


def _warning_row() -> dict:
    return {
        "id": "knowledge.0",
        "section": "knowledge",
        "state": "misconfigured",
        "detail_code": "",
        "required": False,
    }


def _healthy_row() -> dict:
    return {
        "id": "tool.reason",
        "section": "tools",
        "state": "enabled_verified",
        "detail_code": "tool_ready",
        "required": False,
    }


def test_snapshot_orders_notices_by_severity_and_counts_every_state() -> None:
    extra = [
        {"code": "redis_available_but_memory_selected", "severity": "suggestion"},
        {"code": "mystery_notice", "severity": "banana"},
    ]

    snapshot = readiness_snapshot(
        [_healthy_row(), _warning_row(), _blocker_row()], extra_notices=extra
    )

    assert snapshot["ok"] is False
    assert [notice["code"] for notice in snapshot["notices"]] == [
        "active_profile_not_selected",
        "misconfigured",
        "redis_available_but_memory_selected",
        "mystery_notice",
    ]
    summary = snapshot["summary"]
    assert set(summary) == set(READINESS_STATES)
    assert summary["enabled_verified"] == 1
    assert summary["misconfigured"] == 1
    assert summary["not_selected"] == 1
    assert summary["available_disabled"] == 0


def test_empty_snapshot_is_ok_with_zeroed_summary() -> None:
    snapshot = readiness_snapshot([])

    assert snapshot["ok"] is True
    assert snapshot["notices"] == []
    assert snapshot["summary"] == {state: 0 for state in READINESS_STATES}
    assert snapshot["schema_version"] == "deeptutor.settings-readiness/v2"


def test_row_severity_grades_only_broken_required_and_misconfigured() -> None:
    assert row_severity({"required": True, "state": "unavailable"}) == "blocker"
    assert row_severity({"required": True, "state": "not_selected"}) == "blocker"
    assert row_severity({"required": False, "state": "misconfigured"}) == "warning"
    assert row_severity({"required": True, "state": "misconfigured"}) == "blocker"
    assert row_severity({"required": False, "state": "not_selected"}) is None
    assert row_severity({"required": True, "state": "available_disabled"}) is None
    assert row_severity({}) is None


# ---------------------------------------------------------------------------
# private helpers: empty URLs, unreachable backends, unknown engines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_reachable_helper_covers_empty_url_and_health_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await _redis_reachable("") is False

    created: list[dict] = []

    def coordinator_factory(healthy: bool):
        class _StubCoordinator:
            def __init__(self, url: str) -> None:
                self.url = url
                self.closed = False
                created.append({"healthy": healthy, "closed": self})

            async def health(self) -> bool:
                return healthy

            async def close(self) -> None:
                self.closed = True

        return _StubCoordinator

    monkeypatch.setattr(
        "deeptutor.runtime.coordination.redis.RedisCoordinator",
        coordinator_factory(healthy=True),
    )
    assert await _redis_reachable("redis://localhost:6379/0") is True
    assert created[-1]["closed"].closed is True

    monkeypatch.setattr(
        "deeptutor.runtime.coordination.redis.RedisCoordinator",
        coordinator_factory(healthy=False),
    )
    assert await _redis_reachable("redis://localhost:6379/0") is False
    assert created[-1]["closed"].closed is True

    class _ExplodingCoordinator:
        def __init__(self, url: str) -> None:
            raise RuntimeError("no redis")

    monkeypatch.setattr(
        "deeptutor.runtime.coordination.redis.RedisCoordinator", _ExplodingCoordinator
    )
    assert await _redis_reachable("redis://localhost:6379/0") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("engine_id", "config", "expected"),
    [
        ("custom-engine", SimpleNamespace(), None),
        ("docling", SimpleNamespace(is_remote=False), None),
        ("mineru", SimpleNamespace(is_cloud=False), None),
    ],
)
async def test_remote_parser_reachability_skips_non_probe_combinations(
    engine_id: str, config: SimpleNamespace, expected: bool | None
) -> None:
    assert await _selected_remote_parser_reachable(engine_id, object(), config) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [True, False])
async def test_tika_remote_probe_result_is_propagated(
    monkeypatch: pytest.MonkeyPatch, outcome: bool
) -> None:
    def verify_remote(config, timeout: float) -> tuple[bool, str]:
        return outcome, "probe done"

    monkeypatch.setattr(
        "deeptutor.services.parsing.engines.tika.remote.verify_remote", verify_remote
    )

    assert await _selected_remote_parser_reachable("tika", object(), SimpleNamespace()) is outcome


@pytest.mark.asyncio
async def test_tika_remote_probe_failure_reports_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def verify_remote(config, timeout: float) -> tuple[bool, str]:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "deeptutor.services.parsing.engines.tika.remote.verify_remote", verify_remote
    )

    assert await _selected_remote_parser_reachable("tika", object(), SimpleNamespace()) is False


@pytest.mark.asyncio
async def test_docling_remote_probe_runs_only_in_remote_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def verify_remote(config, timeout: float) -> tuple[bool, str]:
        calls.append("probe")
        return True, "ok"

    monkeypatch.setattr(
        "deeptutor.services.parsing.engines.docling.remote.verify_remote", verify_remote
    )

    remote_config = SimpleNamespace(is_remote=True)
    assert await _selected_remote_parser_reachable("docling", object(), remote_config) is True
    assert calls == ["probe"]


# ---------------------------------------------------------------------------
# module availability helper
# ---------------------------------------------------------------------------


def test_module_available_helper_flags_present_and_missing_modules() -> None:
    assert _module_available("deeptutor.services.config.readiness") is True
    assert _module_available("deeptutor.no_such_module_probe") is False
    assert _module_available("this_module_definitely_does_not_exist") is False


def test_severities_ordering_contract_is_stable() -> None:
    assert SEVERITIES == ("blocker", "warning", "suggestion")

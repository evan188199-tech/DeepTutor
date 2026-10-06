"""Focused unit tests for ``deeptutor.services.doctor`` check branches."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.doctor import (
    DoctorCheck,
    DoctorReport,
    _credentials_check,
    _has_authentication_header,
    _llm_checks,
    _rag_check,
    _redact_error,
    _safe_endpoint,
    _storage_check,
    run_diagnostics,
    run_runtime_diagnostics,
)


def _no_preflight(provider: str) -> dict[str, Any]:
    raise AssertionError(f"unexpected preflight call for {provider}")


def _llm_config(**overrides):
    values = {
        "model": "gpt-4o-mini",
        "provider_name": "openai",
        "provider_mode": "standard",
        "binding": "openai",
        "api_key": "sk-test-secret",
        "base_url": "https://api.openai.com/v1",
        "effective_url": "https://api.openai.com/v1",
        "api_version": None,
        "extra_headers": {},
        "reasoning_effort": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("raw", "expected_ok", "expected_detail"),
    [
        (None, False, "No provider endpoint is configured."),
        ("", False, "No provider endpoint is configured."),
        ("http:///path", False, "The configured provider endpoint is not a valid HTTP(S) URL."),
        ("http://localhost:11434/v1/", True, "http://localhost:11434"),
        ("http://[::1]:8080/x", True, "http://[::1]:8080"),
    ],
)
def test_safe_endpoint_accepts_only_usable_http_urls(raw, expected_ok, expected_detail) -> None:
    ok, detail = _safe_endpoint(raw)

    assert ok is expected_ok
    assert detail == expected_detail


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"X_API_KEY": "value"}, True),
        ({"Proxy Authorization": "value"}, True),
        ({"X-Custom-Auth-Token": "token"}, True),
        ({"X-Access-Token": "token"}, True),
        ({"X-Trace-Id": "trace"}, False),
        ({"authorization": ""}, False),
        ({"api-key": None}, False),
        ("not-a-mapping", False),
    ],
)
def test_has_authentication_header_recognizes_credential_shapes(headers, expected) -> None:
    assert _has_authentication_header(headers) is expected


def test_credentials_check_oauth_provider_needs_no_key() -> None:
    check = _credentials_check(_llm_config(provider_name="github_copilot", api_key=""))

    assert check.status == "pass"
    assert "provider-managed OAuth" in check.detail


def test_credentials_check_local_provider_needs_no_key() -> None:
    check = _credentials_check(
        _llm_config(provider_name="vllm", provider_mode="local", api_key="no-key")
    )

    assert check.status == "pass"
    assert "does not require an API key" in check.detail


def test_credentials_check_custom_auth_header_satisfies_placeholder_key() -> None:
    check = _credentials_check(
        _llm_config(api_key="no-key", extra_headers={"X-Custom-Auth": "secret"})
    )

    assert check.status == "pass"
    assert "Credentials are configured" in check.detail


def test_credentials_check_azure_direct_without_key_fails() -> None:
    check = _credentials_check(
        _llm_config(provider_name="azure_openai", provider_mode="standard", api_key="")
    )

    assert check.status == "fail"
    assert check.required is True
    assert "No credentials are configured" in check.detail


def test_llm_checks_oauth_endpoint_is_provider_managed() -> None:
    checks = _llm_checks(_llm_config(provider_name="github_copilot"))

    by_key = {check.key: check for check in checks}
    assert by_key["llm_endpoint"].status == "pass"
    assert "manages its endpoint" in by_key["llm_endpoint"].detail


def test_llm_checks_report_missing_model_and_invalid_endpoint() -> None:
    checks = _llm_checks(
        _llm_config(model="", base_url="http:///path", effective_url="http:///path")
    )

    by_key = {check.key: check for check in checks}
    assert by_key["llm_config"].status == "fail"
    assert by_key["llm_endpoint"].status == "fail"


def test_redact_error_falls_back_to_exception_type_name() -> None:
    assert _redact_error(ValueError(""), None) == "ValueError"


def test_redact_error_hides_configured_api_key_and_headers() -> None:
    config = _llm_config(
        api_key="sk-configured-secret",
        extra_headers={"X-Custom-Auth": "header-secret-value"},
    )

    redacted = _redact_error(
        Exception("call failed sk-configured-secret header-secret-value"), config
    )

    assert "[redacted]" in redacted
    assert "sk-configured-secret" not in redacted
    assert "header-secret-value" not in redacted


def test_redact_error_masks_key_value_patterns_without_config() -> None:
    redacted = _redact_error(Exception("boom api_key=hunter2 token=abc123"), None)

    assert "api_key=[redacted]" in redacted
    assert "token=[redacted]" in redacted
    assert "hunter2" not in redacted


def test_redact_error_masks_bare_sk_tokens() -> None:
    redacted = _redact_error(Exception("connect failed for sk-abcd1234xyz"), None)

    assert "sk-abcd1234xyz" not in redacted
    assert "[redacted]" in redacted


def test_redact_error_preserves_placeholder_placeholders() -> None:
    redacted = _redact_error(Exception("endpoint rejected no-key"), None)

    assert "no-key" in redacted


def test_storage_check_passes_on_writable_directory(tmp_path) -> None:
    check = _storage_check(tmp_path)

    assert check.status == "pass"
    assert check.detail == f"Writable: {tmp_path}"


def test_storage_check_fails_when_root_cannot_be_created(tmp_path) -> None:
    blocked = tmp_path / "occupied"
    blocked.write_text("file", encoding="utf-8")

    check = _storage_check(blocked / "nested")

    assert check.status == "fail"
    assert check.detail.startswith("Cannot write to ")
    assert check.required is True


@pytest.mark.parametrize(
    "rag_config",
    [
        {},
        {"knowledge_bases": None},
        {"knowledge_bases": "junk"},
        {"knowledge_bases": {}},
    ],
)
def test_rag_check_skips_without_usable_knowledge_bases(rag_config) -> None:
    check = _rag_check(rag_config, _no_preflight)

    assert check.status == "skip"
    assert check.required is False


def test_rag_check_ignores_non_dict_entries() -> None:
    check = _rag_check({"knowledge_bases": {"broken": "junk"}}, _no_preflight)

    assert check.status == "pass"


def test_rag_check_reports_weknora_missing_configuration() -> None:
    check = _rag_check(
        {
            "knowledge_bases": {
                "docs": {"rag_provider": "weknora"},
            }
        },
        _no_preflight,
    )

    assert check.status == "fail"
    assert check.required is False
    assert "docs" in check.detail
    assert "not connected to WeKnora" in check.detail


def test_rag_check_reports_weknora_invalid_server_url() -> None:
    check = _rag_check(
        {
            "knowledge_bases": {
                "docs": {
                    "rag_provider": "weknora",
                    "server_url": "https://host:99999",
                    "api_key": "weknora-secret",
                    "knowledge_base_id": "kb-1",
                }
            }
        },
        _no_preflight,
    )

    assert check.status == "fail"
    assert "invalid WeKnora server URL" in check.detail
    assert "weknora-secret" not in check.detail


def test_rag_check_reports_lightrag_invalid_server_url() -> None:
    check = _rag_check(
        {
            "knowledge_bases": {
                "remote": {
                    "rag_provider": "lightrag-server",
                    "server_url": "https://host:99999",
                }
            }
        },
        _no_preflight,
    )

    assert check.status == "fail"
    assert check.required is False
    assert "remote: invalid LightRAG server URL" in check.detail


def test_rag_check_reports_preflight_crash_as_advisory_failure() -> None:
    def crashing_preflight(provider: str) -> dict[str, Any]:
        raise RuntimeError("preflight exploded")

    check = _rag_check(
        {
            "knowledge_bases": {
                "notes": {"rag_provider": "llamaindex"},
            }
        },
        crashing_preflight,
    )

    assert check.status == "fail"
    assert check.required is False
    assert "preflight could not run" in check.detail


def test_rag_check_treats_optional_preflight_failures_as_ready() -> None:
    def preflight(provider: str) -> dict[str, Any]:
        return {
            "ok": True,
            "checks": [{"label": "Embedding hint", "ok": False, "optional": True}],
        }

    check = _rag_check(
        {
            "defaults": {"rag_provider": "llamaindex"},
            "knowledge_bases": {"notes": {}},
        },
        preflight,
    )

    assert check.status == "pass"
    assert "llamaindex" in check.detail


def test_report_ok_ignores_optional_failures_and_skips() -> None:
    report = DoctorReport(
        online=False,
        checks=[
            DoctorCheck(key="llm_config", label="LLM configuration", status="pass", detail="ok"),
            DoctorCheck(
                key="rag",
                label="RAG prerequisites",
                status="fail",
                detail="advisory",
                required=False,
            ),
            DoctorCheck(
                key="online",
                label="Provider response",
                status="skip",
                detail="not requested",
                required=False,
            ),
        ],
    )

    assert report.ok is True
    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["online"] is False
    assert [check["key"] for check in payload["checks"]] == [
        "llm_config",
        "rag",
        "online",
    ]
    assert payload["checks"][1]["required"] is False


def test_report_ok_fails_on_required_failure_only() -> None:
    report = DoctorReport(
        online=False,
        checks=[
            DoctorCheck(key="llm_config", label="LLM configuration", status="fail", detail="bad"),
        ],
    )

    assert report.ok is False
    assert DoctorReport(online=False, checks=[]).ok is True


@pytest.mark.asyncio
async def test_run_diagnostics_reports_resolver_failure_without_blocking_other_checks(
    tmp_path,
) -> None:
    probe_calls = []

    async def probe(config) -> None:
        probe_calls.append(config)

    def broken_resolver():
        raise RuntimeError("resolver crashed for sk-leaky-token")

    report = await run_diagnostics(
        online=True,
        resolve_llm=broken_resolver,
        data_root=tmp_path,
        load_rag_config=lambda: {"defaults": {}, "knowledge_bases": {}},
        online_probe=probe,
    )

    by_key = {check.key: check for check in report.checks}
    assert by_key["llm_config"].status == "fail"
    assert "sk-leaky-token" not in by_key["llm_config"].detail
    assert by_key["storage"].status == "pass"
    assert by_key["rag"].status == "skip"
    assert probe_calls == []
    assert by_key["online"].status == "skip"
    assert "Skipped because local LLM checks failed." in by_key["online"].detail
    assert report.ok is False


@pytest.mark.asyncio
async def test_run_diagnostics_treats_rag_config_crash_as_advisory(tmp_path) -> None:
    def broken_rag_config() -> dict[str, Any]:
        raise RuntimeError("kb config unreadable")

    report = await run_diagnostics(
        resolve_llm=lambda: _llm_config(),
        data_root=tmp_path,
        load_rag_config=broken_rag_config,
        rag_preflight=_no_preflight,
    )

    rag = next(check for check in report.checks if check.key == "rag")
    assert rag.status == "fail"
    assert rag.required is False
    assert "Could not inspect RAG settings" in rag.detail
    assert report.ok is True


class _FakeCoordinator:
    def __init__(self, healthy: bool) -> None:
        self._healthy = healthy
        self.closed = False

    async def health(self) -> bool:
        return self._healthy

    async def close(self) -> None:
        self.closed = True


class _FakeCoordinationSettings:
    backend = "memory"
    backend_workers = 2

    @classmethod
    def from_runtime_settings(cls, system: Any, integrations: Any) -> "_FakeCoordinationSettings":
        return cls()


@pytest.mark.asyncio
async def test_run_runtime_diagnostics_reports_ready_stack(
    monkeypatch,
) -> None:
    created = []

    async def fake_create(settings):
        coordinator = _FakeCoordinator(healthy=True)
        created.append((settings, coordinator))
        return coordinator

    class _FakeStore:
        async def list_nonterminal_turns(self):
            return []

    async def fake_migrate(dry_run: bool = False):
        assert dry_run is True
        return [{"imported": 2}, {"imported": None}, {"imported": 3}]

    monkeypatch.setattr(
        "deeptutor.runtime.coordination.CoordinationSettings", _FakeCoordinationSettings
    )
    monkeypatch.setattr("deeptutor.runtime.coordination.create_runtime_coordinator", fake_create)
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(
        "deeptutor.services.session.legacy_migration.migrate_all_legacy_chat_scopes",
        fake_migrate,
    )

    report = await run_runtime_diagnostics()

    by_key = {check.key: check for check in report.checks}
    assert report.ok is True
    assert created and created[0][1].closed is True
    assert by_key["turn_coordination"].status == "pass"
    assert "memory coordination is ready for 2 worker(s)." in by_key["turn_coordination"].detail
    assert by_key["turn_repository"].status == "pass"
    assert by_key["legacy_chat_migration"].status == "pass"
    assert "5 session(s) pending migration." in by_key["legacy_chat_migration"].detail


@pytest.mark.asyncio
async def test_run_runtime_diagnostics_reports_unhealthy_backend(monkeypatch) -> None:
    async def fake_create(settings):
        return _FakeCoordinator(healthy=False)

    class _FakeStore:
        async def list_nonterminal_turns(self):
            return []

    async def fake_migrate(dry_run: bool = False):
        return []

    monkeypatch.setattr(
        "deeptutor.runtime.coordination.CoordinationSettings", _FakeCoordinationSettings
    )
    monkeypatch.setattr("deeptutor.runtime.coordination.create_runtime_coordinator", fake_create)
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(
        "deeptutor.services.session.legacy_migration.migrate_all_legacy_chat_scopes",
        fake_migrate,
    )

    report = await run_runtime_diagnostics()

    coordination = next(check for check in report.checks if check.key == "turn_coordination")
    assert coordination.status == "fail"
    assert report.ok is False


@pytest.mark.asyncio
async def test_run_runtime_diagnostics_reports_coordination_setup_failure(
    monkeypatch,
) -> None:
    class _FakeStore:
        async def list_nonterminal_turns(self):
            return []

    async def fake_migrate(dry_run: bool = False):
        return []

    async def broken_create(settings):
        raise RuntimeError("coordination backend refused to start")

    monkeypatch.setattr(
        "deeptutor.runtime.coordination.CoordinationSettings", _FakeCoordinationSettings
    )
    monkeypatch.setattr("deeptutor.runtime.coordination.create_runtime_coordinator", broken_create)
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(
        "deeptutor.services.session.legacy_migration.migrate_all_legacy_chat_scopes",
        fake_migrate,
    )

    report = await run_runtime_diagnostics()

    coordination = next(check for check in report.checks if check.key == "turn_coordination")
    assert coordination.status == "fail"
    assert "coordination backend refused to start" in coordination.detail


@pytest.mark.asyncio
async def test_run_runtime_diagnostics_reports_migration_failure(monkeypatch) -> None:
    class _FakeStore:
        async def list_nonterminal_turns(self):
            return []

    async def fake_create(settings):
        return _FakeCoordinator(healthy=True)

    async def broken_migrate(dry_run: bool = False):
        raise RuntimeError("legacy migration scan failed")

    monkeypatch.setattr(
        "deeptutor.runtime.coordination.CoordinationSettings", _FakeCoordinationSettings
    )
    monkeypatch.setattr("deeptutor.runtime.coordination.create_runtime_coordinator", fake_create)
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _FakeStore())
    monkeypatch.setattr(
        "deeptutor.services.session.legacy_migration.migrate_all_legacy_chat_scopes",
        broken_migrate,
    )

    report = await run_runtime_diagnostics()

    migration = next(check for check in report.checks if check.key == "legacy_chat_migration")
    assert migration.status == "fail"
    assert "legacy migration scan failed" in migration.detail
    assert report.ok is False


@pytest.mark.asyncio
async def test_run_runtime_diagnostics_reports_store_failure(monkeypatch) -> None:
    async def fake_create(settings):
        return _FakeCoordinator(healthy=True)

    def broken_store():
        raise RuntimeError("session store unavailable")

    async def fake_migrate(dry_run: bool = False):
        return []

    monkeypatch.setattr(
        "deeptutor.runtime.coordination.CoordinationSettings", _FakeCoordinationSettings
    )
    monkeypatch.setattr("deeptutor.runtime.coordination.create_runtime_coordinator", fake_create)
    monkeypatch.setattr("deeptutor.services.session.get_session_store", broken_store)
    monkeypatch.setattr(
        "deeptutor.services.session.legacy_migration.migrate_all_legacy_chat_scopes",
        fake_migrate,
    )

    report = await run_runtime_diagnostics()

    repository = next(check for check in report.checks if check.key == "turn_repository")
    assert repository.status == "fail"
    assert "session store unavailable" in repository.detail
    assert report.ok is False

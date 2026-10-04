"""Cold-start verification of the #1421 fix lineage (PR #1436).

Replays the reporter's sequence from
https://github.com/HKUDS/DeepTutor/issues/1421 against the REAL file-backed
``ModelCatalogService`` on a fresh data directory — no fake catalog service:

1. first boot writes the default catalog (``load()`` on a missing file);
2. the user's LLM is configured once (a real change; one reset by design);
3. cold restart: the first message resolves the shared clients, and settings
   traffic re-applies the SAME catalog while that turn is in flight — the
   redundant apply must not swap the clients out from under it (this is the
   loop that hung the first message before the fix);
4. a real configuration change still resets the clients at once.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.settings_draft import SettingsDraftService
from deeptutor.services.embedding import client as embedding_client_module
from deeptutor.services.embedding import config as embedding_config_module
from deeptutor.services.llm import client as llm_client_module
from deeptutor.services.llm import config as llm_config_module

_RESET_WARNING = "resetting global LLM"


class _FakeEmbeddingAdapter:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    async def embed(self, request):
        return type("EmbeddingResponse", (), {"embeddings": [[] for _ in request.texts]})()


def _user_catalog(llm_model: str) -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-profile-default",
                "active_model_id": "llm-model-default",
                "profiles": [
                    {
                        "id": "llm-profile-default",
                        "name": "Default LLM Endpoint",
                        "binding": "openai",
                        "base_url": "https://llm.example/v1",
                        "api_key": "llm-key",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {"id": "llm-model-default", "name": llm_model, "model": llm_model}
                        ],
                    }
                ],
            },
            "embedding": {
                "active_profile_id": "embedding-profile-default",
                "active_model_id": "embedding-model-default",
                "profiles": [
                    {
                        "id": "embedding-profile-default",
                        "name": "Default Embedding Endpoint",
                        "binding": "openai",
                        "base_url": "https://embedding.example/v1/embeddings",
                        "api_key": "embedding-key",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-default",
                                "name": "text-embedding-user",
                                "model": "text-embedding-user",
                                "dimension": "1536",
                            }
                        ],
                    }
                ],
            },
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


pytestmark = pytest.mark.real_llm_resolver


@pytest.fixture()
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Real catalog + draft services on tmp files; resolvers stay real.

    The resolver seam is the one the settings router's own tests use, but the
    lambdas delegate to the REAL ``resolve_*_runtime_config`` with the real
    loaded catalog, so profile selection and normalization are exercised for
    real. Everything below the seam — the file writes, the apply endpoints,
    ``_runtime_catalog_write``, and the client singletons — is production
    code.
    """
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    draft_service = SettingsDraftService(tmp_path / "settings_draft.json")
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(settings_router, "get_settings_draft_service", lambda: draft_service)
    monkeypatch.setattr(
        embedding_client_module,
        "_resolve_adapter_class",
        lambda _binding: _FakeEmbeddingAdapter,
    )

    real_llm_resolver = llm_config_module.resolve_llm_runtime_config
    real_embedding_resolver = embedding_config_module.resolve_embedding_runtime_config
    monkeypatch.setattr(
        llm_config_module,
        "resolve_llm_runtime_config",
        lambda *a, **k: real_llm_resolver(*a, **{**k, "catalog": service.load()}),
    )
    monkeypatch.setattr(
        embedding_config_module,
        "resolve_embedding_runtime_config",
        lambda *a, **k: real_embedding_resolver(*a, **{**k, "catalog": service.load()}),
    )

    # Enter the scenario with clean singletons (a cold process).
    llm_client_module.reset_llm_client()
    embedding_client_module.reset_embedding_client()
    llm_config_module.clear_llm_config_cache()
    yield service
    llm_client_module.reset_llm_client()
    embedding_client_module.reset_embedding_client()
    llm_config_module.clear_llm_config_cache()


@pytest.mark.asyncio
async def test_first_boot_writes_the_default_catalog(runtime: ModelCatalogService) -> None:
    assert not runtime.path.exists()
    first = runtime.load()
    assert runtime.path.exists()
    assert first["services"]["llm"]["profiles"] == []
    assert runtime.load() == first


@pytest.mark.asyncio
async def test_cold_start_first_message_survives_a_redundant_apply(
    runtime: ModelCatalogService, caplog: pytest.LogCaptureFixture
) -> None:
    """The #1421 shape: model configured, restart, first message, re-apply."""
    runtime.load()
    runtime.apply(_user_catalog("gpt-user"))
    runtime.load()  # settle normalization onto the file

    # Cold restart: the first message resolves the shared clients.
    in_flight_llm = llm_client_module.get_llm_client()
    in_flight_embedding = embedding_client_module.get_embedding_client()
    assert in_flight_llm.config.model == "gpt-user"

    with caplog.at_level(logging.WARNING, logger="deeptutor.api.routers.settings"):
        # Settings traffic while the turn is in flight: apply with no body
        # promotes the stored (empty) draft — proposed == current.
        response = await settings_router.apply_catalog(None)
        assert response["catalog"]
        # And the UI round-trip: re-apply the redacted catalog shown on
        # screen (masked secrets must restore to an identical catalog).
        redacted = settings_router.redact_catalog_secrets(runtime.load())
        await settings_router.apply_catalog(settings_router.CatalogPayload(catalog=redacted))

    assert llm_client_module.get_llm_client() is in_flight_llm
    assert embedding_client_module.get_embedding_client() is in_flight_embedding
    assert not [r for r in caplog.records if _RESET_WARNING in r.message]


@pytest.mark.asyncio
async def test_a_real_settings_change_still_resets_the_clients(
    runtime: ModelCatalogService, caplog: pytest.LogCaptureFixture
) -> None:
    runtime.load()
    runtime.apply(_user_catalog("gpt-first"))
    runtime.load()

    llm_config_module.get_llm_config()
    old_llm = llm_client_module.get_llm_client()
    old_embedding = embedding_client_module.get_embedding_client()

    changed = deepcopy(runtime.load())
    llm_profile = changed["services"]["llm"]["profiles"][0]
    llm_profile["models"][0]["model"] = "gpt-second"
    llm_profile["models"][0]["name"] = "gpt-second"

    with caplog.at_level(logging.WARNING, logger="deeptutor.api.routers.settings"):
        response = await settings_router.apply_catalog(
            settings_router.CatalogPayload(catalog=changed)
        )

    assert response["catalog"]
    assert llm_client_module.get_llm_client() is not old_llm
    assert embedding_client_module.get_embedding_client() is not old_embedding
    assert any(_RESET_WARNING in r.message for r in caplog.records)
    assert llm_client_module.get_llm_client().config.model == "gpt-second"

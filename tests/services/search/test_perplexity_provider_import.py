"""Import-name and declaration alignment for the Perplexity search provider.

The provider lazy-imports ``Perplexity`` from the ``perplexity`` module. That
module is installed by the official Perplexity SDK, distributed on PyPI as
``perplexityai`` — not by the unrelated ``perplexity`` distribution, whose
client has a different API. These tests keep the import name, the declared
dependency floors and the fallback error message telling the same story.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace

import pytest

from deeptutor.services.search.providers.perplexity import PerplexityProvider

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

# First `perplexityai` release shipping the `chat.completions` API the provider
# calls; 0.3.0–0.6.0 only expose the `search` resource.
MINIMUM_PERPLEXITYAI = "0.7.0"


def _load_project(path: Path) -> dict:
    with path.open("rb") as file:
        return tomllib.load(file)["project"]


def _cli_requirement_lines() -> list[str]:
    return [
        line.split("#", 1)[0].strip()
        for line in (REPOSITORY_ROOT / "requirements" / "cli.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.split("#", 1)[0].strip()
    ]


def test_perplexityai_floor_matches_every_install_surface() -> None:
    """Every declaration surface must ship a completions-capable SDK.

    The distribution is `perplexityai` but the module it installs is
    `perplexity`, which is what the provider imports. Floors below 0.7.0
    install a SDK without the `chat.completions` API the provider calls.
    """
    expected = f"perplexityai>={MINIMUM_PERPLEXITYAI}"
    root = _load_project(REPOSITORY_ROOT / "pyproject.toml")
    cli_package = _load_project(REPOSITORY_ROOT / "packaging" / "deeptutor-cli" / "pyproject.toml")

    for dependencies in (
        root["dependencies"],
        root["optional-dependencies"]["cli"],
        cli_package["dependencies"],
    ):
        assert [item for item in dependencies if item.startswith("perplexityai")] == [expected]

    assert [item for item in _cli_requirement_lines() if item.startswith("perplexityai")] == [
        expected
    ]


def test_missing_sdk_error_names_the_module_and_the_package_to_install(monkeypatch) -> None:
    provider = PerplexityProvider(api_key="k")
    monkeypatch.setitem(sys.modules, "perplexity", None)

    with pytest.raises(ImportError) as excinfo:
        provider.client

    message = str(excinfo.value)
    # The missing module is `perplexity`; the package to install is `perplexityai`.
    assert "'perplexity'" in message
    assert "pip install perplexityai" in message
    assert "perplexityai module is not installed" not in message


def test_client_is_built_from_the_perplexity_module(monkeypatch) -> None:
    constructed: dict[str, str | None] = {}

    class _FakeSDK:
        def __init__(self, *, api_key: str | None = None) -> None:
            constructed["api_key"] = api_key

    monkeypatch.setitem(sys.modules, "perplexity", SimpleNamespace(Perplexity=_FakeSDK))

    provider = PerplexityProvider(api_key="test-key")
    client = provider.client

    assert isinstance(client, _FakeSDK)
    assert constructed["api_key"] == "test-key"
    assert provider.client is client


def test_installed_sdk_smoke_matches_the_imported_module() -> None:
    """Minimal-install smoke: the declared package provides the imported API.

    Runs wherever the SDK is installed (CI installs it via
    requirements/cli.txt); constructs a client and checks the callable the
    provider dials, without touching the network.
    """
    perplexity = pytest.importorskip("perplexity", reason="perplexityai SDK not installed")
    try:
        version("perplexityai")
    except PackageNotFoundError:
        pytest.skip("a 'perplexity' module exists but the perplexityai SDK is not installed")

    client = perplexity.Perplexity(api_key="test-key")
    try:
        assert callable(client.chat.completions.create)
    finally:
        client.close()

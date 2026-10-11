"""
Web Search Base Provider - Abstract base class for all search providers

This module defines the BaseSearchProvider class that all search providers must inherit from.
Providers read credentials from data/user/settings/model_catalog.json.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, Final

from deeptutor.services.config import search_provider_credentials

from .types import WebSearchResponse

# Legacy name retained for provider metadata only.
SEARCH_API_KEY_ENV = "SEARCH_API_KEY"

# Shared per-request transport timeout tiers, in seconds. Every provider's
# ``timeout`` default must be one of these named tiers instead of a literal,
# so the whole family's timeout surface stays reviewable here.
#
# Coverage:
# - FAST (20s) — lightweight metasearch/SERP relays that only return result
#   lists: searxng, brave, duckduckgo.
# - STANDARD (30s) — ordinary SERP-family APIs: serper, serply, qianfan,
#   zhipu, bocha, aliyun_iqs. Default tier for new providers.
# - SLOW (60s) — engines that read or fetch the pages before answering:
#   doubao, firecrawl, jina, tavily.
#
# The tiers bound a single request. The failover chain in ``__init__`` walks
# the configured candidates serially, so its worst-case wall time is the sum
# of the surviving candidates' tier values; keep new providers on the lowest
# tier their latency profile allows. Callers may still override ``timeout``
# per call.
SEARCH_TIMEOUT_FAST_S: Final[int] = 20
SEARCH_TIMEOUT_STANDARD_S: Final[int] = 30
SEARCH_TIMEOUT_SLOW_S: Final[int] = 60


class BaseSearchProvider(ABC):
    """Abstract base class for search providers.

    Providers use the active Search profile from Settings > Catalog.
    Each provider has its own BASE_URL defined as a class constant.
    """

    name: str = "base"
    display_name: str = "Base Provider"
    description: str = ""
    requires_api_key: bool = True
    supports_answer: bool = False  # Whether provider generates LLM answers
    BASE_URL: str = ""  # Each provider defines its own endpoint
    API_KEY_ENV_VARS: tuple[str, ...] = (SEARCH_API_KEY_ENV,)

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        """
        Initialize the provider.

        Args:
            api_key: API key for the provider. If not provided, use the active Search profile.
            **kwargs: Additional configuration options.
        """
        self.logger = logging.getLogger(__name__)
        self.api_key = api_key or self._get_api_key()
        self.config = kwargs
        self.proxy = kwargs.get("proxy")

    def _get_api_key(self) -> str:
        """Get the API key from this provider's own search profile.

        Looked up by provider rather than off the active profile, so a provider
        that is configured but not currently active still finds its own key
        instead of borrowing another vendor's.
        """
        key, _ = search_provider_credentials(self.name)
        if self.requires_api_key and not key:
            raise ValueError(f"{self.name} requires an api_key in Settings > Catalog > Search.")
        return key

    @abstractmethod
    def search(self, query: str, **kwargs: Any) -> WebSearchResponse:
        """
        Execute search and return standardized response.

        Args:
            query: The search query.
            **kwargs: Provider-specific options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        pass

    def is_available(self) -> bool:
        """
        Check if provider is available (dependencies installed, API key set).

        Returns:
            bool: True if provider is available, False otherwise.
        """
        try:
            if self.requires_api_key and not self.api_key:
                return False
            return True
        except (ValueError, ImportError):
            return False


__all__ = [
    "BaseSearchProvider",
    "SEARCH_API_KEY_ENV",
    "SEARCH_TIMEOUT_FAST_S",
    "SEARCH_TIMEOUT_STANDARD_S",
    "SEARCH_TIMEOUT_SLOW_S",
]

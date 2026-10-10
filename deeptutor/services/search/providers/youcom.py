"""You.com search provider (keyless free tier, optional API key).

API: https://you.com/docs/guides/search

Two endpoints, one provider:

- Without a key: ``GET https://api.you.com/v1/agents/search`` — no key, no
  account, 100 searches a day. The second zero-config engine after
  DuckDuckGo, with a JSON API instead of scraping.
- With ``YDC_API_KEY``: ``POST https://ydc-index.io/v1/search`` (``X-API-Key``
  header) — the keyed Search API with the same result shape and higher
  limits, so adding a key upgrades the same provider instead of switching.

Both return plain rows in ``results.web[]`` (``url``, ``title``,
``description``, ``snippets``) with no model-written answer, so
consolidation still supplies the answer. Past the free quota the endpoint
returns 429; the provider raises on it like any other HTTP error and the
runtime fallback sends the query to DuckDuckGo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("you")
class YouDotComProvider(BaseSearchProvider):
    """You.com web search: keyless free tier, keyed Search API."""

    description = "You.com web results (free without a key; optional YDC_API_KEY)"
    KEYLESS_URL = "https://api.you.com/v1/agents/search"
    KEYED_URL = "https://ydc-index.io/v1/search"
    API_KEY_ENV_VARS = ("YDC_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout: int = 20,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search You.com.

        Args:
            query: Search query.
            max_results: Result cap, sent as the API's ``count`` and applied
                client-side as well.
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url``, which
                replaces whichever endpoint is selected (keyless or keyed)
                for a self-hosted gateway.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        count = max(1, min(int(max_results), 100))
        keyed = bool(self.api_key)
        url = str(kwargs.get("base_url") or (self.KEYED_URL if keyed else self.KEYLESS_URL))
        headers = {
            "Accept": "application/json",
            "User-Agent": "deeptutor youdotcom-integration/hkuds-deeptutor",
        }
        request_kwargs: dict[str, Any] = {"headers": headers}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        if keyed:
            headers["X-API-Key"] = self.api_key
            resp = requests.post(
                url, json={"query": query, "count": count}, timeout=timeout, **request_kwargs
            )
        else:
            params: dict[str, Any] = {"query": query, "count": count}
            resp = requests.get(url, params=params, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"You.com API error: {resp.status_code} - {resp.text}")
        payload = resp.json()
        results = payload.get("results")
        rows = (results.get("web") if isinstance(results, dict) else None) or []
        rows = [row for row in rows if isinstance(row, dict)][:count]

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            result = _parse_row(row)
            search_results.append(result)
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=result.url,
                    title=result.title,
                    snippet=result.snippet,
                    date=result.date,
                    source=result.source,
                )
            )

        metadata: dict[str, Any] = {"finish_reason": "stop"}
        api_metadata = payload.get("metadata")
        if isinstance(api_metadata, dict) and api_metadata.get("search_uuid"):
            metadata["searchId"] = api_metadata["search_uuid"]

        return WebSearchResponse(
            query=query,
            answer="",
            provider="you",
            timestamp=datetime.now().isoformat(),
            model="youcom",
            citations=citations,
            search_results=search_results,
            metadata=metadata,
        )


def _parse_row(row: dict[str, Any]) -> SearchResult:
    """Map one ``results.web[]`` row onto ``SearchResult``."""
    title = str(row.get("title", "") or "")
    url = str(row.get("url", "") or "")
    description = str(row.get("description", "") or "")
    snippets = [str(s) for s in row.get("snippets") or [] if str(s).strip()]
    return SearchResult(
        title=title,
        url=url,
        snippet=description or " ".join(snippets),
        date=str(row.get("page_age", "") or ""),
        source=urlparse(url).hostname or "You.com",
    )

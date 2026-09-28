"""Scope semantics of :func:`crawl_docs_site`'s ``base_path_prefix``.

Contract under review (AGEN-24):

- A page seed scopes its parent directory, so sibling pages are internal:
  ``/intro/home`` seeds ``/intro/*``.
- A root seed still scopes the whole host.
- Anything outside the seed's directory — other directories or other
  hosts — is rejected.
- A trailing-slash (directory index) seed stays scoped to its own
  directory; it must NOT widen to the whole host.
"""

from __future__ import annotations

import pytest

from deeptutor.services.web_source import crawler


async def _capture_prefix(monkeypatch, base_url: str) -> str:
    """Run ``crawl_docs_site`` and return the ``base_path_prefix`` it used."""

    async def fake_sitemap(*args, **kwargs):
        return [base_url]

    captured: dict[str, str] = {}

    async def fake_process(url, depth, client, sem, **kwargs):
        captured["prefix"] = kwargs["base_path_prefix"]
        captured["host"] = kwargs["base_host"]
        return {"requested_url": url, "error": "stop", "status_code": 0}

    monkeypatch.setattr(crawler, "_sitemap_urls", fake_sitemap)
    monkeypatch.setattr(crawler, "_process_page", fake_process)
    monkeypatch.setattr(crawler, "_is_disallowed_host", lambda host: False)

    await crawler.crawl_docs_site(base_url)
    return captured["prefix"]


@pytest.mark.asyncio
async def test_page_seed_scopes_sibling_directory(monkeypatch) -> None:
    prefix = await _capture_prefix(monkeypatch, "https://example.com/intro/home")

    assert prefix == "/intro"
    assert crawler._is_internal("https://example.com/intro/next", "example.com", prefix)
    assert crawler._is_internal("https://example.com/intro", "example.com", prefix)
    # Sibling look-alikes must not slip through.
    assert not crawler._is_internal("https://example.com/intro2/x", "example.com", prefix)


@pytest.mark.asyncio
async def test_root_seed_scopes_whole_host(monkeypatch) -> None:
    prefix = await _capture_prefix(monkeypatch, "https://example.com/")

    assert prefix == "/"
    assert crawler._is_internal("https://example.com/any/path", "example.com", prefix)
    assert not crawler._is_internal("https://other.example/any/path", "example.com", prefix)


@pytest.mark.asyncio
async def test_section_seed_rejects_other_directories_and_hosts(monkeypatch) -> None:
    prefix = await _capture_prefix(monkeypatch, "https://example.com/intro/home")

    assert not crawler._is_internal("https://example.com/docs/x", "example.com", prefix)
    assert not crawler._is_internal("https://other.example/intro/x", "example.com", prefix)


@pytest.mark.asyncio
async def test_directory_seed_keeps_its_own_scope(monkeypatch) -> None:
    """A trailing-slash seed is a directory index, not a root override.

    ``Path('/intro/').parent`` is ``/`` — a naive pathlib rewrite would
    widen a section seed to the entire host.
    """

    prefix = await _capture_prefix(monkeypatch, "https://example.com/intro/")

    assert crawler._is_internal("https://example.com/intro/other", "example.com", prefix)
    assert not crawler._is_internal("https://example.com/docs/x", "example.com", prefix)


@pytest.mark.asyncio
async def test_crawl_follows_sibling_links_and_skips_out_of_scope(monkeypatch) -> None:
    """End-to-end: only the seed directory's pages get fetched."""

    page_html = (
        "<html><body><main>"
        "<a href='/intro/next'>next</a>"
        "<a href='/docs/outside'>outside</a>"
        "<a href='https://other.example/x'>external</a>"
        "</main></body></html>"
    )
    fetched: list[str] = []

    async def fake_fetch(url, *, client):
        fetched.append(url)
        return crawler.FetchOutcome(html=page_html, final_url=url, status_code=200)

    async def fake_sitemap(*args, **kwargs):
        return ["https://example.com/intro/home"]

    monkeypatch.setattr(crawler, "_fetch_page", fake_fetch)
    monkeypatch.setattr(crawler, "_sitemap_urls", fake_sitemap)
    monkeypatch.setattr(crawler, "_is_disallowed_host", lambda host: False)

    result = await crawler.crawl_docs_site("https://example.com/intro/home")

    assert result.ok
    assert sorted(fetched) == [
        "https://example.com/intro/home",
        "https://example.com/intro/next",
    ]
    assert [page.url for page in result.pages] == sorted(fetched)

"""Regression guards for the chat-history search chain (upstream #1678).

#1678 reports that history search cannot find text that clearly exists in
conversation messages. The linked fix (#1683) traces the visible failure to
the web history page, which filtered only titles and last messages locally
instead of calling the server search API — the server chain itself already
searches full visible transcripts. These tests lock that server-side chain —
retrieval entry (REST route and all-workspaces index), query construction,
literal matching with case/whitespace semantics, and empty results — so the
reported scenario can never silently regress.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.services.session.search import (
    MAX_SEARCH_QUERY_CHARS,
    bounded_search_excerpt,
    normalize_search_query,
)
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.navigation import session_index
from tests.services.workspace.test_data_scope import account as account


def run(coro):
    return asyncio.run(coro)


def _store(tmp_path) -> SQLiteSessionStore:
    return SQLiteSessionStore(tmp_path / "history.db")


# ---------------------------------------------------------------------------
# Query construction: the user-entered term is trimmed and bounded before it
# ever reaches the store. An over-long or unpadded query must not change what
# the history page can find.
# ---------------------------------------------------------------------------


def test_query_construction_trims_whitespace_and_bounds_length() -> None:
    assert normalize_search_query("  quantum tunneling  ") == "quantum tunneling"
    assert normalize_search_query("") == ""
    assert normalize_search_query(None) == ""
    assert len(normalize_search_query("x" * 500)) == MAX_SEARCH_QUERY_CHARS


# ---------------------------------------------------------------------------
# Matching: literal substring over the full visible transcript (user and
# assistant messages), not only the title and not only the newest message.
# This is the exact #1678 expectation — text that exists anywhere in the
# conversation must be found.
# ---------------------------------------------------------------------------


def test_exact_substring_in_earlier_user_message_is_found(tmp_path) -> None:
    store = _store(tmp_path)
    session = run(store.create_session(title="Lab notebook", session_id="native"))
    first_id = run(
        store.add_message(
            session["id"], "user", "We ran the ferromagnetic cup experiment twice."
        )
    )
    run(store.add_message(session["id"], "assistant", "All steps completed."))

    result = run(store.search_sessions("ferromagnetic cup", limit=10, offset=0))

    assert result["total"] == 1
    [match] = result["sessions"]
    assert match["session_id"] == "native"
    assert match["match_message_id"] == first_id
    assert match["match_role"] == "user"
    assert "ferromagnetic cup" in match["match_excerpt"].lower()


def test_exact_substring_in_assistant_reply_wins_as_latest_visible_match(tmp_path) -> None:
    store = _store(tmp_path)
    session = run(store.create_session(title="Physics chat", session_id="native"))
    run(store.add_message(session["id"], "user", "Explain entropy again"))
    earliest = run(store.add_message(session["id"], "assistant", "entropy is disorder"))
    latest = run(
        store.add_message(session["id"], "assistant", "A short ENTROPY recap follows")
    )
    run(store.add_message(session["id"], "system", "entropy provider metadata"))

    result = run(store.search_sessions("entropy", limit=10, offset=0))

    assert result["total"] == 1
    [match] = result["sessions"]
    assert match["match_message_id"] == latest
    assert match["match_message_id"] != earliest
    assert match["match_role"] == "assistant"


def test_case_differences_do_not_block_matches(tmp_path) -> None:
    store = _store(tmp_path)
    session = run(store.create_session(title="Photosynthesis Notes", session_id="native"))
    run(store.add_message(session["id"], "user", "the LIGHT reaction happens first"))

    upper_query = run(store.search_sessions("LIGHT reaction", limit=10, offset=0))
    lower_query = run(store.search_sessions("light REACTION", limit=10, offset=0))
    title_query = run(store.search_sessions("photosynthesis", limit=10, offset=0))

    assert upper_query["total"] == 1
    assert lower_query["total"] == 1
    assert title_query["total"] == 1
    assert upper_query["sessions"][0]["session_id"] == "native"
    assert title_query["sessions"][0]["match_message_id"] is None


def test_outer_whitespace_is_trimmed_and_matching_stays_literal(tmp_path) -> None:
    store = _store(tmp_path)
    session = run(store.create_session(title="Glossary", session_id="native"))
    run(store.add_message(session["id"], "user", "the quantum tunneling effect"))

    padded = run(store.search_sessions("  quantum tunneling  ", limit=10, offset=0))
    reversed_words = run(store.search_sessions("tunneling quantum", limit=10, offset=0))
    extra_inner_space = run(store.search_sessions("quantum  tunneling", limit=10, offset=0))

    assert padded["total"] == 1
    assert reversed_words["total"] == 0
    assert extra_inner_space["total"] == 0


# ---------------------------------------------------------------------------
# Empty results: blank queries match nothing at the store boundary instead of
# returning the whole index, and a real term with no hit yields an empty page.
# ---------------------------------------------------------------------------


def test_empty_or_blank_queries_return_empty_results(tmp_path) -> None:
    store = _store(tmp_path)
    session = run(store.create_session(title="Anything", session_id="native"))
    run(store.add_message(session["id"], "user", "some conversation body"))

    assert run(store.search_sessions("")) == {"sessions": [], "total": 0}
    assert run(store.search_sessions("   ")) == {"sessions": [], "total": 0}
    assert run(store.search_sessions("\t\n")) == {"sessions": [], "total": 0}


def test_term_without_any_hit_reports_an_empty_page(tmp_path) -> None:
    store = _store(tmp_path)
    session = run(store.create_session(title="Unrelated", session_id="native"))
    run(store.add_message(session["id"], "user", "plain conversation"))

    assert run(store.search_sessions("xyzzy-no-such-term")) == {"sessions": [], "total": 0}


# ---------------------------------------------------------------------------
# Result shaping: the excerpt windows around the hit case-insensitively so the
# history row can show why a session matched.
# ---------------------------------------------------------------------------


def test_match_excerpt_windows_around_the_hit_case_insensitively() -> None:
    filler = "intro " * 60
    content = f"{filler}The GRAVITY wave signal was clear.{filler}"

    excerpt = bounded_search_excerpt(content, "gravity wave")

    assert len(excerpt) <= 320
    assert "gravity wave" in excerpt.lower()
    assert excerpt.startswith("…")


# ---------------------------------------------------------------------------
# Retrieval entry: the REST route the history page is expected to call, and
# the all-workspaces index used when the page searches across workspaces.
# ---------------------------------------------------------------------------


def test_search_endpoint_serves_transcript_matches_and_rejects_blank_queries(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path)
    session = run(store.create_session(title="History", session_id="native"))
    run(store.add_message(session["id"], "user", "the glyph decoding worked"))
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)
    app = FastAPI()
    app.include_router(sessions_router.router, prefix="/api/sessions")

    with TestClient(app) as client:
        hit = client.get("/api/sessions/search", params={"q": "glyph decoding"})
        blank = client.get("/api/sessions/search", params={"q": "   "})
        miss = client.get("/api/sessions/search", params={"q": "no-such-term"})

    assert hit.status_code == 200
    assert hit.json()["total"] == 1
    assert hit.json()["sessions"][0]["match_role"] == "user"
    assert blank.status_code == 400
    assert miss.status_code == 200
    assert miss.json() == {"sessions": [], "total": 0, "limit": 50, "offset": 0}


@pytest.mark.asyncio
async def test_all_workspaces_entry_finds_message_text_in_other_workspaces(account) -> None:
    other = account.create_workspace("Archive")["workspace_id"]
    with workspace_context(""):
        default_store = await _account_store()
        default_session = await default_store.create_session(title="Default chat")
        await default_store.add_message(default_session["id"], "user", "tide pool survey")
    with workspace_context(other):
        archive_store = await _account_store()
        archive_session = await archive_store.create_session(title="Archive chat")
        await archive_store.add_message(
            archive_session["id"], "assistant", "the tide pool survey data is attached"
        )

    result = await session_index(10, 0, "tide pool survey")

    assert result["total"] == 2
    by_workspace = {row["content_workspace_id"]: row for row in result["sessions"]}
    assert set(by_workspace) == {"", other}
    assert by_workspace[other]["match_role"] == "assistant"
    assert "tide pool survey" in by_workspace[other]["match_excerpt"].lower()


async def _account_store():
    from deeptutor.services.session import get_sqlite_session_store

    return get_sqlite_session_store()

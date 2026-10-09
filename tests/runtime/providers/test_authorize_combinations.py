"""Remaining gate combinations for ``authorize_mcp_tools``.

``tests/runtime/providers/test_authorize.py`` pins the canonical caller
kinds (administrator, ungranted user, partner, exclusive capability). This
file walks the intersections the base matrix does not: both gates restricted
at once, each gate alone, the unrestricted result meeting ``owned_names``,
and the exclusive-capability short-circuit winning over every other input.
Only the returned :class:`Allowlist` is asserted.
"""

from __future__ import annotations

from collections.abc import Iterator

from deeptutor.runtime.providers.allowlist import Allowlist
from deeptutor.runtime.providers.authorize import authorize_mcp_tools
from deeptutor.runtime.providers.scope import ToolScope


def _owned_names(*names: str) -> Iterator[str]:
    """``owned_names`` is typed as a bare iterable; exercise that contract."""
    yield from names


def test_restricted_grant_and_caller_whitelist_keep_their_intersection() -> None:
    scope = ToolScope(
        owner_id="u1",
        caller_whitelist=frozenset({"mcp_gh_search", "mcp_other"}),
    )
    allowed = authorize_mcp_tools(
        scope=scope,
        user_grant=Allowlist.of(["mcp_gh_search", "mcp_docs_search"]),
    )
    assert allowed.names == frozenset({"mcp_gh_search"})


def test_restricted_grant_governs_when_caller_has_no_whitelist() -> None:
    allowed = authorize_mcp_tools(
        scope=ToolScope(owner_id="u1"),
        user_grant=Allowlist.of(["mcp_gh_search"]),
    )
    assert allowed.names == frozenset({"mcp_gh_search"})


def test_caller_whitelist_governs_when_grant_is_unrestricted() -> None:
    scope = ToolScope(owner_id="u1", caller_whitelist=frozenset({"mcp_docs_search"}))
    allowed = authorize_mcp_tools(scope=scope, user_grant=Allowlist.unrestricted())
    assert allowed.names == frozenset({"mcp_docs_search"})


def test_unrestricted_result_survives_owned_names() -> None:
    allowed = authorize_mcp_tools(
        scope=ToolScope(owner_id="admin"),
        user_grant=Allowlist.unrestricted(),
        owned_names=["mcp_mynotion_search"],
    )
    assert allowed.is_unrestricted
    assert allowed.allows("mcp_mynotion_search")


def test_owned_names_extend_a_restricted_gate_without_dropping_it() -> None:
    """The gate is the caller×grant intersection first; owned names add to it.

    A name granted but not whitelisted by the caller never enters the gate,
    and owned names never remove a gate name.
    """
    scope = ToolScope(owner_id="u1", caller_whitelist=frozenset({"mcp_gh_search"}))
    allowed = authorize_mcp_tools(
        scope=scope,
        user_grant=Allowlist.of(["mcp_gh_search", "mcp_docs_search"]),
        owned_names=_owned_names("mcp_mynotion_search", "mcp_mynotion_read"),
    )
    assert allowed.names == frozenset(
        {"mcp_gh_search", "mcp_mynotion_search", "mcp_mynotion_read"}
    )


def test_partner_gate_is_widened_by_owned_names() -> None:
    scope = ToolScope(
        owner_id="owner",
        is_partner=True,
        caller_whitelist=frozenset({"mcp_gh_search"}),
    )
    allowed = authorize_mcp_tools(
        scope=scope,
        user_grant=Allowlist.of([]),
        owned_names=["mcp_mynotion_search"],
    )
    assert allowed.names == frozenset({"mcp_gh_search", "mcp_mynotion_search"})


def test_exclusive_capability_wins_over_every_other_input() -> None:
    scope = ToolScope(
        owner_id="owner",
        is_partner=True,
        caller_whitelist=None,
        exclusive_capability=True,
    )
    allowed = authorize_mcp_tools(
        scope=scope,
        user_grant=Allowlist.unrestricted(),
        owned_names=["mcp_mynotion_search"],
    )
    assert allowed.names == frozenset()
    assert not allowed.allows("mcp_gh_search")

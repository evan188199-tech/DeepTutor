# PR: test(research): cover citation_manager payload fault tolerance

## Summary

- Adds 14 tests for `deeptutor/agents/research/utils/citation_manager.py`, locking three contracts the existing suite did not cover:
  1. **`_rag_source_payload` degrades on ragged payloads instead of crashing** — `None`/scalar/plain-text payloads yield no sources; dict payloads without known source fields yield no sources; a missing or non-string `kb_name` never leaks `None` into metadata; ragged fields (string/int/`None`/dict where a list is expected) are skipped; the first list-shaped field wins; list payloads pass through unchanged; scalar junk entries are dropped by `_rag_source_info`.
  2. **Reference numbering is contiguous and unique per distinct source across tool types** — citations added via `rag`, `web_search`, and `paper_search` get numbers 1..N with no gaps or duplicates; identical papers (same title + first author) share a number while distinct sources never collide; an empty manager and unknown ids degrade to `{}` / `0`.
  3. **Missing or broken inputs never raise out of `add_citation`** — a prose answer with no structured payload stores a usable zero-source citation; ragged metadata sources fall back to the answer payload; a tool trace missing expected attributes is reported (logged) and returns `False` instead of raising; unknown tool types store a generic entry.
- **No product code is changed** — a single new test file (`tests/agents/research/test_citation_manager_payloads.py`, 205 lines).

## Root cause

`deeptutor/agents/research/utils/citation_manager.py` builds every citation the research agents surface to users, but the existing suite left it at **21% statement coverage**, and its fault-tolerance contracts had no tests: upstream PR #812 (landed via #808) fixed one list-shape regression after the fact, yet nothing pinned the surrounding behavior — non-list scalar tolerance, `kb_name` normalization, cross-tool numbering contiguity, paper dedup, and trace-error degradation. This PR pins those contracts so future refactors cannot silently regress them.

## Changes

- `tests/agents/research/test_citation_manager_payloads.py` (new, +205 lines): 14 tests in three groups matching the contracts above. Tool traces are lightweight `SimpleNamespace` stand-ins, each test uses its own `CitationManager` on a throwaway `tmp_path` cache dir, and a `capsys` assertion verifies the broken-trace failure is reported rather than raised — no shared state, no runtime data touched.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `pytest tests/agents/research/test_citation_manager.py tests/agents/research/test_citation_manager_payloads.py -v` → **18 passed** (4 existing + 14 new)
- `pytest tests/agents/research/ -q` → **91 passed** (full research-agent suite, no regressions)
- `pytest tests/reading/ -q` → **402 passed** (adjacent reading suite, no regressions)
- Coverage of the target module (existing file vs. existing + new):
  `pytest tests/agents/research/test_citation_manager.py --cov=deeptutor.agents.research.utils.citation_manager -q` → **21%** (331 missing of 419 stmts);
  same command plus `test_citation_manager_payloads.py` → **52%** (**−130 missing statements**)
- `ruff check tests/agents/research/test_citation_manager_payloads.py && ruff format --check tests/agents/research/test_citation_manager_payloads.py` → All checks passed; 1 file already formatted
- `python scripts/check_architecture.py && python scripts/check_workspace_hygiene.py` → Architecture boundaries: OK / Repository hygiene check passed

## Related issue

None upstream — the gap was identified by an internal coverage audit (DT-21 Top-15 #4: `citation_manager.py`). Related to #812 / #808 (prior list-shape fix): this PR pins the surrounding fault-tolerance contracts rather than fixing a reported bug, so it uses `Related to`, not `Fixes`.

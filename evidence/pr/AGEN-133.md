# PR: fix(rag): classify invalid persisted index errors and include re-index steps

## Summary

- Searching a knowledge base whose persisted index contains invalid vectors (e.g. `null` dimensions left behind by an older version, as in #440) failed as `invalid_embedding_provider_response` with no re-index flag, pointing users at their embedding provider/model configuration instead of the damaged index.
- This PR classifies these failures as `invalid_embedding_index` with `needs_reindex: true`, and the user-facing answer now names the concrete fault, the recovery path (knowledge base page → `Re-index`, under `Index versions` — wording matches the web UI), and warns that re-uploading documents reuses the damaged index and cannot repair it.

## Root cause

`storage._validate_persisted_embeddings` validates persisted vectors with the shared `validate_embedding_batch`, whose messages are framed for live provider responses and start with `Embedding provider returned invalid vector …`. `search_error_result` matched that provider keyword before the persisted-index signature, so a corrupt persisted store was reported as a provider failure (wrong `error_type`, `needs_reindex` missing), even though the provider was healthy — exactly the #440 symptom.

## Changes

- `deeptutor/services/rag/pipelines/llamaindex/errors.py`: classify the persisted-index diagnosis (`RAG index contains invalid embedding vectors`, plus the pre-existing null-vector similarity / shape errors) before the provider-response branch; extract the loader's `Details:` reason into the answer; the answer now spells out the re-index steps and the re-upload caveat.
- `deeptutor/services/rag/pipelines/llamaindex/storage.py`: the persisted-embedding validation error now names the `Re-index` action (`Index versions → Re-index`) and the re-upload caveat; the underlying fault is restated neutrally as `stored vector in <file> failed validation: <fault>` instead of quoting the provider-facing `Embedding provider returned invalid vector …` text, since persisted data is not a live provider response.
- `tests/services/rag/test_llamaindex_embedding_failures.py`: 3 new tests — `test_search_answer_names_reason_and_reindex_action` (classification, `needs_reindex`, neutral reason naming the vector-store file, no provider blame), `test_invalid_index_error_names_reindex_action_and_reupload_caveat` (storage error wording), `test_search_answer_keeps_reindex_steps_without_low_level_details` (null-vector similarity path also gets the re-index steps without low-level noise).

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/services/rag/test_llamaindex_embedding_failures.py -q` → **11 passed** (8 pre-existing + 3 new)
- Red-green check: same file applied to the pre-fix `dev` state → the 3 new tests **fail** (3 failed, 8 passed), confirming they pin the fix.
- `python -m pytest tests/services/rag -q` → **637 passed, 31 skipped, 0 failed** (in a pristine worktree without the untracked `data/user/settings/main.yaml`, ~12 environment-dependent failures such as `test_embedding_binding` reproduce identically on the `dev` baseline and are unrelated to this change)
- `ruff check deeptutor/services/rag/pipelines/llamaindex/errors.py deeptutor/services/rag/pipelines/llamaindex/storage.py tests/services/rag/test_llamaindex_embedding_failures.py` → All checks passed
- `ruff format --check <same files>` → 3 files already formatted

## Related issue

Related to #440 (not `Fixes`: the reporter's search still failed after re-indexing and upgrading was suggested there, so this makes the persisted-index failure correctly classified and actionable rather than claiming to resolve that environment).

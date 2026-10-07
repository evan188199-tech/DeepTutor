# Exception-chain integrity scan (raise…from / cause loss) — deeptutor/

- Generated: 2026-10-07 11:41 UTC
- Revision: origin/main @ `f07029cfc` (v1.6.13)
- Scope: `deeptutor/**` — 1029 files parsed (0 syntax failures), AST-level, read-only
- Scanner: `scan_exception_chain.py` (this directory); raw results in `findings.json`
- Dedup axes: findings inside broad handlers (`except Exception` / `BaseException` / bare) carry `dedup: scan-broad-excepts` (**84** findings) — overlap with the broad-capture scan, not double-counted here. Error-message wording and error-utility axes (scan-error-messages / fix-error-utils-sanitize) are orthogonal: this scan only judges chain integrity, not message text.

## Summary

| Severity | Count |
|---|---|
| 🔴 high | 16 |
| 🟡 medium | 234 |
| 🟢 low | 3 |
| **total** | **253** |

| Rule | Meaning | Count |
|---|---|---|
| E1 missing-explicit-cause | `raise <new>` inside an except handler without `from` — implicit `__context__` survives but `__cause__` is unset (traceback shows 'During handling…', not 'direct cause') | 181 |
| E2 suppressed-cause-from-none | `raise ... from None` inside a handler — root-cause traceback deliberately dropped | 72 |

Rules with 0 findings: E3, E4, E5, E6, E7.

## Top modules

| Module | Total | high | medium | low |
|---|---|---|---|---|
| `deeptutor.api` | 226 | 2 | 224 | 0 |
| `deeptutor.services` | 17 | 11 | 5 | 1 |
| `deeptutor.tools` | 5 | 1 | 4 | 0 |
| `deeptutor.multi_user` | 2 | 1 | 1 | 0 |
| `deeptutor.runtime` | 2 | 0 | 0 | 2 |
| `deeptutor.partners` | 1 | 1 | 0 | 0 |

## Findings

### 🔴 High — 16 (root cause fully lost; triage each as accidental vs intentional sanitization)

| Location | Rule | Detail | Code |
|---|---|---|---|
| `deeptutor/api/routers/auth.py:1045` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise HandoffRejected("Invalid handoff ticket") from None` |
| `deeptutor/api/routers/auth.py:1105` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise HTTPException(` |
| `deeptutor/multi_user/session_handoff.py:176` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise HandoffRejected("Invalid handoff ticket") from None` |
| `deeptutor/partners/channels/slack.py:123` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost (handler l ·logged | `raise RuntimeError("Slack Socket Mode WebSocket connect timed out") from None` |
| `deeptutor/services/app_update.py:388` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise VersionCheckError("The latest release has an invalid version") from None` |
| `deeptutor/services/app_update.py:418` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise VersionCheckError("The latest release has an invalid URL") from None` |
| `deeptutor/services/app_update.py:435` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise VersionCheckError("The latest release has an invalid version") from None` |
| `deeptutor/services/cron/service.py:141` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise ValueError(` |
| `deeptutor/services/cron/service.py:170` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise ValueError(f"unknown timezone {schedule.tz!r}") from None` |
| `deeptutor/services/embedding/adapters/gemini.py:374` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'exc'; root cause fully lost (handler lo ·logged | `raise EmbeddingProviderError(` |
| `deeptutor/services/llm/provider_core/openai_codex_provider.py:102` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'refresh_error'; root cause fully lost ( ·logged | `raise CodexHTTPError(` |
| `deeptutor/services/partners/channel_onboarding.py:488` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise _InvalidProviderResponse(` |
| `deeptutor/services/session/_turn_runtime_shared.py:1300` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise ValueError("Could not resolve the selected text's source message") from None` |
| `deeptutor/services/settings/registry_edit.py:80` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise ValueError(` |
| `deeptutor/services/subagent/opencode_server.py:150` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise RuntimeError("server did not become ready in time") from None` |
| `deeptutor/tools/cron_tool.py:51` | E2 | 'from None' inside handler drops the root-cause traceback; raised message does not reference caught exception 'None'; root cause fully lost | `raise ValueError(` |

Triage notes for High:

- **Likely intentional sanitization** (keep suppression, but make root cause reachable): `auth.py:1045`, `session_handoff.py:176` (JWE/crypto internals → generic HandoffRejected), `gemini.py:374` (redacted body), `openai_codex_provider.py:102` (auth renewal), `turn_runtime_shared.py:1300`. Recommended pattern: `logger.debug("…", exc_info=True)` immediately before `raise ... from None`, so production debugging keeps the chain server-side.
- **Likely accidental / low value suppression**: `app_update.py:388/418/435` (ValueError → VersionCheckError), `cron/service.py:141/170` + `cron_tool.py:51` (parse/lookup errors), `registry_edit.py:80`, `opencode_server.py:150`, `slack.py:123`, `auth.py:1105`. Recommended: replace `from None` with `from e` (or embed `e` and use `from e`).

### 🟡 Medium — 234 (missing `from`; implicit `__context__` still preserves the chain)

Dominant pattern: FastAPI routers converting caught domain errors to `HTTPException` without `from` (`raise HTTPException(status_code=…, detail=str(e))`). Server logs still show the implicit chain, but `__cause__` is unset and any handler that inspects `__cause__`/re-wraps loses the direct link.

| Module | Count | Representative locations |
|---|---|---|
| `deeptutor.api` | 224 | `api/routers/auth.py:961`, `api/routers/auth.py:966`, `api/routers/auth.py:1006`, `api/routers/auth.py:1011`, `api/routers/auth.py:1065`, `api/routers/auth.py:1070` …(+218) |
| `deeptutor.services` | 5 | `services/app_update.py:378`, `services/cron/service.py:146`, `services/parsing/engines/docling/engine.py:170`, `services/parsing/engines/markitdown/engine.py:81`, `services/parsing/engines/pymupdf4llm/engine.py:113` |
| `deeptutor.tools` | 4 | `tools/tex_downloader.py:222`, `tools/vision/image_utils.py:106`, `tools/vision/image_utils.py:108`, `tools/vision/image_utils.py:110` |
| `deeptutor.multi_user` | 1 | `multi_user/session_handoff.py:137` |

<details><summary>Full medium list (path:line, rule)</summary>

```
deeptutor/api/routers/auth.py:961  E1  raise HTTPException(
deeptutor/api/routers/auth.py:966  E1  raise HTTPException(
deeptutor/api/routers/auth.py:1006  E1  raise HTTPException(
deeptutor/api/routers/auth.py:1011  E1  raise HTTPException(
deeptutor/api/routers/auth.py:1065  E1  raise HTTPException(
deeptutor/api/routers/auth.py:1070  E1  raise HTTPException(
deeptutor/api/routers/book.py:834  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:857  E1 [dedup:broad]  raise HTTPException(status_code=400, detail=f"Invalid proposal: {exc}")
deeptutor/api/routers/book.py:861  E1  raise HTTPException(status_code=404, detail=str(exc))
deeptutor/api/routers/book.py:864  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:888  E1 [dedup:broad]  raise HTTPException(status_code=400, detail=f"Invalid spine: {exc}")
deeptutor/api/routers/book.py:897  E1  raise HTTPException(status_code=404, detail=str(exc))
deeptutor/api/routers/book.py:900  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:921  E1  raise _book_paused_http(exc)
deeptutor/api/routers/book.py:923  E1  raise HTTPException(status_code=404, detail=str(exc))
deeptutor/api/routers/book.py:926  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:949  E1  raise _book_paused_http(exc)
deeptutor/api/routers/book.py:952  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:994  E1  raise _book_paused_http(exc)
deeptutor/api/routers/book.py:997  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:1063  E1  raise _book_paused_http(exc)
deeptutor/api/routers/book.py:1066  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:1093  E1  raise _book_paused_http(exc)
deeptutor/api/routers/book.py:1096  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:1364  E1  raise _book_paused_http(exc)
deeptutor/api/routers/book.py:1367  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:1412  E1  raise HTTPException(status_code=404, detail=str(exc))
deeptutor/api/routers/book.py:1415  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:1434  E1  raise HTTPException(status_code=404, detail=str(exc))
deeptutor/api/routers/book.py:1437  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/book.py:1455  E1  raise HTTPException(status_code=404, detail=str(exc))
deeptutor/api/routers/book.py:1458  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/co_writer.py:131  E2  raise HTTPException(status_code=403, detail=str(exc)) from None
deeptutor/api/routers/co_writer.py:133  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/co_writer.py:546  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:561  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:597  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:609  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:626  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:643  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:716  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:728  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:839  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:857  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/co_writer.py:874  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/file_preview.py:109  E1  raise HTTPException(status_code=404, detail="Preview source not found")
deeptutor/api/routers/file_preview.py:121  E1  raise HTTPException(status_code=404, detail="Preview source not found")
deeptutor/api/routers/knowledge.py:1427  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1486  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1507  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1539  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1563  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1595  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1615  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1635  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1650  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1686  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/knowledge.py:1698  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1751  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1781  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1803  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1819  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:1879  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2001  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2037  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2051  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2113  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2127  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2139  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2158  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2185  E1  raise HTTPException(status_code=400, detail=str(e))
deeptutor/api/routers/knowledge.py:2190  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2222  E1  raise HTTPException(status_code=400, detail=str(e))
deeptutor/api/routers/knowledge.py:2225  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2253  E1  raise HTTPException(status_code=400, detail=str(e))
deeptutor/api/routers/knowledge.py:2274  E1  raise HTTPException(status_code=400, detail=str(e))
deeptutor/api/routers/knowledge.py:2293  E1  raise HTTPException(status_code=400, detail=str(e))
deeptutor/api/routers/knowledge.py:2298  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2403  E1  raise HTTPException(status_code=400, detail=str(e))
deeptutor/api/routers/knowledge.py:2408  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2472  E1  raise HTTPException(status_code=400, detail=str(e))
deeptutor/api/routers/knowledge.py:2477  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:2545  E1  raise HTTPException(status_code=401, detail="IMA rejected the supplied credentials.")
deeptutor/api/routers/knowledge.py:2547  E1  raise HTTPException(status_code=429, detail="IMA rate limit reached. Try again shortly.")
deeptutor/api/routers/knowledge.py:2549  E1  raise HTTPException(status_code=502, detail="IMA returned an invalid response.")
deeptutor/api/routers/knowledge.py:2551  E1  raise HTTPException(status_code=502, detail="Could not reach Tencent IMA.")
deeptutor/api/routers/knowledge.py:2722  E1  raise HTTPException(status_code=400, detail=str(e))
deeptutor/api/routers/knowledge.py:2729  E1 [dedup:broad]  raise HTTPException(status_code=500, detail="Could not connect the IMA knowledge base.")
deeptutor/api/routers/knowledge.py:2960  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=f"Failed to list knowledge bases: {e!s}")
deeptutor/api/routers/knowledge.py:3001  E1  raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
deeptutor/api/routers/knowledge.py:3003  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:3050  E1  raise HTTPException(status_code=403, detail="Access denied")
deeptutor/api/routers/knowledge.py:3261  E1  raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
deeptutor/api/routers/knowledge.py:3263  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:3420  E1  raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
deeptutor/api/routers/knowledge.py:3715  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:4171  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=format_exception_message(e))
deeptutor/api/routers/knowledge.py:4220  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=format_exception_message(e))
deeptutor/api/routers/knowledge.py:4238  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:4252  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:4555  E1  raise HTTPException(status_code=404, detail=error_msg)
deeptutor/api/routers/knowledge.py:4556  E1  raise HTTPException(status_code=400, detail=error_msg)
deeptutor/api/routers/knowledge.py:4558  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:4572  E1  raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
deeptutor/api/routers/knowledge.py:4574  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:4591  E1  raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
deeptutor/api/routers/knowledge.py:4593  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/knowledge.py:4688  E1  raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
deeptutor/api/routers/knowledge.py:4690  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/mcp_settings.py:73  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/memory.py:349  E1  raise HTTPException(status_code=409, detail=str(exc))
deeptutor/api/routers/memory.py:384  E1  raise HTTPException(status_code=404, detail="unknown run_id")
deeptutor/api/routers/memory.py:386  E1  raise HTTPException(status_code=409, detail=str(exc))
deeptutor/api/routers/memory.py:714  E1  raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")
deeptutor/api/routers/memory.py:721  E1  raise HTTPException(status_code=500, detail=str(exc))
deeptutor/api/routers/notebook.py:204  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:206  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:221  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:223  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:246  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:248  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:270  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:272  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:301  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:303  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:325  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:327  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:360  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:362  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:395  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:397  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:423  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:425  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:439  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:441  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:455  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:457  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/notebook.py:475  E1  raise _unreadable(exc)
deeptutor/api/routers/notebook.py:477  E1 [dedup:broad]  raise HTTPException(status_code=500, detail=str(e))
deeptutor/api/routers/partner_groups.py:100  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:118  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:157  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:178  E2  raise HTTPException(status_code=404, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:180  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:216  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:231  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:251  E2  raise HTTPException(status_code=404, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:253  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:280  E2  raise HTTPException(status_code=404, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:283  E2  raise HTTPException(status_code=status_code, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:312  E2  raise HTTPException(status_code=404, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:314  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:332  E2  raise HTTPException(status_code=404, detail=str(exc)) from None
deeptutor/api/routers/partner_groups.py:334  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partners.py:209  E2  raise HTTPException(status_code=500, detail=str(exc)) from None
deeptutor/api/routers/partners.py:366  E2  raise HTTPException(
deeptutor/api/routers/partners.py:371  E2  raise HTTPException(
deeptutor/api/routers/partners.py:468  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1042  E2 [dedup:broad]  raise HTTPException(
deeptutor/api/routers/partners.py:1131  E2 [dedup:broad]  raise HTTPException(
deeptutor/api/routers/partners.py:1191  E2  raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1206  E2  raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1221  E2  raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1230  E2  raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1304  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1407  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1409  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1433  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1449  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1464  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1488  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1504  E2  raise HTTPException(status_code=422, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1522  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1666  E2  raise HTTPException(
deeptutor/api/routers/partners.py:1671  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/api/routers/partners.py:1673  E2  raise HTTPException(status_code=400, detail=str(exc)) from None
deeptutor/api/routers/personas.py:94  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/personas.py:118  E1  raise HTTPException(
deeptutor/api/routers/personas.py:123  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/personas.py:138  E1  raise HTTPException(status_code=404, detail=t("api.persona_not_found", name=name))
deeptutor/api/routers/personas.py:140  E1  raise HTTPException(status_code=409, detail=str(exc))
deeptutor/api/routers/personas.py:142  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/personas.py:152  E1  raise HTTPException(status_code=404, detail=t("api.persona_not_found", name=name))
deeptutor/api/routers/personas.py:154  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/question_notebook.py:300  E1  raise HTTPException(status_code=404, detail=str(e))
deeptutor/api/routers/question_notebook.py:574  E1  raise HTTPException(status_code=409, detail=str(exc))
deeptutor/api/routers/question_notebook.py:583  E1  raise HTTPException(status_code=409, detail=str(exc))
deeptutor/api/routers/settings.py:919  E2  raise _codex_http_exception(exc) from None
deeptutor/api/routers/settings.py:928  E2  raise _codex_http_exception(exc) from None
deeptutor/api/routers/settings.py:952  E2  raise _codex_http_exception(exc) from None
deeptutor/api/routers/settings.py:961  E2  raise _codex_http_exception(exc) from None
deeptutor/api/routers/settings.py:970  E2  raise _codex_http_exception(exc) from None
deeptutor/api/routers/settings.py:979  E2  raise _codex_http_exception(exc) from None
deeptutor/api/routers/settings.py:1021  E2  raise _codex_http_exception(exc) from None
deeptutor/api/routers/settings.py:1290  E2  raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
deeptutor/api/routers/skills.py:97  E1  raise HTTPException(status_code=409, detail=f"Tag already exists: {exc}")
deeptutor/api/routers/skills.py:99  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:109  E1  raise HTTPException(status_code=404, detail=f"Tag not found: {tag}")
deeptutor/api/routers/skills.py:111  E1  raise HTTPException(status_code=409, detail=f"Tag already exists: {exc}")
deeptutor/api/routers/skills.py:113  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:123  E1  raise HTTPException(status_code=404, detail=f"Tag not found: {tag}")
deeptutor/api/routers/skills.py:125  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:169  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:175  E1  raise HTTPException(status_code=502, detail=str(exc))
deeptutor/api/routers/skills.py:189  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:195  E1  raise HTTPException(status_code=502, detail=str(exc))
deeptutor/api/routers/skills.py:210  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:236  E1  raise HTTPException(status_code=409, detail=f"Skill already exists: {payload.name}")
deeptutor/api/routers/skills.py:238  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:240  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:267  E1  raise HTTPException(status_code=409, detail=f"Skill already exists: {exc}")
deeptutor/api/routers/skills.py:269  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:271  E1  raise HTTPException(status_code=502, detail=str(exc))
deeptutor/api/routers/skills.py:293  E1  raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
deeptutor/api/routers/skills.py:295  E1  raise HTTPException(status_code=403, detail=str(exc))
deeptutor/api/routers/skills.py:297  E1  raise HTTPException(status_code=409, detail=str(exc))
deeptutor/api/routers/skills.py:299  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:301  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/skills.py:311  E1  raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
deeptutor/api/routers/skills.py:313  E1  raise HTTPException(status_code=403, detail=str(exc))
deeptutor/api/routers/skills.py:315  E1  raise HTTPException(status_code=400, detail=str(exc))
deeptutor/api/routers/system.py:219  E2  raise HTTPException(
deeptutor/api/routers/system.py:290  E2  raise HTTPException(status_code=503, detail=str(exc)) from None
deeptutor/api/routers/system.py:309  E2  raise HTTPException(status_code=409, detail=str(exc)) from None
deeptutor/multi_user/session_handoff.py:137  E1  raise HandoffError("Public origin hostname is invalid")
deeptutor/services/app_update.py:378  E2  raise VersionCheckError(f"Unable to check for updates: {exc}") from None
deeptutor/services/cron/service.py:146  E2 [dedup:broad]  raise ValueError(f"invalid cron expression {schedule.expr!r}: {exc}") from None
deeptutor/services/parsing/engines/docling/engine.py:170  E1 [dedup:broad]  raise ParserError(f"Docling failed to convert {Path(source_path).name}: {exc}")
deeptutor/services/parsing/engines/markitdown/engine.py:81  E1 [dedup:broad]  raise ParserError(f"markitdown failed to convert {Path(source_path).name}: {exc}")
deeptutor/services/parsing/engines/pymupdf4llm/engine.py:113  E1 [dedup:broad]  raise ParserError(f"PyMuPDF4LLM failed to convert {source_path.name}: {exc}")
deeptutor/tools/tex_downloader.py:222  E1 [dedup:broad]  raise Exception(f"Failed to read tex file: {e!s}")
deeptutor/tools/vision/image_utils.py:106  E1  raise ImageError(f"Failed to download image: HTTP {e.response.status_code}")
deeptutor/tools/vision/image_utils.py:108  E1  raise ImageError(f"Image download timeout ({REQUEST_TIMEOUT}s)")
deeptutor/tools/vision/image_utils.py:110  E1  raise ImageError(f"Failed to download image: {e!s}")
```

</details>

### 🟢 Low — 3 (recognized idioms; no action needed)

- `deeptutor/runtime/launcher.py:432` — recognized idiom: Ctrl-C/EOF converted to SystemExit; `from None` is intentional here
- `deeptutor/runtime/launcher.py:452` — recognized idiom: Ctrl-C/EOF converted to SystemExit; `from None` is intentional here
- `deeptutor/services/session/turn_runtime.py:23` — recognized idiom: PEP 562 module/attribute __getattr__ protocol; `from None` is intentional here

## Executable fix patterns

```python
# E1 — add the missing cause link
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))          # before
    raise HTTPException(status_code=400, detail=str(e)) from e   # after

# E2 — accidental suppression: restore the chain
except ValueError:
    raise VersionCheckError("The latest release has an invalid version") from None  # before
except ValueError as e:
    raise VersionCheckError("The latest release has an invalid version") from e     # after

# E2 — intentional sanitization (API boundary): keep from None, log the cause
except (JWEError, JWSError):
    logger.debug("handoff ticket rejected", exc_info=True)       # server-side root cause
    raise HandoffRejected("Invalid handoff ticket") from None
```

## Method & limitations

- Pure `ast` analysis; no code executed, no files modified.
- A raise is attributed to a handler when it executes within the handler's dynamic scope (control-flow bodies included; nested handlers, nested function/class bodies excluded).
- E1 severity assumes FastAPI-style re-wrapping; implicit `__context__` means nothing is silently swallowed by E1 findings — the gap is `__cause__` explicitness and tooling that reads it.
- `from None` intent (sanitization vs accidental) cannot be proven from AST; the `logged` tag marks handlers that log before raising. Human triage recommended for the 16 High items.

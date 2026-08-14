# DeepTutor — Agent-Native Architecture

## Overview

DeepTutor is an **agent-native** intelligent learning companion organized
around a two-layer plugin model — single-shot **Tools** invoked by the
LLM, and multi-stage **Capabilities** that take over a turn — exposed
through three entry points: CLI, WebSocket API, and Python SDK.

## Architecture

```
Entry Points:  CLI (Typer)  |  WebSocket /api/v1/ws  |  Python SDK
                    ↓                   ↓                   ↓
              ┌─────────────────────────────────────────────────┐
              │              ChatOrchestrator                    │
              │   routes UnifiedContext → selected Capability    │
              │   (defaults to `chat`)                           │
              └──────────┬──────────────┬───────────────────────┘
                         │              │
              ┌──────────▼──┐  ┌────────▼──────────┐
              │ ToolRegistry │  │ CapabilityRegistry │
              │  (Level 1)   │  │   (Level 2)        │
              └──────────────┘  └────────────────────┘
```

All capabilities emit on a shared `StreamBus`; the orchestrator fans
events out to consumers. Runtime settings live in
`data/user/settings/*.json` — project-root `.env` files are intentionally
ignored.

### Level 1 — Tools

Single-function tools the LLM picks on demand. Four user-toggleable tools
surface in `/settings/tools`:

| Tool           | Description                                   |
| -------------- | --------------------------------------------- |
| `brainstorm`   | Breadth-first idea exploration with rationale |
| `web_search`   | Web search with citations                     |
| `paper_search` | arXiv preprint search                         |
| `reason`       | Dedicated deep-reasoning LLM call             |

The rest are **context-gated**: the chat capability auto-mounts them from
`ToolMountFlags` (presence of a KB, attachments, sandbox availability, …), and
any of them can also be force-enabled via `--tool`. Auto-mounted set: `rag`,
`read_source`, `read_memory`, `write_memory`, `read_skill`, `load_tools`,
`exec`, `code_execution` (sandboxed Python: NL intent → code → run),
`list_notebook`, `write_note`, `web_fetch`, `github`, `cron`,
`ask_user` (pauses the turn and resumes with the user's reply), plus the
mastery-path tools. `geogebra_analysis` is parked under
`COMING_SOON_TOOL_TYPES`.

### Level 2 — Capabilities

Multi-stage pipelines that own the turn:

| Capability       | Stages                                                |
| ---------------- | ----------------------------------------------------- |
| `chat`           | exploring → responding (single agentic loop, default) |
| `mastery_path`   | responding (Guided Learning — chat loop + mastery tools, gated per topic type) |
| `deep_solve`     | planning → reasoning → writing                        |
| `deep_question`  | ideation → generation                                 |
| `deep_research`  | rephrasing → decomposing → researching → reporting    |
| `visualize`      | analyzing → generating → reviewing (SVG / Chart.js / Mermaid / HTML; or routes to Manim sub-stages via `render_type`) |
| `math_animator`  | concept_analysis → concept_design → code_generation → code_retry → summary → render_output |

All capabilities converge on `emit_capability_result()` in
`deeptutor/capabilities/_shared.py` so every turn emits the same envelope
(response payload + `cost_summary` from `UsageTracker`). Status copy and
prompts are i18n'd via `capabilities/prompts/{en,zh}/<name>.yaml`.

## CLI Usage

```bash
# Install
pip install deeptutor      # Full app (CLI + Web/API + packaged Web assets)
pip install deeptutor-cli  # CLI-only

# Run any capability
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2=4" -t rag --kb my-kb
deeptutor run visualize "Animate sine wave" --config render_mode=manim_video

# Interactive REPL
deeptutor chat
# (inside the REPL: /regenerate or /retry re-runs the last user message)

# Partners (IM-connected companions)
deeptutor partner list

# Knowledge bases, memory, server
deeptutor kb list
deeptutor kb create my-kb --doc textbook.pdf
deeptutor memory show
deeptutor serve --port 8001       # API server only
deeptutor start                   # backend + frontend together
```

## Key Files

| Path                                       | Purpose                              |
| ------------------------------------------ | ------------------------------------ |
| `deeptutor/runtime/orchestrator.py`        | `ChatOrchestrator` — unified entry   |
| `deeptutor/runtime/launcher.py`            | Backend + frontend lifecycle / port discovery |
| `deeptutor/runtime/registry/`              | Tool + Capability registries         |
| `deeptutor/runtime/bootstrap/builtin_capabilities.py` | Built-in capability class paths |
| `deeptutor/services/config/runtime_settings.py` | JSON settings + process-env overrides |
| `deeptutor/core/stream.py`, `stream_bus.py` | StreamEvent protocol + async fan-out |
| `deeptutor/core/tool_protocol.py`          | `BaseTool` + `ToolDefinition`         |
| `deeptutor/core/capability_protocol.py`    | `BaseCapability` + `CapabilityManifest` |
| `deeptutor/core/context.py`                | `UnifiedContext` dataclass            |
| `deeptutor/tools/builtin/__init__.py`      | All built-in tool wrappers           |
| `deeptutor/capabilities/`                  | Built-in capability implementations  |
| `deeptutor/app.py`                         | `DeepTutorApp` — Python SDK facade    |
| `deeptutor_cli/main.py`                    | Typer CLI entry point                |
| `deeptutor/api/routers/unified_ws.py`      | Unified WebSocket endpoint           |

## Dependency Layers

Public install paths and source extras are defined in `pyproject.toml`.
Requirements files mirror the same dependency groups for Docker/CI installs.

```
pip install deeptutor      — Full app (CLI + Web/API + packaged Web assets)
pip install deeptutor-cli  — CLI-only (LLM + RAG + providers + document parsing)
pip install -e .           — Source install for development

Source extras (.[ extra ], defined in pyproject.toml):
.[cli]            — CLI-only dependency set
.[server]         — Web/API server dependencies
.[partners]       — Partner channel SDKs + MCP client  (legacy alias: .[tutorbot])
.[matrix]         — Matrix channel for Partners (matrix-nio; needs libolm)
.[matrix-e2e]     — Matrix with end-to-end encryption (matrix-nio[e2e])
.[math-animator]  — Manim addon (powers `visualize` Manim renders + `deeptutor run math_animator`)
.[dev]            — Test / lint tooling
.[all]            — Everything above
```

## Engineering Delivery Requirements

- Before development, research the relevant open-source context: search for
  related issues, pull requests, the current implementation, and tests. Cite
  adopted issues or PRs by number or URL in the delivery report.
- Use this reference priority: current code and tests; target-branch PRs that
  are merged and well-validated; confirmed issues or roadmap items; open or
  draft PRs.
- Do not copy an older solution mechanically. Check its target branch,
  compatibility with the current architecture, test evidence, and likely
  follow-up evolution. Record obsolete or conflicting PRs explicitly.
- If GitHub is unavailable, continue with local Git history and repository
  documentation, and disclose the research limitation.
- Follow `CONTRIBUTING.md` for upstream work. Use `dev` as the usual target
  branch and `multi-user` for multi-user changes; never silently switch the
  current branch.
- Protect existing worktree changes and generated artifacts. Keep the change
  scope narrow, distinguish new failures from pre-existing failures, and do
  not clean up unrelated uncommitted work.

### Verification Matrix

- For Python changes, focus on `pytest`; when warranted, run
  `pytest -q tests deeptutor/learning/tests`.
- For Python quality, run `ruff check`, `ruff format --check`, or the relevant
  pre-commit checks when configured.
- For Web changes, run `npm run test:node`, `npm run lint`, and `npm run build`;
  add `npm run i18n:check` when copy or locale files are involved.
- For UI features, actually inspect loading, skeleton, empty, error, desktop,
  and mobile/responsive states.
- Choose checks in proportion to risk, run the relevant application flow, and
  report each acceptance item as `PASS`, `FAIL`, or `BLOCKED` with evidence.
  Continue fixing failures until they pass; never claim completion for an
  unverified item.

### Delivery gates

- Follow this default loop for non-trivial work: **research → decision → acceptance checklist → confirmation → development → real verification → fix-and-verify closure**.
- Before development, read repository rules, relevant code and tests, and current worktree status. Do not ask the user for facts that can be discovered locally.
- Ask only about decisions that materially change product behavior, architecture, security, or compatibility. Make reasonable assumptions for non-critical details and record them.
- For a genuine major trade-off, present three materially different enterprise-grade options with benefits, cost, risks, and a recommendation. Do not manufacture three options for a simple fix or explicit issue.
- For non-trivial work, publish a concise Markdown acceptance checklist and wait for confirmation before coding. For clear, low-risk, repetitive work, self-confirm and record that decision.
- The checklist should cover applicable items: background and goal; core flow; architecture and interfaces; data and permissions; error and empty states; skeleton and loading states; terminal and responsive behavior; compatibility and migration; tests; and success criteria.
- After implementation, run relevant tests and the application flow. Report every checklist item as `PASS`, `FAIL`, or `BLOCKED` with evidence. Fix failures and rerun verification; do not claim completion for unverified items.

### Research and upstream reference order

- Search same-topic issues, PRs, current implementation, and tests for every development item.
- Prefer references in this order: current code and tests; merged and well-validated PRs targeting the current branch; confirmed issues or roadmap items; open or draft PRs.
- Check target branch, architecture fit, test evidence, compatibility, and future evolution before adopting any precedent. Record stale or conflicting references.
- When GitHub is unavailable, use local Git history and repository documentation and disclose that limitation.

### Branch and change-boundary rules

- Follow `CONTRIBUTING.md`: normally target `dev`; use `multi-user` for multi-user changes. Never silently switch the current branch.
- Preserve existing user changes and generated artifacts. Distinguish pre-existing failures from regressions, and never clean unrelated uncommitted work.

### Acceptance and verification record

- Record assumptions, the confirmation decision (or low-risk self-confirmation), selected checks, and evidence in the delivery report.
- For UI changes, verify loading, skeleton, empty, error, desktop, mobile, and responsive states when applicable.
- Use `PASS / FAIL / BLOCKED` per acceptance item. A `FAIL` requires another repair-and-rerun cycle; a `BLOCKED` must name the missing access, dependency, or environment evidence.

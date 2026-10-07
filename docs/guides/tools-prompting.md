# tools/prompting — prompt-hint templates guide

> **Scope boundary.** This guide covers only the `deeptutor/tools/prompting/` subpackage
> (its loader/composer module plus the 54 hint YAML files). The top-level tool
> implementations (`deeptutor/tools/*.py`, `deeptutor/tools/builtin/`, capability tools)
> are owned by the guide-tools card and are described here only as consumers of this
> package's API.

## 1. What lives here

55 files, one Python module and pure data:

- `deeptutor/tools/prompting/__init__.py` — the entire code surface: YAML loading
  (`load_prompt_hints`, `deeptutor/tools/prompting/__init__.py:52`) and text rendering
  (`ToolPromptComposer`, `deeptutor/tools/prompting/__init__.py:89`;
  `compose_prompt_text`, `deeptutor/tools/prompting/__init__.py:203`).
- `hints/en/*.yaml` (27 files) and `hints/zh/*.yaml` (27 files) — one file per hinted
  tool, one prompt metadata record per file. `en` is the fallback language;
  `deeptutor/tools/prompting/__init__.py:56-58`.

There is no per-module Python code: adding or editing a hint is a YAML edit, never a
code change in this package.

## 2. Record schema: YAML → dataclasses

Each YAML file maps to `ToolPromptHints`
(`deeptutor/core/tool_protocol.py:117-126`):

| YAML key | Field | Used by |
|---|---|---|
| `short_description` | one-line "what it is" | `format_list`, `format_list_with_usage`, `format_aliases` fallback (`__init__.py:95-100,102-122,154-167`) |
| `when_to_use` | decision guidance | `format_list_with_usage`, `format_table` (`__init__.py:102-122,124-152`) |
| `input_format` | argument shape shown to the LLM | same as `when_to_use` |
| `guideline` | behavioral rule | `format_table`, `format_phased` (`__init__.py:143-146,187-190`) |
| `note` | extra caveat | `format_table` notes block (`__init__.py:148-150`) |
| `phase` | research-phase bucket | `format_phased` grouping (`__init__.py:169-200`) |
| `aliases` (list) | `ToolAlias` records | `format_aliases`, `format_phased` (`__init__.py:154-167,174-186`) |

`ToolAlias` fields are `name/description/input_format/when_to_use/phase`
(`deeptutor/core/tool_protocol.py:106-113`). **Currently no hint file uses
`aliases:`** — the alias path is a dormant extension point (see §7).

A real example: `hints/en/rag.yaml` (all six scalar keys, `phase: "exploration"`).
The richest file is `hints/en/ask_user.yaml`, whose `input_format` is a YAML block
scalar embedding a JSON example with per-question option rules.

## 3. Loading and selection logic

`load_prompt_hints(tool_name, language)` (`deeptutor/tools/prompting/__init__.py:52-86`):

1. Language is normalized: anything starting `zh` → `zh`, `en` → `en`, else kept as-is
   (`__init__.py:43-49`). So `zh-CN` resolves to the `zh` file.
2. Candidate files: `hints/<lang>/<tool_name>.yaml`, then `hints/en/<tool_name>.yaml`
   when the language is not `en` (`__init__.py:56-58`). Selection is therefore
   **file name == tool name**, with zh→en per-file fallback; there is no partial
   fallback (a missing key is just an empty string, `__init__.py:77-83`).
3. Missing tool_name in both languages returns an **empty** `ToolPromptHints()`
   (`__init__.py:86`) — callers cannot distinguish "tool has no hints" from
   "hints are blank".

## 4. Rendering: five formats, one dispatcher

`ToolPromptComposer` (`__init__.py:89`) renders a `list[tuple[name, ToolPromptHints]]`:

- `format_list` (`__init__.py:95-100`) — `- name: short_description` bullets. Tools
  with an empty `short_description` are **skipped** (`__init__.py:98`).
- `format_list_with_usage` (`__init__.py:102-122`) — bullet plus indented
  "When to use" / "Input" lines (labels localized at `__init__.py:110-111`). Also
  skips empty `short_description` (`__init__.py:114-115`).
- `format_table` (`__init__.py:124-152`) — Markdown action table (with optional
  `control_actions` rows, `__init__.py:137-140`), then a guideline block headed by
  `_GUIDELINE_HEADER` (`__init__.py:15-21,143-146`), then notes (`__init__.py:148-150`).
- `format_aliases` (`__init__.py:154-167`) — one line per alias; without aliases it
  degrades to name + short_description + input format.
- `format_phased` (`__init__.py:169-200`) — groups by `phase` into the fixed
  `_PHASE_ORDER` = exploration, expansion, synthesis, verification, other
  (`__init__.py:40`), labeled via `_PHASE_LABELS` (`__init__.py:23-38`).

`compose_prompt_text(hints, format=..., language=..., **opts)` is the single dispatch
entry and raises `ValueError` on unknown formats
(`__init__.py:203-227`). Both registries route through it so every registry renders
identically (`__init__.py:210-215`).

### Which call site uses which format (production code)

| Caller | Format | Site |
|---|---|---|
| Agentic chat loop tool manifest | `list_with_usage` | `deeptutor/agents/loop/pipeline.py:537-553` (format at :546) |
| Research block loops | `list_with_usage` | `deeptutor/agents/research/pipeline.py:965-972` |
| Question pipeline tool list | `list_with_usage` | `deeptutor/agents/question/pipeline.py:1714-1719` |
| Co-writer external-reference tools (rag/web_search only) | `list` | `deeptutor/co_writer/edit_agent.py:370-382` (format at :381) |

`table`, `aliases` and `phased` have **no production callers** today — they are
retained render paths (no other caller exists in `deeptutor/`).

## 5. Who supplies hints: three tiers

A tool reaches a prompt through `registry.build_prompt_text(...)`, which collects
`tool.get_prompt_hints(language)` per tool
(`deeptutor/runtime/registry/tool_registry.py:121-145`;
scoped variant `deeptutor/runtime/registry/scoped_registry.py:107-124`).

1. **YAML-backed** — classes that delegate to `load_prompt_hints(self.name, ...)`:
   the 21 built-ins via `_PromptHintsMixin`
   (`deeptutor/tools/builtin/__init__.py:26-30`, classes at :33-1789),
   `ExecTool` (`deeptutor/tools/exec_tool.py:53`), the four mastery nav tools
   (`deeptutor/tools/mastery_nav.py:196-203`), `ImagegenTool`/`VideogenTool`
   (`deeptutor/tools/media_gen_tool.py:138,220`), and the eight reading tools
   (`deeptutor/capabilities/reading/_tool_base.py:26-28`).
2. **Definition-derived default** — `BaseTool.get_prompt_hints`
   (`deeptutor/core/tool_protocol.py:258-263`) returns
   `ToolPromptHints(short_description=definition.description)`. All capability
   tools without hint files (solve/obsidian/marginnote/ima/setup/course/partner/
   workspace/subagent, etc., catalog at
   `deeptutor/tools/builtin_specs.py:46-205`) land here.
3. **Empty** — YAML-backed classes whose name has no YAML file: they return the
   empty hints of §3 and are then silently dropped from `list`/`list_with_usage`
   renderings. Today this applies to `cron` (mixin at
   `deeptutor/tools/builtin/__init__.py:1789`, no `hints/*/cron.yaml`), the reading
   tools (`reading_list_tabs` … `reader_annotate`, spec at
   `deeptutor/tools/builtin_specs.py:162-174`, no matching YAML), and the legacy
   workspace file tools (`deeptutor/tools/file_tools.py:28-30`, which today is
   referenced only by `tests/tools/test_file_tools.py`).

Note the asymmetry between tier 2 and tier 3: a tool *without* the mixin still shows
up in lists via its definition description; a YAML-backed tool *without* a YAML file
disappears from the list. If you adopt the mixin, ship the YAML in the same change.

The zh/en parity of the hint set is maintained by hand: every name in `hints/en/`
has a twin in `hints/zh/` (27/27 today), with matching `phase` values.

## 6. Consumers beyond prompts

- **Web API**: the built-in tools endpoint serializes both languages' hints per tool
  for the UI (`deeptutor/api/routers/tools.py:183-184`, payload builder
  `_serialise_hints` at :135) and lists execution aliases from a *different* source,
  `TOOL_ALIASES` (`deeptutor/api/routers/tools.py:156-157`; registry-level table
  `deeptutor/tools/builtin_specs.py:217-222`). YAML `aliases:` and `TOOL_ALIASES`
  are unrelated mechanisms with the same name.
- **Language flow**: pipelines pass their turn language (e.g.
  `deeptutor/agents/loop/pipeline.py:244`) straight into
  `build_prompt_text(..., language=...)`, so one conversation gets a consistent
  zh or en tool manifest.

## 7. Extension points (and traps)

1. **Add hints for a tool** — create `hints/en/<tool_name>.yaml` (+ `hints/zh/`),
   make the tool class YAML-backed (mixin or a `get_prompt_hints` override like
   `deeptutor/tools/mastery_nav.py:202`). No registry change needed; the loader is
   name-driven (`__init__.py:56`).
2. **Alias surface for one tool** — fill `aliases:` in the YAML and render with
   `format="aliases"` or `format="phased"`; aliases can carry their own
   `phase` (`__init__.py:174-186`). No file uses this yet.
3. **Extra rows in `format_table`** — pass `control_actions=[{name, when_to_use,
   input_format}]` through `compose_prompt_text(**opts)` (`__init__.py:137-140,222`).
   No caller yet.
4. **Trap: unknown phases vanish from `format_phased`.** Phase strings outside
   `_PHASE_ORDER` (`__init__.py:40`) are collected into ad-hoc groups
   (`__init__.py:170-177`) but never rendered, because output iterates only
   `_PHASE_ORDER` (`__init__.py:194`). Today, `hints/en/write_memory.yaml` uses
   `phase: "execution"` and `brainstorm.yaml` uses `phase: "ideation"` — both would
   be dropped by a `phased` rendering (harmless today because no caller uses it).
5. **Trap: missing YAML silences a mixin tool** (tier 3 in §5). Prefer the tier-2
   default when you only want the definition description to show.
6. **Trap: `format_table` emits rows for hints that have `when_to_use` or
   `input_format` even without `short_description`** (`__init__.py:135-136`), while
   the list formats skip those — formats disagree on the "empty" predicate.

## 8. Key files

| File | Role |
|---|---|
| `deeptutor/tools/prompting/__init__.py` | loader (`:52`) + composer (`:89`) + dispatcher (`:203`) |
| `deeptutor/tools/prompting/hints/en/*.yaml`, `hints/zh/*.yaml` | 27+27 hint records; file name = tool name |
| `deeptutor/core/tool_protocol.py` | `ToolAlias` (`:106`), `ToolPromptHints` (`:117`), default `get_prompt_hints` (`:258`) |
| `deeptutor/tools/builtin/__init__.py` | `_PromptHintsMixin` (`:26`) wiring 21 built-ins to YAML |
| `deeptutor/tools/builtin_specs.py` | builtin catalog (`:46-205`), `TOOL_ALIASES` (`:217`) |
| `deeptutor/runtime/registry/tool_registry.py` | `get_prompt_hints` (`:121`), `build_prompt_text` (`:132`) |
| `deeptutor/runtime/registry/scoped_registry.py` | same API over a scoped view (`:107-124`) |
| `deeptutor/agents/loop/pipeline.py` | chat tool manifest, `list_with_usage` (`:537-553`) |
| `deeptutor/api/routers/tools.py` | web payload with en+zh hints (`:135,183-184`) |

## 9. Tests and coverage

Existing tests touching this package (all are content assertions on specific
tools, none cover the loader/composer API itself):

- `tests/tools/test_exec_prompt_hints.py` — exec hints must not suggest POSIX
  filters as portable commands and must state the sandbox-denial rule, en+zh.
- `tests/tools/test_code_execution_guidance.py:25` — exec guidance via
  `load_prompt_hints("exec", ...)`.
- `tests/tools/test_zotero_search.py:190-195` — zotero hints are bilingual and
  carry short_description/guideline/input_format.
- `tests/services/test_media_gen.py:104-109` — imagegen vs videogen hints must
  distinguish generation from execution.

Coverage gaps (no test exists for any of these):

1. `load_prompt_hints` behavior: zh→en fallback, unknown-language normalization,
   missing-file → empty hints, `aliases` parsing.
2. `ToolPromptComposer` / `compose_prompt_text`: all five formats, the
   `ValueError` on unknown format (`__init__.py:227`), the `control_actions` path.
3. Data invariants across the 54 YAML files: en/zh name parity, required keys
   non-empty, `phase` values within `_PHASE_ORDER` (two files currently violate
   it, §7.4), YAML parseability.
4. Registry integration: `build_prompt_text` output for a mixed set of
   YAML-backed / definition-only / YAML-less-mixin tools (the tier drop-out in §5).

## 10. Suggested reading order

1. `hints/en/rag.yaml`, then `hints/en/ask_user.yaml` — simple and rich records.
2. `deeptutor/tools/prompting/__init__.py:52-86` — how a record is loaded.
3. `deeptutor/tools/prompting/__init__.py:95-227` — how records become prompt text.
4. `deeptutor/agents/loop/pipeline.py:537-553` — the main consumer's manifest.
5. `deeptutor/api/routers/tools.py:160-200` — the web surface over the same data.

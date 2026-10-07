# Unused static assets — scan report (assets/figs + web/public)

- HEAD: `f07029cfcf2c8dfccdb671cdfc343db8334f5741`
- Assets scanned: 129 (assets/figs: 74, web/public: 55)
- Corpus: 3470 tracked files (excl. the two scanned trees and scan/)
- Candidates: **48** files, **12,327,953 bytes** (11.76 MiB) total cleanable

## Method (reproducible)

`scan_unused_assets.py` (in this directory) walks `git ls-files`, then
searches every corpus file (tracked files outside `assets/figs/`,
`web/public/` and `scan/`) for the patterns below. All patterns use
boundary guards: a leading `(?<![A-Za-z0-9_./-])` so a short form
never matches inside a longer path pointing at a different asset,
and a trailing `(?![A-Za-z0-9_-])` that still allows prose or markup
punctuation right after the name (e.g. a sentence ending `README.md.`).

| Pattern | Example |
| --- | --- |
| A1 rel-from-root | `assets/figs/web-1.4.6+/home/home.png` |
| A2 figs-rel | `figs/web-1.4.6+/home/home.png` |
| A3 tree-rel | `web-1.4.6+/home/home.png` |
| B1 public-url | `/knowledge-engine-icons/llamaindex.png` |
| B2 public-rel | `knowledge-engine-icons/llamaindex.png` |
| B3 web-public-rel | `public/agent-icons/README.md` |
| C basename-unique | `llamaindex.png` (only if unique across all scanned assets) |

Any pattern containing a space is additionally searched percent-encoded
(`%20`), which is how the READMEs reference filenames with spaces
(e.g. `assets/figs/system/system%20architecture.png` at `README.md:667`).

Dynamic construction is covered: `web/components/common/ProviderIcon.tsx:88`
builds `/provider-icons/${spec.file}` from string literals in the same file
(e.g. `file: "openai.svg"`), matched by B1/B2/C. Shared basenames such as
`00-overview.png` or `OVERVIEW.png` exist in several screenshot dirs, so
they are ambiguous: pattern C never applies to them, and a bare basename
match cannot make one of its siblings referenced.

The candidate table lists each file's pattern set; "0 hits" means none
of the file's patterns matched any of the corpus files.

Sibling references never count: the corpus excludes both scanned trees,
so the vendored-icon READMEs (`web/public/*/README.md`) and other
screenshots cannot vouch for their neighbours. Weak stem collisions are
recorded in `scan_unused_assets.json` but never counted as references.

## Cleanup candidates (unreferenced)

| Path | Bytes | Judgment evidence |
| --- | --- | --- |
| `assets/figs/chat-loop.png` | 1,187,881 | 0 hits for patterns A1, A2, A3 in 3470 corpus files; weak stem hits (not references): assets/releases/past_releases/ver1-5-15.md, deeptutor/api/routers/partners.py, deeptutor/capabilities/__init__.py, deeptutor/capabilities/mastery/tools.py, deeptutor/capabilities/registry.py, deeptutor/capabilities/solve/tools.py, deeptutor/core/entry_points.py, deeptutor/learning/policy.py, deeptutor/learning/tests/test_mastery_tools.py, deeptutor/runtime/capability_catalog.py, deeptutor/services/session/_turn_runtime_shared.py, deeptutor/services/session/turns/executor.py, deeptutor/services/subagent/partner.py, deeptutor_cli/common.py, tests/cli/test_turn_renderer.py, tests/services/partners/conftest.py, tests/services/partners/scripts.py, tests/services/partners/test_partner_runtime.py, web/components/partners/PartnerChat.tsx, web/features/chat/trace/TracePresentation.tsx, web/features/chat/trace/selectors.ts |
| `assets/figs/logo/logo_black.png` | 197,256 | 0 hits for patterns A1, A2, A3 in 3470 corpus files; weak stem hits (not references): web/components/chat/home/SessionLoadingView.tsx, web/features/chat/components/ChatWorkspace.tsx, web/tests/proxy-policy.test.ts |
| `assets/figs/web-1.4.6+/OVERVIEW.png` | 157,676 | 0 hits for patterns A1, A2, A3 in 3470 corpus files; weak stem hits (not references): README.md, assets/README/README_AR.md, assets/README/README_CN.md, assets/README/README_ES.md, assets/README/README_FR.md, assets/README/README_HI.md, assets/README/README_JA.md, assets/README/README_PL.md, assets/README/README_PT.md, assets/README/README_RU.md, assets/README/README_TH.md, assets/README/README_TW.md, deeptutor/book/agents/spine_synthesizer.py, deeptutor/book/engine.py, deeptutor/book/estimate.py, deeptutor/book/models.py, tests/book/test_overview_chapter.py |
| `assets/figs/web-1.4.6+/book/04-book-demo side chat & mermaid.png` | 629,193 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/book/05-book- add customize block for chapter.png` | 240,809 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/book/06-book-switch the block type.png` | 251,212 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/extensions/00-mcp-store.png` | 175,176 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/extensions/02-cli-apps.png` | 155,953 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/01-capabilities.png` | 141,066 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/02-add contexts.png` | 167,624 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/03-another use subagent.png` | 77,816 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/03-use subagent.png` | 39,998 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/04-attatch knowledge base.png` | 9,602 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/05-customize persona.png` | 195,307 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/06-switch model.png` | 86,224 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/07-side bar for various activities.png` | 205,672 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/08-another subagent demo with partners.png` | 692,942 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/09-demo with configured image-gen model(as a tool).png` | 1,362,884 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/10-configure models.png` | 287,844 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/home/11-configure and explore tools.png` | 371,635 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/knowledge/02-panel for each knowledge base.png` | 452,237 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/knowledge/03-config document parsing engine in settings.png` | 364,582 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/learning-space/01-chat history.png` | 144,139 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/learning-space/02-notebooks.png` | 118,062 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/learning-space/03-question bank.png` | 169,435 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/learning-space/04-mastery path.png` | 325,007 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/learning-space/05-personas.png` | 175,932 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/learning-space/06-skills.png` | 262,469 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/memory/02-config memory params in settings.png` | 295,325 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/myagents/01-sync selective chat history from claude code or codex.png` | 414,315 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/notebook/00-console.png` | 149,261 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/partners/01-chat with partners.png` | 372,457 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/reading/00-overview.png` | 179,504 | 0 hits for patterns A1, A2, A3 in 3470 corpus files; weak stem hits (not references): README.md, assets/README/README_AR.md, assets/README/README_CN.md, assets/README/README_ES.md, assets/README/README_FR.md, assets/README/README_HI.md, assets/README/README_JA.md, assets/README/README_PL.md, assets/README/README_PT.md, assets/README/README_RU.md, assets/README/README_TH.md, assets/README/README_TW.md |
| `assets/figs/web-1.4.6+/reading/01-open-a-document.png` | 197,411 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/reading/02-cited-answer.png` | 714,407 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.4.6+/settings/03-starting-points.png` | 281,048 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.12/settings/00-general-overview.png` | 137,530 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.12/settings/01-runtime-status-readiness.png` | 101,472 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.12/settings/02-workspace-create.png` | 124,732 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.12/settings/03-provider-connection-api-format.png` | 120,303 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.12/settings/04-model-list-picker.png` | 136,329 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.12/settings/05-model-capabilities.png` | 135,923 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.5/settings/00-settings-overview.png` | 79,471 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.5/settings/01-settings-readiness.png` | 68,256 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.5/settings/02-settings-workspace.png` | 79,875 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.5/settings/03-model-api-format-capability.png` | 59,069 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `assets/figs/web-1.6.5/settings/04-model-list-picker.png` | 34,955 | 0 hits for patterns A1, A2, A3 in 3470 corpus files |
| `web/public/knowledge-engine-icons/README.md` | 677 | 0 hits for patterns A1, B1, B2, B3, C in 3470 corpus files; weak stem hits (not references): .dockerignore, .github/ISSUE_TEMPLATE/docs.yml, CONTRIBUTING.md, README.md, assets/README/README_AR.md, assets/README/README_CN.md, assets/README/README_ES.md, assets/README/README_FR.md, assets/README/README_HI.md, assets/README/README_JA.md, assets/README/README_PL.md, assets/README/README_PT.md, assets/README/README_RU.md, assets/README/README_TH.md, assets/README/README_TW.md, assets/releases/past_releases/ver1-1-1.md, assets/releases/past_releases/ver1-1-2.md, assets/releases/past_releases/ver1-2-0.md, assets/releases/past_releases/ver1-2-3.md, assets/releases/past_releases/ver1-2-4.md, assets/releases/past_releases/ver1-3-0.md, assets/releases/past_releases/ver1-3-1.md, assets/releases/past_releases/ver1-3-4.md, assets/releases/past_releases/ver1-3-5.md, assets/releases/past_releases/ver1-3-8.md, assets/releases/past_releases/ver1-4-2.md, assets/releases/past_releases/ver1-4-4.md, assets/releases/past_releases/ver1-4-9.md, assets/releases/past_releases/ver1-6-6.md, deeptutor/knowledge/add_documents.py, deeptutor/multi_user/identity.py, deeptutor/services/cli_apps/provider.py, deeptutor/services/cli_apps/vendor/catalog.json, deeptutor/services/parsing/engines/liteparse/formats.py, deeptutor/skills/builtin/skill-creator/SKILL.md, docs-for-user/CONTAINERIZATION.md, packaging/deeptutor-cli/pyproject.toml, pyproject.toml, start_deeptutor.command, tests/api/test_knowledge_router.py, tests/capabilities/test_mastery_capability.py, tests/cli/test_docs_contract.py, tests/cli/test_kb_cli.py, tests/cli/test_provider_cli.py, tests/knowledge/test_add_documents_linked_folder.py, tests/scripts/test_docker_compose.py, tests/scripts/test_workspace_hygiene.py, tests/services/rag/test_file_routing.py, web/components/agents/agent-icons.tsx, web/tests/doc-attachments.test.ts |

## False-positive exclusions

None required by hand: every web/public icon resolves via a static
string literal (PROVIDER_ICONS map in `ProviderIcon.tsx`, the engine
map in `KnowledgeEngineIcon.tsx`, `OfficialAssetGlyph src=...` in
`agent-icons.tsx`), so no dynamically-only-used icon had to be
excluded from the candidate list. Shared-basename screenshots are
handled by the ambiguity rule above instead of manual overrides.

## Notes

- `web/public/knowledge-engine-icons/README.md` is a licensing/
  provenance record for the vendored engine icons (it is the only
  web/public candidate). Unreferenced by code, but recommend keeping
  it (or relocating it outside `public/`) rather than deleting.
- The 47 assets/figs candidates include three whole screenshot
  generations of the settings page that were never wired into any
  README: `web-1.6.12/settings/` (6 files), `web-1.6.5/settings/`
  (5 files) and most of `web-1.4.6+/` beyond the 27 screenshots the
  READMEs actually embed. This is the README staleness problem in
  reverse: docs keep pointing at web-1.4.6+/web-1.6.5 shots while
  newer captures accumulate unreferenced.
- Safe-delete caveat: candidates are unreferenced in this tree, but
  release notes under `assets/releases/` document history and were
  part of the corpus; nothing under `assets/releases/` references
  any candidate.

## Referenced assets (not candidates)

| Path | Bytes | Evidence (pattern: corpus file:lines, first 5) |
| --- | --- | --- |
| `assets/figs/logo/banner.png` | 151,954 | A1_rel_from_root: README.md:3 |
| `assets/figs/logo/logo.png` | 202,234 | A1_rel_from_root: README.md:3 |
| `assets/figs/partners/pageindex-mark-dark.svg` | 7,686 | A1_rel_from_root: README.md:1085 |
| `assets/figs/partners/pageindex-mark.svg` | 7,686 | A1_rel_from_root: README.md:1086,1087 |
| `assets/figs/system/chat-agent-loop.png` | 914,360 | A1_rel_from_root: README.md:684 |
| `assets/figs/system/partners-architecture.png` | 1,127,505 | A1_rel_from_root: README.md:705 |
| `assets/figs/system/system architecture.png` | 1,107,882 | A1_rel_from_root_pct20: README.md:667 |
| `assets/figs/web-1.4.6+/book/00-book_overview.png` | 158,364 | A1_rel_from_root: README.md:783 |
| `assets/figs/web-1.4.6+/book/01-book-demo-quiz card.png` | 582,427 | A1_rel_from_root_pct20: README.md:789 |
| `assets/figs/web-1.4.6+/book/02-book-demo-manim video.png` | 638,446 | A1_rel_from_root_pct20: README.md:791 |
| `assets/figs/web-1.4.6+/book/03-book-demo interactive module.png` | 567,514 | A1_rel_from_root_pct20: README.md:793 |
| `assets/figs/web-1.4.6+/co-writer/00-overview.png` | 134,875 | A1_rel_from_root: README.md:766 |
| `assets/figs/web-1.4.6+/co-writer/01-edit panel.png` | 646,029 | A1_rel_from_root_pct20: README.md:772 |
| `assets/figs/web-1.4.6+/home/00-overview.png` | 145,910 | A1_rel_from_root: README.md:678 |
| `assets/figs/web-1.4.6+/home/08-subagent demo with claude code.png` | 585,851 | A1_rel_from_root_pct20: README.md:755 |
| `assets/figs/web-1.4.6+/knowledge/00-overview.png` | 322,602 | A1_rel_from_root: README.md:804 |
| `assets/figs/web-1.4.6+/knowledge/01-create knowledge base.png` | 375,418 | A1_rel_from_root_pct20: README.md:810 |
| `assets/figs/web-1.4.6+/learning-space/00-overview.png` | 253,853 | A1_rel_from_root: README.md:833 |
| `assets/figs/web-1.4.6+/learning-space/07- download skills from eduhub.png` | 120,886 | A1_rel_from_root_pct20: README.md:839 |
| `assets/figs/web-1.4.6+/memory/00-overview.png` | 292,118 | A1_rel_from_root: README.md:850 |
| `assets/figs/web-1.4.6+/memory/01-3 layer memory graph.png` | 2,625,008 | A1_rel_from_root_pct20: README.md:856 |
| `assets/figs/web-1.4.6+/myagents/00-overview.png` | 206,288 | A1_rel_from_root: README.md:724 |
| `assets/figs/web-1.4.6+/partners/00-partners overview.png` | 144,424 | A1_rel_from_root_pct20: README.md:699 |
| `assets/figs/web-1.4.6+/partners/02-IM config for each partner.png` | 262,122 | A1_rel_from_root_pct20: README.md:711 |
| `assets/figs/web-1.4.6+/settings/00-setting overview.png` | 221,518 | A1_rel_from_root_pct20: README.md:867 |
| `assets/figs/web-1.4.6+/settings/01-appearance settings.png` | 322,780 | A1_rel_from_root_pct20: README.md:880 |
| `assets/figs/web-1.6.5/OVERVIEW.png` | 125,011 | A1_rel_from_root: README.md:658 |
| `web/public/agent-icons/README.md` | 959 | B3_web_public_rel: web/components/agents/agent-icons.tsx:131 |
| `web/public/agent-icons/deepseek-harness.svg` | 3,721 | B1_public_url: web/components/agents/agent-icons.tsx:201 \| C_basename_unique: web/tests/subagent-harnesses.test.ts:56 |
| `web/public/agent-icons/hermes.svg` | 3,619 | B1_public_url: web/components/agents/agent-icons.tsx:184 \| C_basename_unique: web/tests/subagent-harnesses.test.ts:54 |
| `web/public/agent-icons/kimi.svg` | 15,560 | B1_public_url: web/components/agents/agent-icons.tsx:134 \| C_basename_unique: web/tests/subagent-harnesses.test.ts:51 |
| `web/public/agent-icons/mimo-code.svg` | 6,875 | B1_public_url: web/components/agents/agent-icons.tsx:151 \| C_basename_unique: web/tests/subagent-harnesses.test.ts:53 |
| `web/public/agent-icons/openclaw.svg` | 2,163 | B1_public_url: web/components/agents/agent-icons.tsx:191 \| C_basename_unique: web/tests/subagent-harnesses.test.ts:55 |
| `web/public/agent-icons/opencode.svg` | 613 | B1_public_url: web/components/agents/agent-icons.tsx:141 \| C_basename_unique: web/tests/subagent-harnesses.test.ts:52 |
| `web/public/apple-touch-icon.png` | 30,381 | B1_public_url: web/app/layout.tsx:34 \| B1_public_url: web/tests/proxy-policy.test.ts:110 |
| `web/public/banner.png` | 152,099 | B1_public_url: web/components/layout/AppShell.tsx:122 \| B1_public_url: web/components/sidebar/SidebarShell.tsx:268 \| B1_public_url: web/tests/proxy-policy.test.ts:108 |
| `web/public/favicon-16x16.png` | 1,547 | B1_public_url: web/app/layout.tsx:31 |
| `web/public/favicon-32x32.png` | 3,037 | B1_public_url: web/app/layout.tsx:32 \| B1_public_url: web/tests/proxy-policy.test.ts:119 |
| `web/public/knowledge-engine-icons/graphrag.png` | 1,669 | B1_public_url: web/components/knowledge/KnowledgeEngineIcon.tsx:14 |
| `web/public/knowledge-engine-icons/lightrag.jpg` | 25,782 | B1_public_url: web/components/knowledge/KnowledgeEngineIcon.tsx:15,16 |
| `web/public/knowledge-engine-icons/llamaindex.png` | 26,321 | B1_public_url: web/components/knowledge/KnowledgeEngineIcon.tsx:11 |
| `web/public/knowledge-engine-icons/marginnote.png` | 46,833 | B1_public_url: web/components/knowledge/KnowledgeEngineIcon.tsx:19 |
| `web/public/knowledge-engine-icons/obsidian.svg` | 4,821 | B1_public_url: web/components/knowledge/KnowledgeEngineIcon.tsx:18 |
| `web/public/knowledge-engine-icons/pageindex.png` | 9,595 | B1_public_url: web/components/knowledge/KnowledgeEngineIcon.tsx:12,13 |
| `web/public/knowledge-engine-icons/tencent-ima.svg` | 3,064 | B1_public_url: web/components/knowledge/KnowledgeEngineIcon.tsx:17 |
| `web/public/logo-ver2.png` | 109,768 | B1_public_url: web/app/(workspace)/co-writer/sampleTemplate.ts:109 |
| `web/public/logo.png` | 203,702 | B1_public_url: web/components/layout/AppShell.tsx:115 \| B1_public_url: web/components/sidebar/SidebarShell.tsx:197,261 \| B1_public_url: web/proxy.ts:104 \| B1_public_url: web/tests/proxy-policy.test.ts:37,107 \| B2_public_rel: deeptutor/skills/builtin/pptx/SKILL.md:96 \| B2_public_rel: tests/services/skill/test_skill_hub.py:143,145 |
| `web/public/logo_black.png` | 197,681 | B1_public_url: web/components/chat/home/SessionLoadingView.tsx:62 \| B1_public_url: web/features/chat/components/ChatWorkspace.tsx:2571 \| B1_public_url: web/tests/proxy-policy.test.ts:109 |
| `web/public/provider-icons/aihubmix-color.svg` | 1,442 | C_basename_unique: web/components/common/ProviderIcon.tsx:19 |
| `web/public/provider-icons/anthropic.svg` | 369 | C_basename_unique: web/components/common/ProviderIcon.tsx:15,16 |
| `web/public/provider-icons/azure-color.svg` | 1,622 | C_basename_unique: web/components/common/ProviderIcon.tsx:17 |
| `web/public/provider-icons/baidu-color.svg` | 1,385 | C_basename_unique: web/components/common/ProviderIcon.tsx:58 |
| `web/public/provider-icons/baiducloud-color.svg` | 718 | C_basename_unique: web/components/common/ProviderIcon.tsx:43 |
| `web/public/provider-icons/brave.svg` | 2,130 | C_basename_unique: web/components/common/ProviderIcon.tsx:55 |
| `web/public/provider-icons/bytedance-color.svg` | 954 | C_basename_unique: web/components/common/ProviderIcon.tsx:23,24 |
| `web/public/provider-icons/cohere-color.svg` | 770 | C_basename_unique: web/components/common/ProviderIcon.tsx:44 |
| `web/public/provider-icons/deepseek-color.svg` | 2,165 | C_basename_unique: web/components/common/ProviderIcon.tsx:26 |
| `web/public/provider-icons/duckduckgo.svg` | 2,679 | C_basename_unique: web/components/common/ProviderIcon.tsx:56 |
| `web/public/provider-icons/exa-color.svg` | 403 | C_basename_unique: web/components/common/ProviderIcon.tsx:54 |
| `web/public/provider-icons/gemini-color.svg` | 2,837 | C_basename_unique: web/components/common/ProviderIcon.tsx:27,28 |
| `web/public/provider-icons/githubcopilot.svg` | 2,020 | C_basename_unique: web/components/common/ProviderIcon.tsx:25 |
| `web/public/provider-icons/groq.svg` | 569 | C_basename_unique: web/components/common/ProviderIcon.tsx:42 |
| `web/public/provider-icons/jina.svg` | 405 | C_basename_unique: web/components/common/ProviderIcon.tsx:45 |
| `web/public/provider-icons/lmstudio.svg` | 1,254 | C_basename_unique: web/components/common/ProviderIcon.tsx:40 |
| `web/public/provider-icons/minimax-color.svg` | 1,571 | C_basename_unique: web/components/common/ProviderIcon.tsx:33,34 |
| `web/public/provider-icons/mistral-color.svg` | 656 | C_basename_unique: web/components/common/ProviderIcon.tsx:35 |
| `web/public/provider-icons/moonshot.svg` | 4,029 | C_basename_unique: web/components/common/ProviderIcon.tsx:32 |
| `web/public/provider-icons/nvidia-color.svg` | 1,026 | C_basename_unique: web/components/common/ProviderIcon.tsx:41 |
| `web/public/provider-icons/ollama.svg` | 3,291 | C_basename_unique: web/components/common/ProviderIcon.tsx:39 |
| `web/public/provider-icons/openai.svg` | 1,688 | B1_public_url: web/tests/proxy-policy.test.ts:111 \| C_basename_unique: web/components/common/ProviderIcon.tsx:13,14 |
| `web/public/provider-icons/openrouter.svg` | 907 | C_basename_unique: web/components/common/ProviderIcon.tsx:18 |
| `web/public/provider-icons/perplexity-color.svg` | 604 | C_basename_unique: web/components/common/ProviderIcon.tsx:53 |
| `web/public/provider-icons/qwen-color.svg` | 2,045 | C_basename_unique: web/components/common/ProviderIcon.tsx:30,31,61 |
| `web/public/provider-icons/searxng.svg` | 592 | C_basename_unique: web/components/common/ProviderIcon.tsx:57 |
| `web/public/provider-icons/siliconcloud-color.svg` | 521 | C_basename_unique: web/components/common/ProviderIcon.tsx:20 |
| `web/public/provider-icons/stepfun-color.svg` | 677 | C_basename_unique: web/components/common/ProviderIcon.tsx:36 |
| `web/public/provider-icons/tavily-color.svg` | 1,093 | C_basename_unique: web/components/common/ProviderIcon.tsx:52 |
| `web/public/provider-icons/vllm-color.svg` | 287 | C_basename_unique: web/components/common/ProviderIcon.tsx:38 |
| `web/public/provider-icons/volcengine-color.svg` | 859 | C_basename_unique: web/components/common/ProviderIcon.tsx:21,22,60 |
| `web/public/provider-icons/xiaomimimo.svg` | 2,545 | C_basename_unique: web/components/common/ProviderIcon.tsx:37 |
| `web/public/provider-icons/zhipu-color.svg` | 3,598 | C_basename_unique: web/components/common/ProviderIcon.tsx:29 |


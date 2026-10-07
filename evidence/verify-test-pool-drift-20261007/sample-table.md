# 抽样复核：补测卡（test-*）零/弱覆盖声明 — 20261007

- 基准清单：myfork 分支 `scan/coverage-gaps-20261007` 的 `evidence/coverage-gaps-20261007/summary.json`（root_commit `f07029cfc` = 本次复核基线 origin/main，即 v1.6.13；清单与当前树零漂移）。
- 抽样：18 张老卡（deeptour.auto.jsonl 文件序靠前的 test-* 卡），17 张引用 Python 模块、1 张引用前端组件。
- 三态判定口径：
  - **仍零覆盖**：模块仍在 20261007 zero 清单，或仍无专属测试（声明成立）；
  - **已补测试**：模块已有专属测试（weak 清单含测试，或树内存在直接测试文件），卡的零/弱前提部分或全部失效；
  - **模块移位**：模块路径在当前树不存在。
- 树内核对仅读文件与 `rg`/`glob`，未运行测试、未改产品代码。

| # | 卡 key | 引用模块 | 卡内声明 | 20261007 清单状态 | 树内测试证据 | 三态结论 |
|---|--------|----------|----------|-------------------|--------------|----------|
| 1 | test-knowledge-router | deeptutor/api/routers/knowledge.py | 758 缺失 / 68.0%（DT-21 Top15 #1） | 非 zero、非 weak（≥2 测试文件） | tests/api/test_knowledge_router.py、test_knowledge_progress_ws.py、test_knowledge_zip_upload.py | 已补测试 |
| 2 | test-quiz-judge | deeptutor/api/routers/quiz_judge.py | 192 缺失 / 9.4%（DT-21 Top15 #3） | 非 zero（间接执行）、非 weak（0 个专属测试文件） | tests/ 下无专属单测，仅 i18n 字符串测试引用 | 仍零覆盖（声明成立） |
| 3 | test-citation-manager | deeptutor/agents/research/utils/citation_manager.py | 264 缺失 / 37.0%（DT-21 Top15 #4） | 非 zero、非 weak | tests/agents/research/test_citation_manager.py 直接测 CitationManager payload 归一化，与卡要求场景一致 | 已补测试 |
| 4 | test-book-engine | deeptutor/book/engine.py | 506 缺失 / 46.5%（DT-21 Top15 #6） | 非 zero、非 weak | tests/book/test_engine_controls.py、test_engine_language.py | 已补测试 |
| 5 | test-research-pipeline | deeptutor/agents/research/pipeline.py | 408 缺失 / 62.6%（缺口 7） | 非 zero、非 weak | tests/agents/research/test_pipeline_partial_failure.py；另有开放 PR 分支 test/research-pipeline-stage-contract-pr（卡已被领取执行） | 已补测试 |
| 6 | test-kb-manager | deeptutor/knowledge/manager.py | 329 缺失 / 73.7%（缺口 8） | 非 zero、非 weak | tests/knowledge/test_manager_delete.py、test_manager_embedding_flags.py、test_manager_get_info_status.py、test_manager_list.py（共 4 个） | 已补测试 |
| 7 | test-feishu-channel | deeptutor/partners/channels/feishu.py | 495 缺失 / 55.5%（缺口 9） | 非 zero、非 weak | tests/services/partners/test_feishu_*.py 共 8 个 | 已补测试 |
| 8 | test-reading-progress | deeptutor/api/routers/reading.py | 279 缺失 / 66.9%（缺口 11） | 非 zero、非 weak（reading 子包 zero=0） | tests/reading/test_router.py、test_quiz.py、tests/api/test_reading_quiz_answers.py 等 | 已补测试 |
| 9 | test-pocketbase-store | deeptutor/services/session/pocketbase_store.py | 225 缺失 / 72.6%（缺口 13） | 非 zero、非 weak | tests/services/session/test_pocketbase_isolation.py、tests/services/workspace/test_pocketbase_scope.py | 已补测试 |
| 10 | test-question-pipeline | deeptutor/agents/question/pipeline.py | 283 缺失 / 65.6%（缺口 15） | 非 zero、非 weak | tests/agents/question/test_pipeline.py | 已补测试 |
| 11 | test-quiz-viewer | web/components/quiz/QuizViewer.tsx | 366 缺失 / 0%（备选 16，前端） | 20261007 清单为 Python 域，不覆盖前端；按树内核对 | web/tests/quiz-autoscroll.test.ts、quiz-option-latex.test.ts、quiz-image-answer.test.ts 均引用 QuizViewer | 已补测试（清单外，按树判定） |
| 12 | test-telegram-channel | deeptutor/partners/channels/telegram.py | 418 缺失 / 30.2%（备选 17） | 非 zero、非 weak | tests/services/partners/test_telegram_channel.py、test_telegram_markdown_html.py | 已补测试 |
| 13 | test-launcher-lifecycle | deeptutor/runtime/launcher.py | 295 缺失 / 66.7%（备选 18） | 非 zero、非 weak | tests/runtime/test_launcher.py、test_launcher_allocator_env.py | 已补测试 |
| 14 | test-co-writer | deeptutor/api/routers/co_writer.py | 246 缺失 / 40.0%（备选 20） | weak（tests/api/test_co_writer.py） | 同左 | 已补测试（仍弱，卡可改窄而非下架） |
| 15 | test-read-aloud | deeptutor/reading/read_aloud.py | 缺直接单测（#1654 铺底） | 非 zero、非 weak | tests/reading/test_read_aloud.py、tests/services/test_minimax_voice.py 等 | 已补测试 |
| 16 | test-epub-bilingual | deeptutor/reading/epub_bilingual.py | 缺直接单测（#860/#1447 铺底） | weak（tests/reading/test_epub_bilingual.py） | 同左 | 已补测试（仍弱，卡可改窄而非下架） |
| 17 | test-tex-tools | deeptutor/tools/tex_downloader.py、tex_chunker.py | 无任何测试（DT-22 §4） | **两模块均在 20261007 zero 清单** | tests/tools/ 无 tex 相关测试 | 仍零覆盖（声明成立） |
| 18 | test-docx-converter | deeptutor/co_writer/docx_converter.py | 3 处静默吞错（DT-22 MEDIUM） | weak（tests/api/test_co_writer.py） | 同左；卡点名的 3 个边界分支未被专属测试覆盖 | 已补测试（弱；边界场景前提未被清单证伪，建议改窄复核） |

## 三态计数

- 仍零覆盖（声明成立）：2（test-quiz-judge、test-tex-tools）
- 已补测试：16（其中 3 张模块仍处 weak 单测试文件态：test-co-writer、test-epub-bilingual、test-docx-converter）
- 模块移位：0

## 建议下架清单（≤5，前提已明显失效）

1. **test-research-pipeline** — 已有 test_pipeline_partial_failure.py，且开放 PR 分支 test/research-pipeline-stage-contract-pr 表明该卡已被领取执行。
2. **test-kb-manager** — manager.py 已有 4 个专属测试文件，增删查边界已覆盖。
3. **test-feishu-channel** — feishu.py 已有 8 个专属测试文件，解析/回复路由已覆盖。
4. **test-read-aloud** — read_aloud.py 已有直接单测 tests/reading/test_read_aloud.py。
5. **test-citation-manager** — 已有 test_citation_manager.py，与卡要求的 payload 容错场景一致。

不列入下架但建议改窄：test-co-writer、test-epub-bilingual、test-docx-converter（模块仅 1 个测试文件、仍属 weak，卡的边界场景仍有残余价值）；保留：test-quiz-judge、test-tex-tools（声明仍成立）。

## 复核方法备注

- 清单归属：weak_top100 含 242 个单测试文件模块的前 100（按 LOC）；"非 weak" 仅表示未进前 100，配合树内专属测试文件数 ≥2 佐证已脱离弱态。
- test-quiz-judge 说明：quiz_judge.py 声称 9.4% 行覆盖（间接执行），故不在 zero 清单；但 tests/ 无任何专属单测，"192 缺失、需补单测" 的前提在 20261007 下仍成立，判 仍零覆盖（声明成立）。
- 抽样表与本说明同目录 `SHA256SUMS` 为完整性校验。

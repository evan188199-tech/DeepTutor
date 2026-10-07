# guide-reading（docs/guides/immersive-reading.md @ 787ddd799）逐结论复核

- 基线漂移：`ef2d9e5c3`（v1.6.12）→ `f07029cfc`（v1.6.13）
- 判定：仍成立 / 漂移（本体成立、行号或数字过期）/ 失效（被 v1.6.13 推翻）

| # | 导读结论（节） | 判定 | 依据（新基线 path:line） |
|---|---|---|---|
| 1 | §一/§二 模块定位与入口（reading 引擎四层、locator 抽象、REST 挂载 `main.py:644/646`、上传/URL 导入、能力注册、回合接线） | 仍成立 | `reading/__init__.py`、`capabilities/reading/*`、`api/main.py` 均未动；`routers/reading.py` 锚点 +7（`upload_material :1031`→`:1038`、`import-urls :537`→`:544`），内容逐字保留 |
| 2 | §3.1 摄入：一次切分永久寻址、material_id=内容哈希幂等、reuse=false、EPUB 升级冲突、URL/媒体状态机 | 仍成立 | `store.py` 锚点保留（哈希 `:283`→`:283`、幂等 `:291-299` 逐字同、`ReadingUpgradeConflict :300`→`:300`）；`ingestion.py`、`catalog_store.py`、`catalog_models.py` 未动 |
| 3 | §3.2/§3.3 阅读回合与前端渲染（mode/loop 分工、kwargs 注入、locate 预检、reader_action 通道、ReaderPane 分流） | 仍成立 | `capabilities/reading/capability.py`、`tools.py`、`_tool_base.py`、`mode.py`、`reading/service.py`、`search.py` 未动；web 组件行数漂移但对象在（`EpubDocumentView.tsx:162`→`:167`、`PdfDocumentView.tsx:69`→`:76`、`ReaderPane.tsx` 重排 +37） |
| 4 | §五 扩展点（新格式分支、扩展协议+熔断、reader_action 约定、SourceKind、双语） | 仍成立 | `reading/extensions.py`、`extract.py:145-160`、`catalog_models.py:16` 未动；`reading_extensions.py` 路由行 `:145`→`:195`（插入 read-aloud 端点所致），鉴权转发/超时结论不变（`:34/:35/:54`→`:36/:37/:56`） |
| 5 | §六 已知坑（locator 语义随格式、同字节同 id、模型不能自选材料、选区 untrusted、扩展熔断、refresh 串行、多用户访问闸、watching 并入中） | 仍成立 | 上述各锚点文件未动或行保留；`_turn_runtime_shared.py:599` 转义截断逐字未动（新增 `:1199-1262` LaTeX body 等价 grounding 为补充，不推翻）；`refresh.py:11` 未动；`SourceKind`/`ingestion.py` 未动（watching 未并入） |
| 6 | §六 EPUB"TOC 锚点/位置标注是上游在修的活跃 bug（#1673，PR #1686 open）" | **失效（部分：锚点修复已落地 v1.6.13）** | `OutlineEntry.source_href/source_anchor`（`reading/models.py:139-140,148-166`）；存量自动升级 `_upgrade_epub_outline`（`reading/store.py:943-996`）；spine 锚点解析增强（`utils/document_extractor.py:922`→`:949` 起，+41 行）；`EpubDocumentView.tsx` +48 行锚点导航。"EPUB 无忠实原文视图"半句仍成立（仍仅 PDF 有 RAW 视图，`extract.py:67`） |
| 7 | §四 关键文件表（20 个文件行数 + 51 路由数） | 漂移 | 6/20 行数过期：extract.py 579→598、store.py 1516→1566、models.py 523→538、routers/reading.py 1559→1570（`@router.` 计数 51→51 不变）、reading_extensions.py 414→498、ReaderPane.tsx 1343→1380；其余 14 个精确不变 |
| 8 | §七 测试与覆盖空白（402 passed / 25 测试文件 / 325 函数；空白 1-5） | 漂移（主体成立） | 新基线复跑 `pytest tests/reading` = **415 passed, 0 failed（5.61s）**（`pytest-reading.txt`）；测试文件 26（含 conftest）不变；覆盖空白逐条：#1 refresh.py 无测试仍成立（无新增 refresh 测试）、#5 EpubDocumentView vitest 缺位仍成立（新增 spec 为 pdf-resize/read-aloud/source-navigator，非 locator 同步专项）；#1673 相关空白因锚点落地而部分收敛 |
| 9 | §八 相关上游（#1641/#1673/PR#1686、#1378→PR#1384、#1654、#1656 等开合状态） | 不复核（去重） | 上游 PR 状态归 verify-consumed-pr-state 轴；仅记录代码面证据：#1654 朗读（服务端 TTS 端点 + `web/components/reading/use-read-aloud-speech.ts` +94）与 #1673 锚点已在 main 落地，供该卡复核时参考 |

小结：复核 8 项主要结论 = 仍成立 5 / 漂移 2 / 失效 1（部分）；§八上游状态 1 项归 verify-consumed-pr-state 轴不复核。锚点 104 个 = 未动 79 / 平移 25 / 失效 0（全部旧行原文逐字保留，平移 +2～+69）。修订导读时需改写 §六 EPUB TOC 条目、刷新 §四 行数表与 §七 计数，并可在 §八 补记 #1654/#1673 落地事实。

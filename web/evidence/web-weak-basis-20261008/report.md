# web weak 清单 basis 复核与精修（web-test-gaps-20261007 weak 侧）

- 日期：2026-10-08
- 复核对象：`scan/web-test-gaps-20261007` 的 `summary.json` 中 weak 73 条（四类依据：仅 meta / 仅 basename / 仅 barrel / 仅 audit）
- 基线树：scan 依据核对用 `myfork/scan/web-test-gaps-20261007`（50ce62f7e，v1.6.13+evidence）；现状核对用 `origin/main` 6cf793bd8（v1.6.14）
- 只读复核：未改动任何代码；产物仅本 evidence 目录

## 一、结论摘要

| 项目 | 数值 |
|---|---|
| 复核 weak 条目 | 73（100% 逐条复核） |
| 引用真实性（测试引用 60 条 + barrel 引用 13 条） | 测试引用 60/60 真实；barrel 引用 5/13 真实、8/13 为误报 |
| 误报剔除（→zero 侧） | 30 |
| main 上已 covered 移出 | 1（components/chat/preview/FilePreviewDrawer.tsx，ChatWorkspace.smoke.spec.tsx 按路径引用） |
| 精修后 weak 清单 | 42（可直接作下一轮拆卡输入，见 refined_weak.json） |
| Top20 复测种子 | 见 top20_retest_seeds.json |

局限修正：
- #2（barrel 深度）：13 条 barrel 依据逐条核对导出链——5 条真实（具名再导出 depth=1，barrel 均被行为测试路径覆盖）；8 条误报（最近 barrel 根本不导出该模块，全祖先链亦无），应回落 zero 侧。另发现反向盲区：11 条 basename 依据实为“测试经 barrel 导入后行为测试该模块”（depth=1 具名再导出已验证），静态路径规则不可见。
- #3（basename 误报）：系统性词撞机制确认并逐条剔除，主要机制见第四节；共剔除 basename 词撞误报 21 条、barrel 误引 8 条、shim 伪模块 4 条（其中部分同时命中多机制）。

## 二、方法与抽样比例

- 抽样比例：73/73（100%）逐条复核；其中 basename 类 55 条逐条读命中行人工判定，barrel 类 13 条逐条解析导出语句，meta 类 5 条核对路径子串。
- 每条判定依据：重放原扫描判定逻辑（已验证可在 scan 树字节级复现原 weak 清单）→ 逐条核对 summary.json 所列引用文件存在性与命中类型（路径子串 vs 词边界）→ 对 basename-only 命中提取测试文件全部 import/export/require/vi.mock 说明符并解析落点 → 对 barrel 引用解析 barrel 的具名/star 再导出链（深度至 8）→ 与 `origin/main` 全量重扫对比（901 源文件 / 349 zero / 73 weak / 479 covered）。
- 逐条机器证据：verification.json（含每条命中行号与文本、说明符解析落点、barrel 链深度、main 状态）。

## 三、局限 #2 修正：barrel 深度

原报告只查最近一层 index.ts(x) 是否 covered，未验证 barrel 是否真的再导出该模块，也未发现“经 barrel 导入的行为覆盖”。本卡对 13 条 barrel 依据全链核对：

真实（5 条，保留 weak，间接可达）：
| 模块 | barrel | 导出方式 | barrel 覆盖测试 |
|---|---|---|---|
| components/space/question-bank/CategoryMenu.tsx | question-bank/index.ts | 具名 depth1 | practice-entrypoints/question-bank-tooltips 等 |
| features/runtime-status/useRuntimeStatus.ts | runtime-status/index.ts | 具名 depth1 | runtime-health.spec、runtime-status.test |
| i18n/I18nClientBridge.tsx | i18n/index.ts | 具名 depth1 | 约 100 条行为 spec |
| i18n/I18nProvider.tsx | i18n/index.ts | 具名 depth1 | 同上 |
| shared/ui/Skeleton.tsx | shared/ui/index.ts | 具名 depth1 | ui-primitives.spec、tooltip.spec 等 |

误报（8 条，剔除→zero）：BankScopeRail、BankSelectionBar、BankToolbar（question-bank/index.ts 只导出 QuestionBankSection/CategoryMenu/useQuestionBank）；ActivityOrb（trace/index.ts 只导出 model/selectors/TracePresentation，chat/index.ts 不转发 trace）；agent-store、claude-code（chat-import/index.ts 不导出）；shared/ui/activity-state、tooltip-position（shared/ui/index.ts 不导出）。

新增发现（#2 的另一面）：11 条 basename 依据实为 barrel 行为覆盖——测试经 `@/shared/ui`、`@/features/runtime-status`、`@/features/chat/components/turn`、`@/components/space/question-bank` 导入并渲染/断言这些模块（具名再导出 depth=1 已逐条验证）。其中 7 条 shared/ui 原语对应已 DONE 的 test-web-shared-ui-primitives 卡。这 11 条保留 weak（静态规则意义）但拆卡优先级最低，建议下一轮扫描把“测试说明符解析到 covered barrel 且链可达”的条目标记为 `barrel-covered-indirect`。

## 四、局限 #3 修正：basename 误报机制

确认五类误报机制（行级证据见 verification.json）：
1. **泛英文词撞**：`api`（4 条 api.ts，各 121 条命中全为 lib/api.ts 导入、/api/ URL、admin-api 等）、`types`（2 条）、`shared`（2 条）、`labels`、`mentions`、`surfaces`、`outline`、`model`、`styles`、`streaming`（23 条 chat 流式语义）、`runtime`、`detect`、`attribution`（test 标题词）。同名 basename 条目的命中计数完全相同（如 4 条 api.ts 均为 meta=4/node=46/playwright=10/vitest=65），是该机制的指纹。
2. **同名异模块导入**：api-auth-redirect 等导入 `../lib/api`；usage-statistics 导入 `components/settings/shared.tsx`；smoke.spec 导入 `components/ui/Button`（非 shared/ui/Button）。
3. **同名异模块符号**：reading-inline-markdown.test 导入 lib/reading-inline-markdown 的 `InlineMarkdown` 符号，而非 components/common/InlineMarkdown.tsx。
4. **1 行 re-export shim**：engines/ 下 GraphRagForm/ImaForm/LightRagForm/LlamaIndexForm 均为 `export { X } from "./EngineDetail"` 的 1 行别名文件，实现在 EngineDetail.tsx（已 covered），shim 无补测价值。
5. **指向他模块的渲染/源码断言**：space/learning/ConfirmDialog 的 3 条命中实指 components/ui/ConfirmDialog（guardian 页经 GuardianRelationshipsEditor 渲染 ui 版；watching 测试读 WatchingPane 源码）。

保留为真实的 basename 引用形态（修正后 basis）：readWebFile 分段路径读源码（guardian-api、MemoryUsageItem、SettingsNav、ConnectedAgents、agent-icons——扫描器路径匹配盲区）、否定断言（LightRagIndexingProvenance、ReadingFolder）、渲染标记断言（SaveToNotebookModal、ui/ConfirmDialog、Modal、Toggle、SettingsAccessProvider）、vi.mock barrel 键名（QuestionBankSection）、源码调用断言（co-writer hooks ×4）、源码文件名清单（SettingsOverview、GuardianSettingsSection、GuardianRelationshipsEditor）。

## 五、剔除清单（31 条）

- barrel 误引（8）：BankScopeRail.tsx、BankSelectionBar.tsx、BankToolbar.tsx、ActivityOrb.tsx、lib/chat-import/agent-store.ts、lib/chat-import/claude-code.ts、shared/ui/activity-state.ts、shared/ui/tooltip-position.ts
- 泛词撞（12）：features/capabilities/api.ts、features/multi-user/api.ts、features/runtime-status/api.ts、components/activity/types.ts、features/multi-user/types.ts、components/learning/surfaces.ts、components/partners/group/outline.ts、components/partners/group/labels.ts、components/partners/group/mentions.ts、components/mcp/styles.ts、lib/chat-import/streaming.ts、shared/api/runtime.ts
- 词撞+其他（6）：features/chat/trace/model.ts、lib/chat-import/attribution.ts、lib/chat-import/detect.ts、components/common/InlineMarkdown.tsx、components/space/learning/ConfirmDialog.tsx、components/reading/library/shared.tsx
- shim 伪模块（4）：engines/GraphRagForm.tsx、engines/ImaForm.tsx、engines/LightRagForm.tsx、engines/LlamaIndexForm.tsx
- main 已 covered（1）：components/chat/preview/FilePreviewDrawer.tsx

注：agent-store/attribution/detect/streaming 存在运行时父（MyAgentsPicker、ImportWizard、index.ts parseSessions 内部使用、claude-code.ts），静态无测试路径引用，归 zero 侧；claude-code.ts 归属已 DONE 的 test-web-chat-import-claude-code 卡，本卡仅修正 weak 依据误报，不改变该卡结论。

## 六、精修 weak 清单（42 条，refined_weak.json）

| 组 | 条数 | 条目 | 拆卡建议 |
|---|---|---|---|
| meta 引用真实 | 4 | ThemeScript.tsx、eslint.config.mjs(non-actionable)、scripts/i18n_audit.mjs、scripts/typecheck.mjs | 工具/结构性，低优先 |
| barrel 间接可达（依据真实） | 5 | CategoryMenu、useRuntimeStatus、I18nClientBridge、I18nProvider、Skeleton | 可拆；按 barrel 直测或直测模块 |
| barrel 行为已覆盖（低优先） | 11 | QuestionBankSection、ProtocolMismatchNotice、RuntimeHealthCard、TurnCoordinationSettings、Button、Dialog、EmptyState、Field、IconButton、InlineAlert、StatusChip | 不建议拆卡（已有行为覆盖，含已 DONE 的 shared-ui-primitives 卡） |
| barrel 具名再导出（词撞修正后归此） | 2 | lib/chat-import/shared.ts、shared/ui/styles.ts | 可拆 |
| 结构性引用真实 | 20 | guardian-api、ConnectedAgents、agent-icons、Modal、LightRagIndexingProvenance、SaveToNotebookModal、ReadingFolder、MemoryUsageItem、SettingsNav、SettingsOverview、Toggle、ui/ConfirmDialog、GuardianRelationshipsEditor、SettingsAccessProvider、GuardianSettingsSection、co-writer hooks ×4、PdfPage | 主力拆卡池；注意多为“仅结构性”，行为测试仍是空缺 |

## 七、Top20 复测种子（top20_retest_seeds.json）

评分沿用原扫描权重（类别权 × log10(loc+10)），剔除已有行为覆盖与运行时可达条目后排序，前 5：
1. lib/guardian-api.ts（11.43，lib，readWebFile 结构读）
2. lib/chat-import/shared.ts（8.85，barrel 具名再导出，间接）
3. features/settings/sections/GuardianSettingsSection.tsx（8.04，结构性）
4. features/multi-user/components/GuardianRelationshipsEditor.tsx（7.62，结构性）
5. features/runtime-status/useRuntimeStatus.ts（6.31，barrel 间接可达）

## 八、剩余局限

1. 静态映射 ≠ 运行时覆盖率，本卡不执行测试；“保留 weak”仅指引用依据真实。
2. barrel 链核对限于祖先 index.ts(x) 全链 + 具名/star 再导出解析（深度≤8）；跨目录非常规再导出（如兄弟目录 barrel 相对导入）未枚举，极端情况仍可能漏判。
3. 说明符解析支持 `@/` 别名与相对路径；动态模板字符串导入不可静态解析（本卡 73 条未出现此类引用）。
4. 精修清单基于 origin/main 6cf793bd8；后续合入会移动 covered/weak 边界（本卡已示范 1 条）。

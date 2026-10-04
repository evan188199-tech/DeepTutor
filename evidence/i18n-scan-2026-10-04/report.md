# web 端 i18n 扫描报告（en/zh 缺键与硬编码文案）

- 扫描对象：`HKUDS/DeepTutor` `origin/main` @ `ef2d9e5c3`（release v1.6.12），只读扫描，未改任何代码
- 范围：`web/`（Next.js 前端），locale 文件 `web/locales/{en,zh,fr,de,uk}/`，`t()` 调用点覆盖 `web/{app,components,context,features,hooks,i18n,lib,shared}`
- 方法：脚本 `scan_i18n.py`（本目录，附原始输出 `scan_raw.txt`）。要点：`web/i18n/init.ts` 配置 `keySeparator: false` + `defaultNS: "app"`，键是整串英文文本本身（en 中 4831/5272 个键值相同，即"英文即键"），翻译差异全部体现在 zh 等语言包里
- 日期：2026-10-04

## 结论摘要（跑通：PASS）

| 维度 | 结果 |
| --- | --- |
| en/zh 键集差异 | **0**（app.json 5272=5272，common.json 37=37，完全同步） |
| 引用不存在的键 | 静态 `t()` 5609 处，未命中 2 处（0.04%）；11 个动态键前缀族全部有对应键 |
| 硬编码 CJK 文案 | 129 行需人工分类，其中**真实可见缺陷约 3 组**（详见清单三） |
| 硬编码英文用户可见文案 | setError/属性两条子扫描共约 7 处真实命中 |

总体：en/zh 同步状况良好，主要风险不在缺键，而在**绕过 locale 体系的硬编码与平行 i18n 机制**。

## 清单一：en/zh 键集差异

无键集差异。value 级异常 3 项：

| # | 位置 | 问题 | 影响面 | 等级 |
| --- | --- | --- | --- | --- |
| 1-1 | `web/locales/zh/app.json`（键 `s`） | zh 值为空串；`returnEmptyString:false` 使其回退到 en 值 `"s"`，两种语言都显示裸字符 `s` | 疑似孤儿键：无静态 `t("s")` 调用点，来源疑似 `components/learning/practice/PracticeInsights.tsx:191,198` 的动态 `t(metric.label)` 或旧复数键残留。出现时 zh/en 界面均显示 "s" | 中 |
| 1-2 | `web/locales/app.json` 键 `“{{title}}”…stay in your library._one` | en `_one` 分支无 `{{count}}` 占位符、zh `_one` 分支有（且 zh 文案带 count 语义） | zh 走 CLDR 只有 `other` 分支，实际不生效；纯维护噪音 | 低 |
| 1-3 | 68 个 zh 值与 en 完全相同 | 全量清单见 `zh_untranslated_echo.txt`；绝大多数是专有名词/URL（GitHub、MCP、L1/L2/L3 等，合理），约 15 个是真实未译 UI 词（User prompt、Base URL、API Key、Client ID、OK、tokens、Leader、Worker ID、main 等） | zh 用户在设置/知识库/内存面板看到零星英文 | 低 |

附带（超出 en/zh 范围，记录备查）：

- `web/locales/fr/app.json` 与 en 漂移：fr 多 909 个死键、缺 466 个 en 键 → fr 用户 466 处回退英文（`web/i18n/init.ts` fallbackLng=en）。
- `web/locales/uk/` 缺 `common.json`（en/zh/fr/de 均有 37 键的 common.json）。
- `common.json` 是**死命名空间**：`init.ts` 只注册 `app` 命名空间，37 个 common 键 100% 重复存在于各语言 app.json 中，全仓仅 `web/tests/workspace-i18n.spec.ts:3` 引用。建议删除或明确用途。

## 清单二：引用了不存在的键（t() → 无 en 键）

| # | 位置 | 内容 | 影响面 | 等级 |
| --- | --- | --- | --- | --- |
| 2-1 | `web/components/courses/CourseSyllabus.tsx:164` | `t("One unit per line. Add keywords after a \| …")`（课程大纲 textarea 的 placeholder，多行示例文案） | 键不在任何语言包 → i18next 返回键本身，**en/zh/fr/de/uk 全部用户**在 Courses 大纲编辑器看到英文长文案；zh 界面中英混杂。zh 翻译也缺 | 高 |
| 2-2 | `web/components/partners/SoulEditor.tsx:75` | `t("# Soul\nDescribe who this partner is, how it speaks, what it values…")`（Soul 编辑器默认 placeholder） | 同上：全部语言显示英文；zh 用户在 Partner 编辑 Soul 弹窗看到英文提示 | 高 |

动态键前缀族（`t(\`前缀${变量}\`)`）11 个族全部有对应键，无空族（详见 `missing_keys_list.txt`）。

## 清单三：用户可见硬编码文案

完整原始清单：`cjk_hardcoded_list.txt`（129 行 C 类）、`cjk_other_list.txt`（268 行 A/B 类）、`jsx_english_list.txt`。

### 高——无条件显示中文（en/fr/de/uk 用户可见中文）

| # | 位置 | 内容 | 影响面 |
| --- | --- | --- | --- |
| 3-1 | `web/components/memory/MemorySection.tsx:152` | `SURFACE_META.quiz.label = "题库"`，在 `:805` SurfacePill、`:1065` EntityRow 无条件渲染 | 内存面板（chat/memory 图谱页）所有非 zh 语言显示"题库"，其余 7 个 surface 均是英文，明显混杂 |
| 3-2 | `web/components/memory/MemorySection.tsx:160-163` | `L3_LABELS`："近期总结/用户画像/知识 Scope/偏好"，经 `labelFor()`（`:202-203`）无条件渲染 | 同一页面 L3 文档标签全部非 zh 语言显示中文 |

### 高——setError/属性直出英文（zh 用户可见英文）

| # | 位置 | 内容 | 影响面 |
| --- | --- | --- | --- |
| 3-3 | `web/components/reading/ReaderPane.tsx:575`、`:594` | `setError("This citation points to an older material revision…")` | zh 用户在阅读器点旧版本引用时报英文错误条 |
| 3-4 | `web/components/settings/VoicePreviewPanel.tsx:94` | `setError('Voice preview was cancelled or timed out.')` | zh 用户在设置→语音预览超时/取消时报英文 |
| 3-5 | `web/components/knowledge/KbWebSourcesSection.tsx:65` | `setError("Timed out loading web sources. Click retry.")` | zh 用户在知识库 Web 源加载超时报英文 |
| 3-6 | `web/hooks/useVoiceRecorder.ts:37`、`:44` | `setError("Recording is not supported in this browser.")` / `"Microphone permission denied."` | zh 用户录音失败提示英文（语音入口多处复用该 hook） |
| 3-7 | `web/components/knowledge/LightRagRoleModelsEditor.tsx:141-142` | `label="LightRAG base model"`、`description="The default model when no role model is specified…"` 硬编码英文属性 | zh 用户在 LightRAG 角色模型编辑器看到英文标签/描述 |

### 中——平行 i18n 机制（`language === "zh" ? 中文 : 英文` 或 `tr(cn, en)` 局部闭包）

功能上 en/zh 双语可用，但绕过 locale 文件：fr/de/uk 用户永远看到英文；文案散落无法统一审校。合计约 100 行、12 个文件，清单见 `cjk_hardcoded_list.txt`。主要聚集：

- `web/features/settings/sections/DataMigrationSettingsSection.tsx`（49 行，`['英文','中文']` 数组对）
- `web/components/space/EduHubImportModal.tsx`（20 行，局部 `tr(cn, en)`，`:64` 定义）
- `web/hooks/useTopicSourceLibrary.ts`（9 行，`tr()`）
- `web/features/settings/sections/ToolsSettingsSection.tsx`（9 行，`zh ?`）
- `web/lib/tool-availability.ts:26-52`（5 处，工具不可用徽标/详情）
- 其余：`web/lib/workspaces-api.ts:142-143`、`web/components/chat/home/SubagentRunTranscript.tsx:179-182`、`web/features/settings/store/SettingsStore.tsx:416`、`web/components/settings/ModelCards.tsx:406`、`web/components/settings/ServiceConfigEditor.tsx:1329`、`web/components/settings/VoicePreviewPanel.tsx:46`

### 低——无需处理（防误报，列举归档）

- **语言名/协议/检测常量**（本就该双语或非文案）：语言下拉项"简体中文/繁體中文/日本語"（8 处，A 类）；`app/(workspace)/whisper/page.tsx:30,256`、`web/lib/whisper-transcript.ts:36-40`（服务端消息匹配/指令词）；`web/features/chat/components/ChatWorkspace.tsx:1930-1933`（quiz 占位 prompt 检测词表）；`web/lib/reading-citations.ts:96`、`web/lib/reading-inline-markdown.tsx:25`、`web/lib/markdown-display.ts:402`（引用/图片标记/参考文献标题正则，匹配生成侧输出）；`web/features/chat/trace/TracePresentation.tsx:1352-1358`（引言/结论/章节标签匹配）；`web/components/partners/group/mentions.ts:6`（@所有人 词表）；`web/components/settings/SettingsNav.tsx:37`（导航搜索中文关键词，故意增强搜索）；`web/components/settings/ModelCards.tsx` CJK 正则（`:544` CoWriterWorkspace 同类）
- `web/app/(utility)/avatar-preview/page.tsx:14-18`（工具页 demo 数据，5 行）
- `web/app/(workspace)/co-writer/sampleTemplate.ts:27,103`（示例模板内容，本来就该是英文样文）
- **疑似产品名 typo**：`t("Pro Vide Writing")`（`web/features/co-writer/components/CoWriterWorkspace.tsx:1794`），en/zh 值均为 "Pro Vide Writing"，疑为 "Pro Vibe/Video Writing"，需人确认后修键值。

## 风险分级汇总与可拆卡建议

| 等级 | 条目 | 建议拆卡 |
| --- | --- | --- |
| 高 | 2-1、2-2 缺键（en/zh 皆缺） | 1 张补测+修复卡：把两条文案补进 en/zh（zh 需翻译），可附 `web/tests/workspace-i18n.spec.ts` 断言 |
| 高 | 3-1、3-2 MemorySection 中文硬编码 | 1 张修复卡：label 走 `t()`，补 en/zh 键 |
| 高 | 3-3~3-6 setError 英文直出 | 1 张修复卡：5 处改 `t()`，补 en/zh 键（含复数/插值无需） |
| 中 | 1-1 孤儿键 `s` | 随 3-1 卡顺带清理或单独小卡（先定位 `t(metric.label)` 动态来源再删） |
| 中 | 平行 i18n 机制 ~100 行/12 文件 | 1 张迁移卡（范围大，建议按文件分批，先 tool-availability + MemorySection 邻域） |
| 低 | 1-3 约 15 个未译词条 | 并入任意补键卡的批量翻译 |
| 低 | common.json 死命名空间 / uk 缺文件 / fr 漂移 909+466 | 1 张清理卡（删 common.json×4 + 测试改造；fr 漂移单独评估） |
| 低 | "Pro Vide Writing" typo | 待人确认名称后 1 行修复 |

## 复现方式

```bash
cd web && python3 ../evidence/i18n-scan-2026-10-04/scan_i18n.py .   # 全量输出 scan_raw.txt
```

抽查命令：`grep -rn "题库" web/components/memory/MemorySection.tsx`、`sed -n '160,168p' web/components/courses/CourseSyllabus.tsx`。

## 附：扫描覆盖说明

- `t()` 静态调用 5609 处（含 `i18n.t`）；动态 `t(\`…${…}\`)` 15 处归入前缀族分析；`t(变量)` 动态标签（如 `t(metric.label)`、`t(label)`）约 10 处无法静态校验，其中 PracticeInsights 疑为键 `s` 来源，已单列。
- 英文 JSX 文本节点启发式扫描只命中 2 处（co-writer 示例模板），说明 JSX 层 `t()` 覆盖率极高，硬编码集中在 setError/属性/平行机制三条路径，已全部单独扫描。

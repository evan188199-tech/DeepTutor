# AGEN-710 · web/ 无障碍基础静态清点报告

- **扫描对象**: HKUDS/DeepTutor `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13），独立 worktree，分支 `scan/a11y-basics-20261005`
- **扫描日期**: 2026-10-05
- **方式**: 只读静态扫描（Python 掩码扫描器 `scan_a11y.py` + 逐条上下文人工分型 `classify_a11y.py` + ripgrep 交叉复核）。**未修改任何产品代码，产物只进本证据目录。**
- **范围**: `web/**/*.{tsx,jsx,ts,js,mjs,mts}`，共 1253 个文件（排除 `generated`/`dist`/`node_modules`/`.next`/`tests`）；标签级检查面为其中 526 个应用 JSX 文件。
- **边界**: 按卡面要求，不含需运行时测量的对比度、焦点顺序；heading 顺序为"同文件源码顺序"的静态近似。

## 1. 结论（PASS）

| 分型 | 命中 | 判定 | 说明 |
| --- | --- | --- | --- |
| A2 表单控件缺可访问名 | 185 | **issue** | input×123 / select×31 / textarea×31，全部属"可见文字标签存在但未程序化关联"或"仅 placeholder"两类模式（§4） |
| A3 button 无文本/无可访问名 | 19 confirmed | **issue** | 纯图标按钮（X/ArrowUp/ArrowDown/Trash2 等）无 aria-label（§5 清单） |
| A3 button 内容取决于调用方 | 48 | needs-review | `{children}`/`{label}` 型包装按钮，运行时是否有名取决于用法，需逐处确认 |
| A4 heading 跳级 | 3 | **issue** | 同文件源码顺序 h1→h3 跳级 ×3（LOW，最佳实践） |
| B1 aria-hidden 落在可聚焦元素 | 4 | non-issue | 逐条人工核对，全部为隐藏文件输入惯用法（§6） |
| B3 aria-labelledby/describedby 引用断链 | 2 | non-issue | 逐条人工核对，id 由模板字符串生成、运行时可解析（§6） |
| A1 img 缺 alt | 0 | — | JSX 内 26 处 `<img>` 全部有 alt（装饰性 `alt=""` 或描述文本） |
| B2 非法 role 名 / B4 tabindex>0 / B5 同文件重复 id | 0 | — | rg 与扫描器双向复核均为 0 |

**合计：原始命中 261；人工分型后 issue 207（A2 185 + A3 19 + A4 3）、needs-review 48、non-issue 6。** 权威明细（逐条 path:line/分型/依据）见 `a11y_classified.json`；原始探测数据见 `findings.json`。

## 2. 扫描面与 rg 交叉复核

- 扫描器在 526 个应用 JSX 文件中解析出的开标签：button 1115、input 260、select 81、textarea 51、img 26、h1–h6 197。
- `rg '<button' -g '*.tsx'`（排除 tests/generated）命中 1155 行 ≈ 扫描器 1115 个开标签（rg 行数含多行标签的重复行，口径一致）。
- `rg '<img'`（JSX 文件）26 处，与扫描器一致，全部有 alt；其余 17 处 `<img` 位于 `.ts`（markdown/正则字面量等非 DOM 语境），不构成 DOM 命中。
- `rg 'tabindex="[1-9]|tabindex=\{[1-9]'` 与扫描器一致为 0。
- `rg 'aria-labelledby'` 命中均能对应到静态 id 或模板 id（后者见 §6 B3 判定）。

## 3. 分型标准

- **A2 control-no-name**: `input/select/textarea`（`type=hidden` 除外）同时不满足：`aria-label`/`aria-labelledby`/`title`、`id` 与同文件 `htmlFor` 配对、位于 `<label>…</label>` 内。隐藏文件输入惯用法（type=file + `hidden` class 或 aria-hidden+tabIndex=-1）按正面排除项剔除（13 处）。
- **A3 button-no-text**: `<button>` 无 aria-label/aria-labelledby/title；内容分类器判定——静态文本/i18n 调用/数据绑定表达式 → 有名（排除）；`{children}`/`{label}` 等单变量 → needs-review；空/仅图标组件/条件图标 → confirmed。
- **A4 heading-skip**: 同文件源码顺序中标题级别增量 > +1。
- **B1**: aria-hidden=true 且元素为 button/a[href]/表单控件/带 tabindex。
- **B2**: role 值不在 WAI-ARIA 1.2 role 名单（仅静态字符串）。
- **B3**: aria-labelledby/describedby 引用的静态 id 在同文件不存在（同文件近似，跨文件 id 需运行时验证）。
- **B4**: tabindex 静态值 > 0；**B5**: 同文件静态 id 重复。

**局限**：JSX 组合渲染使同文件顺序 ≠ 最终 DOM 顺序；跨文件 label 关联、运行时注入的 aria 属性、Canvas/SVG 内部结构不在本口径内。所有 confirmed 结论均经人工读码复核抽样验证（A3 confirmed 19 条全读，A2 每簇抽样 ≥3，A4 3 条全读）。

## 4. A2 密度分布与模式聚类（185 处 / 84 文件）

按修复模式聚类（模式定义见 `a11y_classified.json` 的 `pattern` 字段）：

| 模式 | 处数 | 典型位置 | 根因 |
| --- | --- | --- | --- |
| setting-row | 34 | 9 个设置文件（MinerUEngineSettings×8、SubagentSettingsEditor×7、DocumentParsingSettingsSection×7 等） | `SettingRow`（`components/settings/shared.tsx:141-165`）把 title 渲染在普通 `<div>`，与 control 插槽无 htmlFor/id 关联 |
| adjacent-label | 78 | CreateKbModal×10、McpServerForm×8、SkillsSection×6、CoWriterWorkspace×5、EngineDetail×4、QuizConfigPanel×4 … | 文件内存在可见 `<label>`（无 htmlFor），相邻控件无 id |
| bare-control | 68 | TurnCoordinationSettings×5、NotebookConsole×4、ResearchConfigPanel×3、VisualizeConfigPanel×3 … | 控件无任何名称来源（多数仅 placeholder；仅 placeholder 6 处） |
| field-label | 5 | `components/partners/schema-form.tsx` | `FieldLabel` 兄弟组件渲染 label，未与控件建立关联 |

按目录密度（issue 口径，Top12）：components/settings 25、components/knowledge 23、features/settings 21、app/(workspace) 20、components/space 19、components/partners 14、components/mcp 13、components/chat 11、components/notebook 7、components/research 6、components/quiz 6、features/runtime-status 5。

## 5. A3 纯图标按钮 confirmed 清单（19 处 / 14 文件）

| # | 位置 | 图标/语境 | 建议 aria-label |
| --- | --- | --- | --- |
| 1 | `app/(workspace)/learning/books/components/BookChatPanel.tsx:472` | X（关闭聊天面板） | Close chat panel |
| 2 | `app/(workspace)/learning/books/components/BookChatPanel.tsx:572` | 附件区图标按钮 | 按动作命名 |
| 3-5 | `app/(workspace)/learning/books/components/SpineEditor.tsx:321,328,335` | ArrowUp/ArrowDown/Trash2（章节排序/删除） | Move chapter up / down / Remove chapter |
| 6 | `app/(workspace)/learning/books/components/BookHealthBanner.tsx:359` | 图标按钮 | 按动作命名 |
| 7 | `app/(workspace)/partners/groups/[groupId]/page.tsx:302` | 图标按钮 | 按动作命名 |
| 8 | `features/settings/sections/MemorySettingsSection.tsx:353` | 图标按钮 | 按动作命名 |
| 9 | `features/settings/sections/CapabilitiesSettingsSection.tsx:622` | 图标按钮 | 按动作命名 |
| 10 | `features/knowledge/components/engines/EngineDetail.tsx:924` | 图标按钮 | 按动作命名 |
| 11 | `components/research/ResearchOutlineEditor.tsx:207` | 图标按钮 | 按动作命名 |
| 12 | `components/settings/Toggle.tsx:13` | role="switch" 通用开关，无文本 | 必须由调用方注入 aria-label（switch 角色自身不产生名称） |
| 13 | `components/memory/MemorySection.tsx:1474` | 图标按钮 | 按动作命名 |
| 14 | `components/partners/group/GroupComposer.tsx:181` | 图标按钮 | 按动作命名 |
| 15 | `components/notebook/NotebookConsole.tsx:529` | X（关闭错误横幅） | Dismiss |
| 16-17 | `components/space/SkillsSection.tsx:783,831` | X（关闭预览） | Close |
| 18-19 | `components/space/PersonasSection.tsx:432,485` | 图标按钮 | 按动作命名 |

同库存在正确范式可直接复用：`components/reading/workspace/ReadingComposer.tsx:200` 等 319 处按钮已带 `aria-label={t(...)}`。

## 6. 人工核对为非问题的命中（6 处）

- **B1 ×4**（`BookChatPanel.tsx:553`、`SessionViewerPanel.tsx:1069`、`ChatComposer.tsx:1022`、`PartnerComposer.tsx:422`）：均为 `type="file"` + `className="hidden"` + `tabIndex={-1}` + `aria-hidden="true"` 的程序化文件输入，display:none 不可聚焦，aria-hidden 语义正确。该惯用法在库内共 13 处（另 9 处无 aria-hidden 但有 hidden class，同样不可聚焦，已在 A2 正面排除）。
- **B3 ×2**（`components/knowledge/KnowledgeHome.tsx:308,414`）：引用的 `knowledge-bases-tab`/`knowledge-engines-tab` 由 `id={`${item.id}-tab`}`（:280）生成，运行时可解析。

## 7. Top 10 修复建议（按杠杆率排序）

1. **改 `SettingRow` 一处，解 34 处**：`components/settings/shared.tsx:141` 用 `useId()` 生成 id，`cloneElement` 注入 control，title 改渲染 `<label htmlFor>`。覆盖 9 个设置文件。
2. **CreateKbModal 10 控件补关联**：`components/knowledge/CreateKbModal.tsx:663,687,1079,1112,1201,1242,1341,1373,1390,1592`——现有可见 `<label>` 加 `htmlFor` + 控件加 `id`。
3. **McpServerForm 8 控件补关联**：`components/mcp/McpServerForm.tsx:189,200` 等，同上模式（`labelClass` 标签已存在）。
4. **SpineEditor 3 个排序/删除按钮加 aria-label**（`app/(workspace)/learning/books/components/SpineEditor.tsx:321,328,335`），同文件 3 处可一批完成。
5. **SkillsSection 一文件双修**：A2 ×6（:64 等 adjacent-label）+ A3 confirmed ×2（:783,831），单 PR 可清零。
6. **TurnCoordinationSettings 5 个 bare-control**（`features/runtime-status/TurnCoordinationSettings.tsx:62,75,107,131,144`）：逐个补 aria-label（文案可用现有 title 翻译键）。
7. **Toggle 开关名称注入**：`components/settings/Toggle.tsx:13` 增加 `label?: string` prop → `aria-label`，并审计其调用点传入语义名。
8. **CoWriterWorkspace 5 控件补关联**（`features/co-writer/components/CoWriterWorkspace.tsx`）。
9. **heading 跳级 3 处降改**：`app/(workspace)/partners/new/page.tsx:378`、`components/memory/MemoryHub.tsx:192`、`components/courses/CoursesShelf.tsx:167` 的 h3→h2（各 1 行改动）。
10. **schema-form FieldLabel 关联**：`components/partners/schema-form.tsx:112,204,228` 等给 FieldLabel 增加 htmlFor/id 透传，一次修复 5 处。

其余 48 处 needs-review（`{children}/{label}` 包装按钮）建议在上述卡片落地时顺带逐处确认，不单开卡。

## 8. 可拆修复卡条目

| 卡 | 范围 | 预计消除命中 | 风险 |
| --- | --- | --- | --- |
| a11y-1 SettingRow 关联 | components/settings/shared.tsx + 9 文件回归 | 34 | 低（纯 DOM 属性，无视觉变化） |
| a11y-2 知识库/MCP 表单关联 | CreateKbModal + McpServerForm | 18 | 低 |
| a11y-3 图标按钮 aria-label 批次 1（books/space） | SpineEditor、BookChatPanel、SkillsSection、PersonasSection | 9 | 低 |
| a11y-4 图标按钮 aria-label 批次 2（其余 10 文件） | §5 其余行 | 10 | 低 |
| a11y-5 bare-control 批次 | TurnCoordinationSettings、NotebookConsole、ResearchConfigPanel、VisualizeConfigPanel 等 | 68 | 低-中（需逐个确定文案） |
| a11y-6 co-writer + schema-form + FieldLabel 关联 | CoWriterWorkspace、schema-form | 10 | 低 |
| a11y-7 heading 跳级 | 3 文件各 1 行 | 3 | 低 |
| a11y-8 needs-review 人工确认 | 48 处包装按钮 | 视确认结果 | 低 |

## 9. 验收核对

1. **每项附 path:line 与分型依据**：`a11y_classified.json` 逐条含 file/line/category/triage/pattern/note。
2. **命中按组件聚类，Top10 给修复建议**：§4 密度分布 + §7 Top10。
3. **不改任何代码**：本分支相对 `origin/main` 仅新增本证据目录（`git diff --stat origin/main` 可核）。

## 10. 复现

```bash
python3 evidence/a11y-basics-20261005/scan_a11y.py web --json /tmp/findings.json
python3 evidence/a11y-basics-20261005/classify_a11y.py web   # 需将 findings.json 放同目录
```

上游开放 PR 核对（2026-10-05，`gh pr list -R HKUDS/DeepTutor --state open` + `gh search issues`）：无 accessibility/alt/label 相关开放 PR 或 issue，无撞车。

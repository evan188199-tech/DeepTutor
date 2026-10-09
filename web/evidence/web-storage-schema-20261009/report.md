# web 本地存储清点与 schema 漂移扫描报告

- 日期：2026-10-09
- 基线：origin/main @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release: v1.6.14）
- 范围：`web/` 全部 localStorage / sessionStorage 读写点（只读扫描，无任何代码改动）
- 明细：见同目录 `inventory.json`（47 个 key 族、33 个产品文件、全部读写点带 文件:行 锚点）

## 复算方法

```bash
# 原始 Web Storage API 直连点
rg -n 'localStorage|sessionStorage' web -g '*.{ts,tsx,js,jsx}'
# 包装层读写点
rg -n 'browserStorage\.(readRaw|writeRaw|removeRaw|read|write|remove|listRaw|subscribe|clearNamespace)' web
# 类型化 StorageKey 定义点
rg -n 'defineStorageKey|dynamicStorageKey' web
```

排除项：`web/lib/client-cache.ts` 为内存 Map 缓存（`knowledge:` 前缀），不属于 Web Storage；`web/tests/**`（24 个测试文件）不参与发现分级，仅统计。

## 架构现状

`web/shared/storage/`（keys.ts / schema.ts / store.ts）提供了一套类型化存储层：`deeptutor:v2:<scope>:<name>` 命名空间、`{version, value, writtenAt}` 信封、校验与迁移钩子、`subscribe`/`clearNamespace` 等完整 API。**但生产代码零消费**：`defineStorageKey`/`dynamicStorageKey` 只出现在 `web/tests/storage.test.ts`；生产路径全部走 `readRaw`/`writeRaw`/`removeRaw`/`listRaw` 的裸字符串 key。

## 发现（按风险分级）

### F1 · schema 版本化缺位（Medium）

信封版本机制（`web/shared/storage/schema.ts:3-7`）与 `deeptutor:v2:` 命名空间（`web/shared/storage/keys.ts:1`）存在但未被任何生产 key 使用。47 个 key 族中仅 6 个带版本标记，且形式不一：

- payload 内版本：`deeptutor.co_writer.draft.v2.*`（`web/features/co-writer/storage/drafts.ts:4,18`，`version:2` 字段校验）
- key 名后缀：`deeptutor.co_writer.draft.*` 遗留轴（drafts.ts:5）、`deeptutor.co_writer.split_ratio.v2`、`sync_scroll.v2`（`drafts.ts:6-7`）、`deeptutor.settings.diagnosticsResults.v1`（`web/features/settings/store/SettingsStore.tsx:212`）、`knowledge:history:v1`（`web/hooks/useKnowledgeHistory.ts:22`）
- 其余 41 个 key 族（主题、语言、侧栏、reader 偏好、capability-config 等）完全无版本：值结构一旦演化只能靠每个消费点的兜底逻辑盲迁移。

风险：schema 漂移时无统一迁移路径，各消费点行为取决于各自兜底的宽严（见 F4）。

### F2 · key 命名规约四种并存（Low）

- `deeptutor-kebab`：`deeptutor-theme`、`deeptutor-language`、`deeptutor-response-language`
- `deeptutor.dot`：`deeptutor.sidebar.*`、`deeptutor.chatResponseTimeout`、`deeptutor.co_writer.*`、`deeptutor.failedSubmissions.*`、`deeptutor.book.*`
- `deeptutor:colon`：`deeptutor:settings-return`、`deeptutor:partner-group:*`、`deeptutor.activeSessionId.tab`
- 短前缀/无前缀：`dt.reader.*`、`dt:viewer-width`、`dt:chat:*`、`dt:memory:*`、`dt.mastery.outline`，以及完全无命名空间的 `reading-learning`（`web/components/reading/workspace/useLearningMode.ts:12`）、`knowledge:history:v1`、`watching-browser:*`、`panel:*`、`partner-session:*`

key 常量无统一注册表：除 `app-shell-storage.ts:73-83` 集中定义外，多数散落在消费文件内，字面量重复（见 F3）。

### F3 · 同 key 多写入者 / 跨模块覆写风险（Low）

- `dt:memory:banner-dismissed`：`web/components/memory/MemoryArchivedBanner.tsx:30` 与 `web/components/memory/MemorySection.tsx:299` 双写，key 字面量在两文件重复定义、无共享常量；语义一致（存最近归档名），但任一侧改动即静默漂移。
- `deeptutor-theme`：`web/components/ThemeScript.tsx:31,34`（水合前内联脚本，只写 `dark`/`snow`）与 `web/lib/theme.ts:62`（写全部四值，含 `glass`）双写。值域兼容，属有意的水合前初始化设计；副作用是 `glass` 主题首帧走系统偏好回退（`ThemeScript.tsx:14-38`），非缺陷但值得知晓。
- 未发现同一 key 被不同语义模块覆写的情况；`deeptutor.activeSessionId.tab:<wsId>` 通过 workspace 后缀隔离，`failedSubmissions.record.*` 在 local/session 双 scope 同名键是有意的降级容灾（`web/lib/failed-submissions.ts:202-227`）。

### F4 · 损坏 JSON 回退一致性（Low，风格分裂）

全部读写点均有守卫（`browserStorage` 层吞异常；5 个引用 `window.localStorage` 的文件中，`ThemeScript.tsx` 与 `lib/chat-markdown-note.ts` 直接调用其方法且有 try/catch 或 null 守卫，co-writer 三处将其作为 `StorageLike` 参数传入 helpers，helpers 内部再守卫），**无未捕获抛出路径**。但回退严格度分三档：

1. 严格校验 + TTL/迁移：failed-submissions 全家族（`web/lib/failed-submissions.ts:64-75,166-199`）、co-writer drafts（`drafts.ts:32-56`）、`PageReader.tsx:66-81`、`reading-location-history.ts`（逐条校验）、`reading-display-preferences.ts:40-75`（逐字段白名单+边界）。
2. 白名单归一化：主题/语言枚举（`lib/theme.ts:39-52`、`app-shell-storage.ts:48-51`）。
3. `JSON.parse(raw) as T` 裸断言：`web/lib/sidebar-layout.ts:247-250`（readJsonLocal 仅 try/catch，解析结果不验形状即入组件状态）、`web/features/chat/components/ChatWorkspace.tsx:509-521`（有 catch-ignore）、`web/components/watching/WatchingBrowser.tsx:73,110`、`web/features/settings/store/SettingsStore.tsx:431-433`（仅验 object）、`useKnowledgeHistory.ts:34-43`（仅验 byKb 存在）。

最弱点是 `sidebar-layout.ts:249`：形状错误的合法 JSON 会原样进入 `SidebarNav` 布局状态。

### F5 · 无界增长（Low）

按 session/实体派生 key 且无 GC 的家族：`dt.reader.history.<sid>`（条目限 50，但旧 session 的 key 永久残留）、`dt:chat:capability-config:<sid>`（`ChatWorkspace.tsx:527` 只增不删）、`dt:memory:active-run:<layer>:<key>`（正常清除有 `removeRaw`，中断运行残留）、`partner-session:*`、`dt:chat-markdown-note:*`、`deeptutor:partner-group:*`。

正面参照：failed-submissions 家族有 7 天 TTL 与启动剪枝（`failed-submissions.ts:173-199`），`deeptutor.book.pendingChapterEnd` 带 TTL（`PageReader.tsx:27,72-75`）。

### F6 · 敏感数据观察（Info，中性记录）

清点范围内未发现 token、密码或凭据类值写入 Web Storage。会话标识类值（`partner-session:*`、`deeptutor.activeSessionId.tab:*`）按 Web Storage 固有模型对同源脚本可读，属常见做法，仅记录不计风险。

### F7 · 死键与死抽象（Info）

- `deeptutor:workspace` 仅出现在 `web/tests/workspace-scope.spec.ts:43`；产品代码的 workspace 作用域取自 URL query（`web/lib/workspace-scope.ts:4-7`），该测试播种的是一个产品不再读取的键。
- 类型化存储层的 `read/write/remove/subscribe/clearNamespace` 与信封迁移在生产零调用（仅 `web/tests/storage.test.ts`），是当前最大的"已建未用"抽象面。

## 统计

| 维度 | 数量 |
|---|---|
| key 族总数 | 47 |
| localStorage 族 | 34 |
| sessionStorage 族（含 3 个 local+session 双写族） | 13 |
| 产品文件（含直接读写点） | 33 |
| 引用 window.localStorage 的产品文件 | 5 |
| 带版本标记的 key 族 | 6 |
| 无版本 key 族 | 41 |
| 测试文件引用（仅统计） | 24 |

发现合计：1 Medium（F1）+ 3 Low（F2/F3/F5）+ 1 Low·风格（F4）+ 2 Info（F6/F7）。本卡为只读清点，不包含任何代码或测试改动。

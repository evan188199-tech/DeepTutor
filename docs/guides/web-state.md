# web/ 前端状态层导读（context / features store / hooks / 持久化 / 错误信封）

- 基线: origin/main @ `f07029cfc`（release v1.6.13）。所有 `path:line` 在该 commit 逐一核对存在。
- 定位: 导读，不是审计。讲清状态"放在哪、怎么读写、何时失效"，供前端修卡/补测卡快速定位改动面。
- 边界（去重声明）: 整体地图与页面分层见 guide-frontend（§3 只有五点速览，本篇展开全部读写路径）；契约生成与 `detail.code` 手写解析的完整清单见 `docs/guides/web-contracts.md` §5；路由/权限守卫见 `docs/guides/web-guard-layers.md`；语言选择见 guide-i18n。本篇只在与状态衔接处引用它们，不重复。

## 0. 一分钟总览

无全局状态库（无 redux/zustand/react-query）。"共享状态"只有 4 个 Provider，其余都是组件本地 state + 模块级缓存 + window 事件总线：

| 层 | 载体 | 定义/入口 | 管什么 | 不管什么 |
|---|---|---|---|---|
| 全应用壳 | `AppShellContext` | Provider `web/context/AppShellContext.tsx:77`（挂在 `web/app/layout.tsx:57`） | theme/语言/activeSessionId/侧栏/代码块偏好 | 任何业务数据 |
| 会话状态机 | `ChatStateAdapter`（useReducer） | Provider `web/features/chat/ChatStateAdapter.tsx:1790`，经 `ChatRuntimeProvider.tsx:19` 挂在 `web/app/(workspace)/layout.tsx:20` | 每会话消息/流式/配置/分支 + turn 运行时 | **会话列表**（在侧栏组件里） |
| 设置域 | `SettingsStore` | Provider `web/features/settings/store/SettingsStore.tsx:626`，挂在 `web/app/(settings)/settings/layout.tsx:17-21` | catalog/draft/providers/ui 偏好 + 诊断 | 设置页以外的拉取 |
| 页面域 | 专项 Context | `web/context/ReadingContext.tsx:91`、`WatchingContext.tsx:49`、`QuizFollowupContext.tsx:626`、`GeogebraTabContext.tsx:87` | 阅读/观看/测验追问等页面运行时 | 跨页复用 |
| 会话列表 | `WorkspaceSidebar` 组件本地 state | `web/components/sidebar/WorkspaceSidebar.tsx:57` | 列表拉取/分组/排序/未读 | 会话内容 |
| 课程域 | 无 provider | 六处独立拉取，仅靠 15s TTL 缓存对齐（`web/lib/courses-api.ts:186`） | 课程 CRUD | 实时同步 |
| 数据 hooks | `web/hooks/*` + `withClientCache` | `web/lib/client-cache.ts:16` | TTL 30s 默认 + single-flight 去重 | 持久化 |
| 浏览器持久化 | `browserStorage` raw API + 零散直连 | `web/shared/storage/store.ts:108-128` | 全部 localStorage/sessionStorage 键 | 无清空路径（§4.5） |
| 错误信封 | `ApiError`（新一代）/ 领域错误类（遗留主流） | `web/shared/api/client.ts:74-109` | HTTP 错误归一化 | WS 错误（独立通道，§5.4） |

关键认知：**状态所有权极度分散**。同一个"会话列表"有 TTL 缓存、`sidebarRefreshToken`、`sessions:changed` 事件三条刷新通道（§2.1）；同一个"语言"偏好有 localStorage、服务器 ui settings、CustomEvent 三个副本（§1.1）。修卡前先确认改的是哪一份。

## 一、状态组织四层

### 1.1 全应用壳：AppShellContext

读写路径（每条都有锚点）：

- 初始化（SSR 安全）: theme 读 `getStoredTheme() ?? getSystemTheme()`（`AppShellContext.tsx:78-80`）；language 固定 `"en"` 起步（`:82`）；sidebar/代码块偏好用默认值（`:88-96`）。
- mount 水合: `useEffect` 一次性读回 sidebar/代码块三项（`:98-104`）；activeSessionId 例外——`useState` 初始化函数里直接读 sessionStorage（`:84-86`），因为 tab 级会话 id 无 SSR 指纹问题。
- 语言兜底拉取: 本地无选择时 `GET /api/settings/ui`（1.5s 超时 `:136-139`，`skipAuthRedirect: true` `:143`），只在浏览器从未选过时采纳服务器值（`hadLanguage` 判定 `:154-169`）；接口与输出语言双键判定（`:126-135`）。
- 写入: 每个 setter 都是"写存储 + setState"两步（`setLanguage :279-283`、`setActiveSessionId :285-288`、`setSidebarCollapsed :290-293`、代码块三个 `:295-309`）。
- 跨标签同步: 双通道——原生 `storage` 事件（`:193-216`）+ 同页 `CustomEvent`（`LANGUAGE_EVENT` 等，`:218-254`，事件常量在 `web/context/app-shell-storage.ts:130-134`）。存储函数集中在 `web/context/app-shell-storage.ts`（键清单见 §4.2 第 1 行）。
- 消费: `useAppShell()`（`:355-361`）。

### 1.2 页面域 Context（一句话带过）

`ReadingProvider`（`web/context/ReadingContext.tsx:91`，`useReading :263`）、`WatchingProvider`（`web/context/WatchingContext.tsx:49`，`useWatching :208`）、测验追问 `useQuizFollowupController`（`web/context/QuizFollowupContext.tsx:626`）、Geogebra 标签页 `useGeogebraTabOpener`（`web/context/GeogebraTabContext.tsx:87`）。均为挂载期组件树内状态，无本地持久化（例外: 阅读学习面板 `reading-learning` sessionStorage，见 §4.2）。

### 1.3 会话状态机：ChatStateAdapter（3710 行）

状态形状 `ChatState`（`web/features/chat/ChatStateAdapter.tsx:173-224`）核心字段：`sessionKey`（本地身份，服务端未分配前是 `draft_…`，`:175`）、`sessionId`（`:176`）、`messages`（`:204`）、`isStreaming`/`currentStage`（`:205-206`）、`enabledTools`/`knowledgeBases`/`llmSelection` 等会话配置（`:178-184`）、`workspaceId`/`courseId`（`:195-196`）、分支选择 `selectedBranches`（`:212`）、未发送标记 `submissionFailed`/`submissionNotSaved`（`:219-223`）。

- 内部结构: `SessionEntry`（`:341-350`，含运行时 `status: "idle"|"running"|…` `:111-112`）；reducer 真正的状态 `ProviderState = { selectedKey, sessions: Record<key, SessionEntry>, sidebarRefreshToken }`（`:352-356`）。
- Action 联合 `type Action`（`:385-479`，34 个）按职责分七组：配置类 11（`SET_TOOLS`/`SET_COURSE_ID`/`SET_LANGUAGE`…，多数带可选 `key`——后端推送属于产生它的会话，不一定是当前选中的，`:390-392`）；乐观消息 4（`ADD_USER_MSG`/`RESTORE_ASSISTANT`…）；流式 4（`STREAM_START/TOUCH/EVENT/END`）；会话生命周期 5（`BIND_SERVER_SESSION`/`LOAD_SESSION`/`REVALIDATE_SESSION`…）；转录维护 4（`RECONCILE_TURN`/`SETTLE_MESSAGE_TRACE`…）；草稿 3；分支 2；侧栏 1（`BUMP_SIDEBAR_REFRESH`）。
- reducer（`:652-1461`）要点：内存会话缓存 LRU 上限 `MAX_CACHED_SESSIONS = 20`（`:627-639`），**running 状态的会话拒绝淘汰**（`:635`）；`isSameTurnEvent` 按 seq 去重（`:643-650`）；`REVALIDATE_SESSION` 在本地 turn 存活时丢弃（`:1140-1148`）。
- Provider `ChatStateAdapterProvider`（`:1790`，`useReducer :1795`）；单运行时约束在 `ChatRuntimeProvider`（`web/features/chat/ChatRuntimeProvider.tsx:9-22`，嵌套即 dev 抛错）；消费 `useChatStateAdapter()`（`:3703-3710`），主要消费者 `ChatWorkspace.tsx:278-279` 与 `WorkspaceSidebar.tsx:40-47`。
- 读路径：会话内容只经 `loadSession`（`:2423`，`GET /api/sessions/{id}` 见 `web/lib/session-api.ts:298-307`）→ `LOAD_SESSION`；内存命中走 `showCachedSession`（`:2310-2315`）零请求。
- 写路径（dispatch 位点）：用户动作经 `ChatWorkspace.handleSend` 等进入 `sendMessage`（`:2672`）；运行时事件全部经 `handleRunnerEvent`（`:1930-2178`）→ 见 §2.3；断连兜底在 `ensureRunner` 的 socket close 分支（`:2199-2229`）。

### 1.4 设置域：SettingsStore（2304 行）+ 卫星 provider

状态全部是 `useState` 平铺（`web/features/settings/store/SettingsStore.tsx:638-699`）：`catalog`（live）与 `draft`（可编辑副本，`:643-644`）、`providers` 八服务（`:646-657`）、`storedDraft`/`savedSignature`/`draftRevision`（`:662-665`）、`saving`/`applying`/`toast`/`logs`（`:666-672`）、`modelTests`/诊断（`:673-680`）。派生：`draftState`/`hasUnsavedChanges`（`:2129-2135`）、`beforeunload` 拦截（`:2141-2149`）。

读路径（`loadSettings`，`:747-860`）：一个信封三个端点——`GET /api/settings`（`:751`，返回 `{ui, catalog, providers, connection_targets, task_kinds}`，类型 `SettingsPayload :204-210`）、`GET /api/settings/draft`（`:791`）、`GET /api/system/status`（`:840`）；mount 守卫 `loadedOnce`（`:872-878`），重读必须走显式 `reloadSettings`。注意它不读 `settings/ui`（GET）——那是 AppShell（`:141`）和 `useSetupSync`（`web/hooks/useSetupSync.ts:60`）的事。

写路径（全部 await、不乐观；失败 `setToast`）：

| 动作 | 锚点 | 端点 |
|---|---|---|
| `saveDraft` | `SettingsStore.tsx:1467-1494` | `PUT /api/settings/draft` |
| `applyService` | `:1497-1554` | `POST /api/settings/apply/service`，成功后 `invalidateLLMOptionsCache()` `:1530` |
| `saveRegistry` | `:1556-1626` | `POST /api/settings/apply/registry`，失效 LLM 缓存 `:1611` |
| `saveProvider` | `:1628-1722` | `POST /api/settings/apply/provider`，失效 `:1707` |
| `applyCatalog` | `:1725-1803` | 校验 `:1728-1740` → `PUT draft :1745` → 各 extension 各自端点 → `POST /api/settings/apply :1765`（无 draft 则 `DELETE :1784`）；失效 `:1775`，`draftRevision++ :1792` |
| `discardDraft` | `:1860-1883` | `DELETE /api/settings/draft`，`draftRevision++ :1873` |
| `runDetailedTest` | `:1910-2063` | `POST /api/settings/tests/{service}/start :1980` + SSE 事件流 `:1995` |

卫星 provider 都是 `useSettings` 的 memoized 切片，零自有拉取：`UiSettingsProvider`（`web/features/settings/store/UiSettingsProvider.tsx:63-68`）、`ModelCatalogProvider`（`ModelCatalogProvider.tsx:102-107`）、`SettingsDraftProvider`（`SettingsDraftProvider.tsx:63-70`）。子页草稿经 `useStagedSettings`（`web/features/settings/store/useStagedSettings.ts:13-65`）注册进 provider：值 = `pendingExtensionPayload(key) ?? live`（`:20`），`draftRevision` 变化触发恢复（`:39-59`）。每个 extension 保存端点映射在 `web/lib/settings-extensions.ts:16-31`（动态前缀 `subagent:*`/`guardian:*` 等 `:45-56`）。

### 1.5 hooks 层：withClientCache 与刷新触发

- `withClientCache`（`web/lib/client-cache.ts:16-61`）：模块级 `Map`；默认 TTL 30s（`:21`）；键自动加 `":workspace=" + activeWorkspaceId()` 后缀（`:28`，`activeWorkspaceId` 只读 URL，`web/lib/workspace-scope.ts:2-6`）；**single-flight**——并发调用共享同一在途 promise（`:34-36`）；请求失败即删条目（`:50-52`）；按前缀失效 `invalidateClientCache`（`:63-69`）。
- 使用者：`web/lib/session-api.ts`（列表 15s，`listSessions` `:199-227`，TTL `:224`）、`web/lib/courses-api.ts`（§三）、`web/lib/llm-options.ts`（`"llm-options:list"` `:5`，请求 `:58`）、`web/lib/workspaces-api.ts`、`web/features/knowledge/api/client.ts`、`web/features/capabilities/api.ts`。
- 失效触发有两类：**mutation 后显式失效**（如 `session-api.ts:345/363/405/415`）与**页面聚焦强刷**——`ChatWorkspace.tsx:1340-1360` 在 `focus`/`pageshow`/`visibilitychange` 时 `refreshLLMOptions({force:true, background:true})` + `refreshKnowledgeBases({force:true})`。
- 状态机式 hook 范例：`useLLMOptions`（`web/hooks/useLLMOptions.ts:25`）= useReducer + `createSingleFlight`（`web/lib/single-flight.ts:6-21`）+ 请求序号防过期（`:37-54`）；旧列表保留的 stale-while-revalidate 语义在 `web/lib/llm-options-state.ts:31-49`（刷新失败且已有列表时降级继续用旧值 `:44-47`）。

## 二、核心状态流：会话（含端到端数据流）

### 2.1 会话列表：三条刷新通道 + 一条总线

- 谁拉：`WorkspaceSidebar.refreshSessions`（`web/components/sidebar/WorkspaceSidebar.tsx:57-82`）调 `listAllSessions({force:true, allWorkspaces:true})`（`:67`，分页聚合在 `web/lib/session-api.ts:230-247`），顺带拉 courses/mastery 索引（`:49,68`）。
- 通道 1 `sidebarRefreshToken`：reducer 在 `STREAM_END`（`ChatStateAdapter.tsx:1098`）、`BIND_SERVER_SESSION`（`:1128`）、`SET_SESSION_TITLE`（`:1236`）、`DELETE_TURN`（`:1407`）、`BUMP_SIDEBAR_REFRESH`（`:1410-1414`）时递增；`WorkspaceSidebar` 的 effect 依赖它重拉（`WorkspaceSidebar.tsx:89-91`）。即：**列表在 turn 结束后才刷新**。
- 通道 2 延迟补偿：turn `done` 后 +5s 再 bump 一次等 LLM 标题（`ChatStateAdapter.tsx:1490`，定时器 `:2070-2072`）；WS 保持 15s 等 `session_meta`（`:1472`，定时器 `:2062-2067`）。
- 通道 3 `sessions:changed` 窗口事件总线（`web/lib/session-events.ts:20-28`）：组织/删除/工作区变更时触发（`session-api.ts:406,416`、`web/lib/workspaces-api.ts:80,133,193`）；订阅在 `WorkspaceSidebar.tsx:96-99`、`UtilitySidebar.tsx:80`、`useChatWorkspaces.ts:38`。
- 未读：模块内存 `Set`（`web/lib/session-unread.ts:17`，刻意不持久化 `:5-16`）；`reconcileUnread` 把"离开 live 集合"的会话标记未读（`:57-78`）；`useUnreadSessions`（`:88-92`）用 `useSyncExternalStore`；输入是 `WorkspaceSidebar.tsx:109-126` 折叠的 `sessionStatuses`。
- 排序/分组：置顶 > 正在流式 > 最近（`web/lib/session-organization.ts:20-32`）；树形嵌套 `:35-80`。

### 2.2 活跃会话 id

`AppShellContext.setActiveSessionId`（`web/context/AppShellContext.tsx:285-288`）写 sessionStorage 键 `deeptutor.activeSessionId.tab:<workspaceId>`（`web/context/app-shell-storage.ts:73`，读写 `:246/:256-258`）并广播 `ACTIVE_SESSION_EVENT`。调用方：`ChatWorkspace.tsx:1277`（随加载 effect 回写）、侧栏/历史/归档各选中处。跨标签同步靠 `storage` 事件（`AppShellContext.tsx:197-198`）。注意键是**每标签页语义 + 每工作区后缀**。

### 2.3 端到端数据流：发送一条 chat 消息（API/WS → store → 组件）

```text
① ComposerInput.doSend            web/components/chat/home/ComposerInput.tsx:323-335
② ChatComposer.doSend             web/components/chat/home/ChatComposer.tsx:655-667
③ ChatWorkspace.handleSend        web/features/chat/components/ChatWorkspace.tsx:1898
     （ask_user 分流 :1913-1928；course 绑定注入 _course_id :2009-2016）
④ adapter.sendMessage             web/features/chat/ChatStateAdapter.tsx:2672
     dispatch ADD_USER_MSG :2931 → reducer :746   乐观用户气泡（负数 id :749）
     dispatch STREAM_START :2942 → reducer :852   占位助手气泡 + isStreaming
     storeFailedSubmission :2963                  未发送文本先落 localStorage（§4.2）
⑤ sendThroughRunner :2991-3080 → runner.client.send :2298
     （未连接时 200ms×60 重试，web/lib/send-retry.ts:1-2；耗尽 → STREAM_END failed :2262-2273）
⑥ buildStartTurnInput → buildStartTurn
     web/features/chat/controllers/buildStartTurnInput.ts:51 → web/contracts/parse/turn-command.ts:70
⑦ UnifiedTurnClient.send          web/features/chat/transport/UnifiedTurnClient.ts:127-129
   TurnRuntimeClient 出站队列        web/features/chat/transport/TurnRuntimeClient.ts:198-205 → 入队 :242 → sendNow :441-444
⑧ WebSocket scopedUrl("/ws")      TurnRuntimeClient.ts:133（socket.send :443）
⑨ 入站按 seq 有序                  handleMessage :308 → acceptStreamEvent :350-388（gap 缓冲 32 :137 + resume 重放 :452-466）
     → toStreamEvent               UnifiedTurnClient.ts:40-81
⑩ handleRunnerEvent               ChatStateAdapter.tsx:1930
     session   → BIND_SERVER_SESSION :1974 → reducer :1101（draft key 换正式 id，URL 随之改写 ChatWorkspace.tsx:1264-1274）
     流式增量  → STREAM_EVENT :2134 → reducer :914-993（rawContent 累积 :947-957）
     done      → STREAM_END :2048 → reducer :994-1100（isStreaming=false, status :1088, token bump :1098）
                → RECONCILE_TURN :2093 → reducer :1239-1269（done 携带的正式消息 id 换掉负数乐观 id）
                → SETTLE_MESSAGE_TRACE :2103 → reducer :1286-1340
⑪ 渲染：memo 化 context value      ChatStateAdapter.tsx:3633-3697
     → ChatWorkspace 读 state（:278-279）→ ChatMessageList（memo，web/features/chat/messages/ChatMessageList.tsx:1897）
⑫ 侧栏：token bump → WorkspaceSidebar.tsx:89-91 重拉列表；+5s 标题补拉（:2070-2072）
```

### 2.4 回写、staleness 与定时器常量

- 会话 `running` 状态**只存在于客户端**（reducer 写 `SessionEntry.status`），服务器的持久 running 不可信——`resolveLoadedRunStatus` 只在响应超时窗口内相信它（`ChatStateAdapter.tsx:2460-2466`）；空闲 watchdog 每 10s 用 `resume_from` 重订阅（`:2632-2670`）。
- 后台 revalidate 撞上本地活 turn 会被丢弃两次（load 侧 `:2435-2443`、reducer 侧 `:1140-1148`）。
- 常量表：加载超时 30s（`web/lib/session-load.ts:11`，缓存命中或用户中止不报错 `:29-37`）；replay 探测 5s（`TurnRuntimeClient.ts:138`）；ack 超时 30s（`:139`）；重连 250ms→8s 抖动、空闲上限 5 次（`web/features/chat/transport/reconnect-policy.ts:5-24`）；trace 缓存 LRU 容量 5、预览 200 事件/128KB（`web/features/chat/trace/memory.ts:276-292`、`:7-8`）。

## 三、核心状态流：课程（无 provider 的对照样本）

- API 层全部带 TTL 缓存 + mutation 失效（`web/lib/courses-api.ts`）：读 `listCourses`（`:172-188`，TTL 15s `:186`）、`getCourseState`（`:273-289`，10s）、候选资源（`:295-312`，30s）；写 `createCourse :190-207`、`updateCourse :209-233`、`deleteCourse :235-241`、挂/摘资源 `:243-271`、大纲 `:314-345`——每个写操作后 `invalidateClientCache("courses:")`。
- 拉取点有六处、互不共享 state：`web/components/courses/CoursesShelf.tsx:45-48`（课程页，失败显示 `role="alert"` 块 `:143-157`）、`web/app/(utility)/courses/[courseId]/page.tsx:47-79`、`WorkspaceSidebar.tsx:49,68`、`UtilitySidebar.tsx:40-58`、`ChatWorkspace.tsx:357`+`382-388`（失败静默成 `[]`）、`web/components/courses/CourseScope.tsx:50-109`。**课程域没有 `sessions:changed` 那样的事件总线**——侧栏课程区刷新只因 `refreshSessions` 顺带重拉。
- course→session 绑定双轨：已建会话经 `updateSessionOrganization(sid, {course_id})` 即时写（`ChatWorkspace.tsx:1474-1487`，服务端存进会话偏好 `web/lib/session-api.ts:105`，侧栏分组读 `web/lib/sidebar-entries.ts:117`）；未建会话则每个 turn 配置携带 `_course_id`（`ChatWorkspace.tsx:2009-2016` → 线格式 `web/features/chat/controllers/buildStartTurnInput.ts:110`）。启动默认值只注入全新会话（`:1402-1426`）；交接卡片解析在 `web/lib/course-handoff.ts:118-195`。
- 已知坑（修卡线索，截至基线）：课程详情页删除仍是 `deleteCourse(...).then(() => router.push("/courses"))` 无 catch（`[courseId]/page.tsx:413-415`）——删除失败时用户被静默跳走；补丁在 myfork 分支 `myfork/fix/course-delete-visible-error`（commit `1cac383c5`，含 `deleteBusy`/`deleteError` 与 `web/tests/course-detail-delete.spec.tsx`），main 尚未包含。

## 四、本地持久化与失效策略

### 4.1 两套体系：typed v2 层在休眠，现实全是 raw 键

- typed 层（`web/shared/storage/`）：命名空间 `deeptutor:v2:`（`keys.ts:1`，物理键 `deeptutor:v2:<scope>:<name>` `:18-20`）；值带版本信封 `{version, value, writtenAt}` 与迁移（`schema.ts:3-47`，读时迁移并回写 `store.ts:52`）；`StorageStore.read/write`（`store.ts:44/:59`）、跨标签 `subscribe`（`:147-164`）、按命名空间清理 `clearNamespace`（`:130-145`）。
- **但生产代码零调用**：`defineStorageKey`/`dynamicStorageKey` 只有测试用（`web/tests/storage.test.ts:51,113,148`）；`browserStorage.read(/.write(/.remove(/.subscribe(/clearNamespace` 在 app 代码中无一处调用。现实是所有模块走 `readRaw/writeRaw/removeRaw`（`store.ts:81-128`），这些 API **绕过命名空间与信封**，物理键就是原始字符串。
- 直连 `window.localStorage`（绕过 store）只有三处：预渲染主题脚本 `web/components/ThemeScript.tsx:14,31,34`、`web/lib/chat-markdown-note.ts:75,105`、co-writer 草稿（调用方注入 `window.localStorage`，`web/features/co-writer/components/CoWriterWorkspace.tsx:305,341,366` 等）。

### 4.2 键清单（逐一核对现行代码）

| 模块 | 键 | scope | 定义锚点 | 失效/清理 |
|---|---|---|---|---|
| 应用壳 | `deeptutor.activeSessionId.tab:<wsId>` | session | `web/context/app-shell-storage.ts:73,246,256` | 置 null 时移除 `:258`；随标签页消亡 |
| 应用壳 | `deeptutor-language` / `deeptutor-response-language` | local | `:74,:75`（读 `:161,:178,:210-222`） | 无 TTL；"存在与否"本身是服务器值采纳的门（`:175-182`） |
| 应用壳 | `deeptutor.sidebarCollapsed` | local | `:76` | 无 |
| 应用壳 | `deeptutor.chatResponseTimeout` | local | `:77-78`（钳制 30–1800 `:88-98`） | 服务器 `chat_response_timeout` 的镜像，随设置加载覆盖 |
| 应用壳 | `deeptutor.code-block-theme` / `…-show-line-numbers` / `…-wrap-long-lines` | local | `:79-83` | 无 |
| 主题 | `deeptutor-theme` | local | `web/lib/theme.ts:10`（直连 `ThemeScript.tsx:14,31,34`） | 无 |
| 侧栏布局 | `deeptutor.sidebar.navLayout` / `sessionOrder` / `collapsedGroups` / `moreExpanded` / `width` | local | `web/lib/sidebar-layout.ts:37-39`、`SidebarNav.tsx:61`、`useSidebarResize.ts:12` | navLayout 读时剔除未知 id（`sidebar-layout.ts:101-122`） |
| 聊天工作区 | `dt:chat:viewer-panel`、`dt:viewer-width` | local | `ChatWorkspace.tsx:430`、`SessionViewerPanel.tsx:121` | 无 |
| 聊天工作区 | `dt:chat:capability-config:<sessionId>` | local | `ChatWorkspace.tsx:501-504`（读 `:513`，写 `:537-546`） | 按会话键永不删除（每会话一枚，损坏即忽略 `:528-530`） |
| 聊天笔记 | `dt:chat-markdown-note:<owner>:<sessionId|pending>` | local（直连） | `web/lib/chat-markdown-note.ts:26,33-37` | `pending` 在会话建立后被正式键取代并删除（`:85-95`） |
| 未发送提交 | `deeptutor.failedSubmissions`（legacy map）、`…fallback.<sid>`（session）、`…record.<sid>:<subId>`、`…cleared.<sid>:<subId>`（墓碑）、`…binding.<sid>:<subId>` | local→session 溢出 | `web/lib/failed-submissions.ts:22-26,29-50` | **TTL 7 天**（`:27`，检查 `:116-134,182-187`）；ack 后删 `:385-386`；配额满逐级降级 local→session→纯文本（`:195-217`）；会话槽可为 `draft:<wsId>`（`ChatStateAdapter.tsx:519-521`） |
| 待发提示 | `deeptutor.pendingPrompt[.<scope>]` | session | `web/lib/pending-prompt.ts:23,25-28` | **读一次即删**（`:44-45`）；scope：`""`/`chat`/`mastery_path`/`immersive_reading` 等 |
| 语音 | `deeptutor.voiceAutoplay.session:<scope>` / `…prompted:<scope>` | session | `web/hooks/useVoiceAutoplay.ts:14-15` | 无 |
| 阅读 | `dt.reader.history.<sid>`（上限 50 条）、`dt.reader.textPreferences`、`dt.reader.autoJump`、`dt.reader.companionWidth` | local | `web/lib/reading-location-history.ts:5,177-202`、`reading-display-preferences.ts:20`、`ReaderPane.tsx:88`、`ReadingWorkspace.tsx:191` | 无；损坏解析回退空（`reading-location-history.ts:138-175`） |
| 阅读 | `reading-learning`（**唯一无前缀键**） | session | `web/components/reading/workspace/useLearningMode.ts:12` | 关闭时删 `:78`；恢复时校验 payload 内 workspaceId，不符即弃（`:15-38`） |
| 书籍 | `deeptutor.book.pendingChapterEnd`、`deeptutor.bookChat.width` | session / local | `PageReader.tsx:48`、`BookChatPanel.tsx:130` | **TTL 30s**（`PageReader.tsx:49`，过期即删 `:74,:79`） |
| 知识库 | `knowledge:history:v1`（每 KB 20 条上限） | local | `web/hooks/useKnowledgeHistory.ts:22-25` | 无 TTL；重命名/删除时重写（`:115-136`）；跨标签走原生 storage 事件（`:81-89`） |
| 精通 | `dt.mastery.outline` | local | `MasteryStudy.tsx:67` | 无 |
| 观看 | `watching-browser:<userId|'local'>` | session | `web/components/watching/WatchingBrowser.tsx:59` | 断开时删除（`:168`） |
| 合作伙伴 | `partner-session:<accountId>:<partnerId>`（legacy 无 accountId）、`deeptutor:partner-group:<id>:session` | local | `web/lib/partner-session.ts:10-14`、`partner-groups-api.ts:199` | 无；legacy 迁移需服务器归属确认（`partner-session.ts:47-58`） |
| 记忆 | `dt:memory:active-run:<L2|L3>:<key>`、`dt:memory:banner-dismissed` | local | `web/components/memory/useMemoryRun.ts:57-61`、`MemoryArchivedBanner.tsx:9` | 运行结束删除（`useMemoryRun.ts:73`）；**banner 键在 `MemorySection.tsx:289` 重复定义了一份**（改键时两处都要动） |
| 面板 | `panel:<storageKey>:collapsed` | local | `web/hooks/useCollapsiblePanel.ts:23,40-44` | 无 |
| 设置 | `deeptutor:settings-return`（返回路径）、`deeptutor.settings.diagnosticsResults.v1` | session | `SettingsReturnTracker.tsx:7`、`SettingsStore.tsx:212`（读 `:425-437`，写 `:889-899`） | 返回路径每次导航覆盖；诊断刻意 tab 级 |
| 共写 | `deeptutor.co_writer.draft.v2.<docId>`（v1 迁移后删除）、`…split_ratio.v2`、`…sync_scroll.v2` | local（直连） | `web/features/co-writer/storage/drafts.ts:4-7`（校验 `:31-51`，`clearDraft :94-102`） | 版本门 + docId 门；显式清空 |
| IndexedDB | `deeptutor-workspace-drafts`（composer 草稿，键 `<userId>:<wsId>:<pathname>`，空稿删行）、`deeptutor-chat-import` v2 | IDB | `web/lib/workspace-drafts.ts:8-19,32-33`、`web/lib/chat-import/agent-store.ts:36-40` | 空稿删除 `workspace-drafts.ts:32-33`；跨工作区搬移 `:61-72` |

内存型（非存储，容易误判为持久化）：`client-cache`（Map，TTL 30s，§1.5）、`session-unread`（Set，`session-unread.ts:17`）、`llm-options-state`（reducer）、`partner-draft`/`partner-chat-draft`/`book-progress`/`mcp-store`（纯函数/无存储）。

### 4.3 失效条件只有四类

1. **TTL**：仅三处——failedSubmissions 7 天、book pendingChapterEnd 30s、client-cache 30s（另有 session/courses 15s 定制）。其余键没有时间维度。
2. **事件驱动**：读一次即删（pendingPrompt）、ack 后删（failedSubmissions.record）、运行结束删（memory active-run）、断开删（watching-browser）、null 值删（activeSessionId）。
3. **版本门**：读时校验结构/版本，不符回退默认（storage 信封 `schema.ts:25-47`、co-writer v2、`knowledge:history:v1`、capability-config 损坏忽略）。
4. **作用域键控**：换 workspace/session/user 即"逻辑失效"——键名含 `<wsId>`（activeSessionId）、`<sessionId>`（capability-config、reader.history、failedSubmissions 槽）、`<userId>`（watching-browser、partner-session）。物理键永不清理，靠键名隔离。

### 4.4 工作区切换与登出

- 切工作区**不清任何存储**：`selectWorkspace`（`web/lib/workspace-scope.ts:30-54`）只广播 `deeptutor:before-workspace-switch`（`:37`，监听者可挂 promise，如 ChatComposer 趁机把草稿写 IDB `ChatComposer.tsx:547-567`）再导航（`:52-53`）；内存态由 `WorkspaceRuntimeBoundary` 以 `key={workspaceId}` 重挂载清空（`web/components/workspaces/WorkspaceRuntimeBoundary.tsx:10-20`）。
- **登出不清存储**：`logout`（`web/lib/auth.ts:177-187`）只 POST `/api/auth/logout` + 失效内存 auth 缓存；全仓无 `localStorage.clear()`（仅测试 `web/tests/setup/rendered.ts:89-90`）。主题、草稿、failedSubmissions、partner-session 等在登出后仍留在浏览器——涉及多账号/隐私的卡要自行评估。
- typed 层的 `clearNamespace`（`store.ts:130-145`）能力已备好但没有接入点；若要做"登出清理"，这是现成钩子。

## 五、与 API 错误信封的衔接

### 5.1 规范化器（新一代，但采用率极低）

`web/shared/api/client.ts:74-109` 的 `normalizedHttpError` 把任意失败体归一成 `AppError`（`web/shared/api/errors.ts:8-15`）：code 取顶层 `error_code` → `detail.error_code` → 兜底 `http_<status>`（`client.ts:97-100`）；message 取 `message`/`detail`(字符串)/`detail.message`（`:59-72`）；`retryable` 取 body 标志，缺省按 408/429/5xx（`:85-95`）；`correlation_id` 取 body 或 `x-correlation-id`/`x-request-id` 头（`:51-57,104-106`）。网络失败/中止映射 `network_error`/`request_aborted`（`:132-147`）。抛出 `ApiError`（`errors.ts:17-41`）。
**生产采用只有 2 处**：`web/shared/api/runtime.ts:8` 与 `web/features/runtime-status/api.ts:9`（另 chat 入参校验 `web/features/chat/controllers/buildStartTurnInput.ts:24-31` 用 `scope:"turn"`）。

### 5.2 遗留主流：apiFetch + 各领域手写解析

`web/lib/api.ts:1-6` 只是转出 `@/shared/api/client` 的 5 行垫片；约 40 个 `web/lib/*-api.ts` 直接用 `apiFetch`（裸 `Response`），各自把后端信封解析成**领域错误类**（均不是 `ApiError`）：`McpApiError`（`detail:{code,message}`，`web/lib/mcp-api.ts:280-313`）、`BookApiError`（含 409 `current_revision`，`web/lib/book-api.ts:25-35,59-92`）、`CodexOAuthApiError`（`payload.detail?.code`，`web/lib/codex-oauth.ts:53-61,130-169`，code→i18n `:229-247`）、阅读素材行级 `error_code`（`web/lib/reading-failure.ts:11-24`）、设置就绪行级 `detail_code`（`web/lib/settings-readiness.ts:41,212-217`）。`asJsonOrThrow`（`client.ts:212-224`，抛普通 `Error`）被 personas/skills 使用。后端 `detail.code` 发射点全表见 `docs/guides/web-contracts.md` §5，不重复。

### 5.3 UI 呈现：无 ErrorBoundary，三种局部模式

- 全局 toast：`notify`（`web/lib/notifications.ts:30-49`）→ `ToastViewport`（挂载 `web/app/layout.tsx:63`）。典型：书籍路由 `web/app/(workspace)/learning/books/BooksRoute.tsx:179-180`；chat 断连 `ChatStateAdapter.tsx:2210-2228`。
- 行内 alert：通用 `InlineAlert`（`web/shared/ui/InlineAlert.tsx:26-55`）；学习域 `LearningErrorState`（`web/components/learning/LearningShell.tsx:98-118`）；课程页失败块（`CoursesShelf.tsx:143-157`）。
- chat 三处状态化横幅：终错卡（`web/features/chat/messages/ChatMessageList.tsx:2333-2359`，Retry/Resend，可重试性读 `event.metadata.retryable :2261-2264`）、孤儿失败 turn（`:2220-2241`）、提交失败横幅（`ChatWorkspace.tsx:2708-2737`）。
- **没有** `app/error.tsx`/`global-error.tsx`/`componentDidCatch`——未捕获渲染错误无人兜底；补测卡若依赖错误边界，现状是不存在。

### 5.4 WS 错误通道与 HTTP 完全分离

`TurnRuntimeClient` 上报 `command_ack` 拒绝与 `protocol_error`（`TurnRuntimeClient.ts:326-330,334-339`，带 `error_code`+`retryable`）→ `toStreamEvent` 转成 `type:"error"` 的 StreamEvent（`UnifiedTurnClient.ts:43-65`，终态码集合 `:47-50`）→ reducer 侧 `handleRunnerEvent` 终错分支（`ChatStateAdapter.tsx:2136-2175`）：regenerate 拒绝先回滚乐观气泡（`RESTORE_ASSISTANT :2140-2156`），再 `STREAM_END {status:"failed", submissionFailed}`（`:2168-2174`）。手动重发判定 `decideFailedTurnReplay`（`web/lib/chat-resend.ts:73-120`，按 `client_submission_id` 对账）；未发送文本的持久化与恢复见 §4.2 failedSubmissions 行（存 `:2961-2968`，恢复 `:2618-2625`）。

## 六、修卡/补测速查

| 要改的东西 | 去哪 | 现成测试 |
|---|---|---|
| 会话消息/流式/失败恢复 | `ChatStateAdapter.tsx` action→reducer；UI 在 `ChatWorkspace.tsx`/`ChatMessageList.tsx` | `web/tests/turn-lifecycle-characterization.test.ts`、`turn-reconcile.test.ts`、`turn-runtime-client.test.ts`、`unified-turn-client-errors.spec.ts`、`chat-failed-submission-recovery.spec.tsx`、`chat-idle-recovery.test.ts`、`chat-resend-failed-turn.test.ts` |
| 应用壳偏好 | `app-shell-storage.ts`（键+读写）+ `AppShellContext.tsx`（状态+事件） | `app-shell-storage-code-block.test.ts`、`app-shell-language-bootstrap.test.ts`、`app-shell-code-block-hydration.spec.tsx` |
| 设置草稿/应用 | `SettingsStore.tsx` 写路径表（§1.4）；子页接 `useStagedSettings` | `settings-context-ui-sync.test.ts`、`settings-provider-slices.test.ts`、`settings-unified-draft.spec.tsx`、`model-settings-store.spec.tsx` |
| 课程 | `courses-api.ts`（记得 mutation 后 `invalidateClientCache("courses:")`）；注意无事件总线 | `courses-shelf.spec.tsx`；删除失败用例仅在 `myfork/fix/course-delete-visible-error` |
| 新增持久化键 | 优先走 `web/shared/storage` typed API（能力齐但无人用，键名规范 `deeptutor.*`/`dt.*`/`dt:*`）；至少写进 §4.2 同款清单 | `storage.test.ts` |
| 错误呈现 | HTTP 新代码走 `requestJson`+`ApiError`；存量领域继续领域错误类 + code→文案 helper（§5.2） | `api-client.test.ts`、`session-load-failure.test.ts` |
| 数据拉取缓存 | `withClientCache` 键自动带 workspace；跨域失效用 `invalidateClientCache(prefix)` | `llm-options-state.test.ts`、`llm-options-transport.test.ts` |

## 七、导读自身验证

- 所有锚点在基线 commit 逐一抽查核对（方法：`sed -n '<line>p' <file>` 比对声明行），抽查 100+ 条，覆盖每节首锚点。
- 持久化键清单来源：`grep -rn "localStorage\.\|sessionStorage\.\|readRaw\|writeRaw\|removeRaw\|listRaw" web/` 全量回收后按模块归组，非抽样。
- 本文档只新增 `docs/guides/web-state.md`，未改任何产品代码。

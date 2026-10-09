# WS 消息契约前后端对照扫描（web/lib 事件流）

- 任务: AGEN-1269（只读扫描，不改任何产品/测试代码）
- 基线: `origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14）
- 日期: 2026-10-09
- 去重边界: `scan-ws-endpoints` 覆盖后端端点轴；`test-websocket-progress` 覆盖进度 WS 单测。本卡只做「web/lib 解析的 payload 字段 ↔ 后端广播结构」对照轴。
- 复算方式: 所有行锚点在基线 commit 上用 `sed -n '<lines> <file>'` 可逐条复验；结构化数据见同目录 `contracts.json`，校验和见 `SHA256SUMS`。

## 结论

PASS。共对照 **26 条**，其中 **19 条两侧一致**、**4 条发现分歧/不对称**、**3 条按设计无线上契约**（客户端内部总线/纯传输层）。分歧中 **0 高危、0 中危、2 低危、4 信息级**。未发现事件名拼写分歧；未发现会导致当前功能错误的漂移。

## 高危点

无。

## 分歧清单（按严重度）

### F-M1（低）web MasteryEvent 镜像缺 `path_id` 字段 — 类型缺失

- 前: `web/lib/learning-api.ts:206-216`（镜像注释在 :204）
- 后: `deeptutor/learning/models.py:335-345`（`path_id` 在 :337；随 `model_dump(mode="json")` 上线，`deeptutor/api/routers/mastery_path.py:845,897`）
- 影响: 注释声称镜像 models.py，但接口缺 `path_id`。运行时字段存在、TS 结构类型多余字段被忽略，当前无功能影响；但镜像声明不准确，消费方读 `event.path_id` 会得到类型错误。
- 建议: web 接口补 `path_id: string`（纯类型/文档级修改）。

### F-B1（低）book-ws-operation 容错读取后端从不发送的 `message`/`detail` 字段 — 字段漂移

- 前: `web/lib/book-ws-operation.ts:34-39`（`event.content ?? event.message ?? event.detail`）
- 后: `deeptutor/api/routers/book.py:1780-1807`——WS error 事件线上只带 `content`（可选 `status`/`code`/`current_revision`）；HTTPException 的 `detail` 字典在 :1790-1803 被拍平成 `content`+`code`+`current_revision`，`message`/`detail` 从不作为线上字段出现。冲突码来源 `:301-346`（`book_revision_required` / `book_revision_conflict`）。
- 影响: 无当前功能缺陷（`content` 恒存在），但死容错会误导后来者以为存在 `detail` 透传契约。
- 建议: 删除 `message ?? detail` 回退，或注明仅为对非 DeepTutor socket 的宽容。

### F-B2（信息）`confirm_spine` WS action 无 web 消费方 — 不对称

- 前: `web/lib/book-api.ts:183-203`（confirmSpine 走 REST `/books/confirm-spine`）
- 后: `deeptutor/api/routers/book.py:1692-1718`（WS 分支发送 `confirm_spine_result`）
- 影响: 后端独有的结果事件类型，web 端无解析路径；非缺陷，属需人工保持同步的平行面。

### F-B3（信息）`BookWsEvent` 对序列化信封不落类型 — 类型缺失

- 前: `web/lib/book-ws-operation.ts:1`（`{type: string, [k: string]: unknown}`）；`seq` 用 `Number()` 强转（`web/lib/use-book-stream.ts:92-96`）
- 后: `deeptutor/api/routers/book.py:1467-1476`（`_serialize_event` 恒发 `type/source/stage/content/metadata/seq/timestamp`）
- 影响: 通用事件通道的刻意宽松，但 `seq/timestamp/source` 契约对类型检查不可见，后端改名不会被 web 构建捕获。

### F-B4（信息）客户端自造 `{type:"__reset"}` 哨兵走同一事件通道 — 类型卫生

- 前: `web/lib/use-book-stream.ts:88`
- 后: 无后端发送方
- 影响: `BookWsEvent` 名义上描述线上事件，但同一回调里混入客户端合成值，消费方需知道特判。

### F-D1（信息）三个模块按设计无线上契约 — 范围说明

- `web/lib/session-events.ts:10`（`sessions:changed`）与 `web/lib/co-writer-events.ts:8`（`co-writer:changed`）是 window EventTarget 客户端内部总线（模块头注释自述）；`web/lib/reconnecting-websocket.ts:152-156` 仅透传 `onMessage`，不解析 payload。无前后端漂移可能，记录以覆盖本卡轴。

## 一致对照（摘要）

| 轴 | 前锚点 | 后锚点 | 结论 |
| --- | --- | --- | --- |
| mastery 端点 `/ws/mastery-paths` | `web/lib/mastery-ws.ts:8` | `deeptutor/api/main.py:634-638` + `deeptutor/api/routers/mastery_path.py:791` | 一致 |
| mastery subscribe `{type,path_id,after_revision}` | `mastery-ws.ts:40-49`（:47 钳制 >=0） | `mastery_path.py:855-876`（服务端再钳到持久头 :874-876） | 一致，语义兼容 |
| mastery `subscribed` | `mastery-ws.ts:10-15,67-77` | `mastery_path.py:892-899` | 一致 |
| mastery `topic_event`（含 reason/sequence） | `mastery-ws.ts:17-24,78-84` | `mastery_path.py:838-847`；Signal 字段 `deeptutor/learning/event_hub.py:21-23` | 一致 |
| mastery `error {type,content}` | `mastery-ws.ts:26-29,64-66` | `mastery_path.py:857,863,867` | 一致 |
| books 端点 `/ws/books` | `web/lib/book-api.ts:23`、`web/lib/use-book-stream.ts:8` | `deeptutor/api/main.py:645` + `deeptutor/api/routers/book.py:1519` | 一致 |
| books subscribe `{type,book_id,after_seq}` | `use-book-stream.ts:56-69` | `book.py:1609-1630`（`after_seq` :1615，reset 规则 :1618-1619） | 一致 |
| books `subscribed` ack `{book_id,latest_seq,reset}` | `use-book-stream.ts:78-91` | `book.py:1622-1629` | 一致 |
| books error `status/code/current_revision` | `book-ws-operation.ts:110-126` | `book.py:1780-1807` | 一致（消息文本取 `content`） |
| create / create_result | `book-api.ts:153-161` | `book.py:1632-1662` | 一致 |
| confirm_proposal / confirm_proposal_result | `book-api.ts:162-182` | `book.py:1664-1690` | 一致 |
| compile_page / compile_page_result | `book-api.ts:210-225` | `book.py:1720-1745` | 一致 |
| regenerate_block / regenerate_block_result | `book-api.ts:226-249` | `book.py:1747-1775` | 一致 |
| books 事件 `metadata.kind`（含 content 回退） | `use-book-stream.ts:139-143` | `deeptutor/book/streaming.py:94-117`（kind 清单 :104-110） | 一致 |
| books 事件 `metadata.page_id` | `use-book-stream.ts:146-151` | `deeptutor/book/compiler.py:163-168,245-257,275-283,306-313,415-431` | 一致 |
| 统一 StreamEventType 15 值并集 | `web/contracts/generated/turn-protocol.ts:172-190` | `deeptutor/core/stream.py:12-28`（schema 源 `deeptutor/api/contracts/turn_protocol.py`） | 一致（web 侧为生成物） |
| 统一 StreamEvent 信封可选性 | `web/features/chat/model/protocol.ts:31-40` + `turn-protocol.ts:565-578` | `core/stream.py:39-60`（`to_dict` 恒发全字段） | 一致，web 收紧被满足 |
| content 门控 `call_kind` 两值 | `web/lib/stream.ts:16-28` | `deeptutor/core/trace.py:13-19`（`ANSWER_BEARING_CALL_KINDS`），发射点 `deeptutor/agents/loop/agent_loop.py:443,878`；并锁测试 `tests/core/test_answer_call_kinds.py` | 一致 |
| 撤回标记元数据（`trace_kind/call_state/answer_visible/call_id`） | `stream.ts:3-10,30-63` | `agent_loop.py:1010-1028,1619-1636,1676,1706-1709`；`call_id` 来自 `core/trace.py:30-52`，合并 `core/trace.py:84-91` | 一致（撤回事件确带 `call_id`） |
| 工具元数据嵌套 `metadata.tool_metadata` | `web/lib/tool-event.ts:5-11,28-56` | `deeptutor/runtime/agentic/tool_dispatch.py:861-867` | 一致（:867 嵌套点，与 tool-event.ts:6-7 引用互证） |

## 边界与未尽事项

- 本次为静态只读对照，未运行服务、未做联机 WS 抓包；行锚点以基线 commit 为准。
- 统一回合协议（unified turn protocol）web 侧类型为 `deeptutor/api/contracts/turn_protocol.py` 导出生成（`web/contracts/README.md`），该轴的结构性漂移风险由生成链兜底；本次仅复核生成物与 `core/stream.py` 的一致性。
- books 流事件回放/游标行为细节（`StreamBus.subscribe(after_seq)` 语义）归 `test-websocket-progress` 卡轴，本卡只记录字段契约。

## 交付物

- `contracts.json` — 26 条对照 + 6 条 finding，结构化可复算
- `SHA256SUMS` — 本目录文件校验和
- 本报告 `report.md`

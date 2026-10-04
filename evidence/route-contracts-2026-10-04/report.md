# 前后端 API 路由契约对照扫描报告

- 日期: 2026-10-04
- 基线: origin/main @ `ef2d9e5c3` (release: v1.6.12)，已对照 origin/dev 复核关键发现
- 分支: `scan/route-contracts-2026-10-04`（只读扫描，未改任何业务代码）
- 方法: 静态解析。后端 = `deeptutor/api/main.py` 挂载前缀 × `deeptutor/api/routers/*.py` 路由声明；前端 = `web/` 源码中 `/api/`、`/ws`、`/files/` 字符串/模板字面量调用点。未启动任何服务、未导入 FastAPI app。
- 产物: `backend_routes.tsv`（后端路由表）、`frontend_calls.tsv`（前端调用点）、`comparison.tsv`（对照明细）、`extract_backend_routes.py` / `extract_frontend_calls.py` / `compare_routes.py`（可复现脚本）

## 总体结论

| 维度 | 结果 |
|---|---|
| 后端有效路由 pattern | 534 个（HTTP 525 + WebSocket 9） |
| 前端调用点（排除 proxy 策略/测试/Next handler 转发层） | 1083 处 |
| 后端路由被前端引用 | 531/534（未引用的 3 个为 `/`、`/health/live`、`/health/ready`，属基础设施端点，合理） |
| **路径漂移（404 级）** | **1 项（高风险）**：统一会话 WebSocket，详见 F1 |
| 方法不匹配（405 级） | 0 项（自动比对 16 个初报，逐一人工复核均为误报；见「方法比对说明」） |
| 历史 issue #1242（`/api/v1/` 前缀漂移） | 已修复：前端生产代码已无 `/api/v1/` 调用，且有守卫测试（`web/tests/no-v1-chat-surface.test.ts`、`web/tests/e2e/learning-progress.audit.ts:113`） |
| 历史 issue #1228（403 被遮蔽为空态） | 客户端层已修复：`web/lib/courses-api.ts:131-150` `expectJson` 对非 2xx 抛 `ApiError`（含 status/retryable），不再静默返回空数组 |

## F1（高风险）统一会话 WebSocket 路径漂移：前端连 `/ws`，后端只挂 `/ws/ws`

双侧证据：

- 前端连接 `/ws`：
  - `web/features/chat/transport/TurnRuntimeClient.ts:127` — 默认 `url: scopedUrl("/ws")`，构造处 `web/features/chat/transport/UnifiedTurnClient.ts:99` 未覆盖该默认值
- 转发层原样透传（不重写路径）：
  - `web/lib/proxy-policy.ts:37-39` — `isWebSocketPath("/ws")` 为真
  - `web/proxy.ts:68` — `NextResponse.rewrite(new URL(pathname + search, API_BASE_URL))`，路径不变
- 后端唯一匹配的路由在 `/ws/ws`：
  - `deeptutor/api/routers/unified_ws.py:43` — `@router.websocket("/ws")`（router 无 APIRouter prefix，见 `unified_ws.py:25`）
  - `deeptutor/api/main.py:784` — `app.include_router(unified_ws.router, tags=["unified-ws"])`（**无 prefix**）
  - 合成有效路径 = `` + `/ws` = `/ws/ws`

影响面：聊天主流程（`web/features/chat/ChatStateAdapter.tsx:2187`）、quiz 追问（`web/context/QuizFollowupContext.tsx:359`）、whisper 页（`web/app/(workspace)/whisper/page.tsx:135`）、书籍对话（`web/app/(workspace)/learning/books/components/BookChatPanel.tsx:117`）均经 `UnifiedTurnClient` 走该 socket。握手打到 `/ws` 无路由（`redirect_slashes=False`，无 307 兜底）→ 客户端进入无限重连。

溯源：`fc39543bc`（"feat: integrate frontend backend and canonical routes"）同一提交内把前端默认 url 改为 `"/ws"`、后端 include 从 `prefix="/api/v1"` 改为无 prefix，但 unified_ws.py 内的路由路径仍是 `/ws`，两侧错开一级。`origin/dev` 上两处与 main 完全一致（dev: `unified_ws.py:43`、`main.py:784`、`TurnRuntimeClient.ts:127`），dev 同样存在。

测试盲区：`tests/api/test_unified_ws_workspace_binding.py:68` 直接调用 handler 函数，绕过了路由匹配；前端测试只断言策略函数（`web/tests/proxy-policy.test.ts:38`），无端到端路径契约测试。

修复建议（二选一，供修复卡决策，本卡不改码）：
1. 后端改：路由声明改挂到 `/ws`（`unified_ws.py` 内路径改 + `main.py:784` 显式 `prefix="/ws"`，两行内），保持前端公共路径 `/ws` 不变；
2. 前端改：连接串改 `"/ws/ws"`（一行），但把实现细节暴露到前端。

补测建议：加一条轻量契约测试——断言 `unified_ws` 路由经 `app.routes` 解析后的最终 path 与前端 `TurnRuntimeClient` 默认 url 字面量一致（两侧都是纯字符串常量，无需起服务）。

人工验证命令（后端已在跑时）：
```
curl -si 'http://127.0.0.1:8001/ws' -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' | head -1   # 预期 404
curl -si 'http://127.0.0.1:8001/ws/ws' -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' | head -1  # 预期 401/非404
```

其余 WS 面均对齐：`/ws/books`（`web/lib/book-api.ts:23` ↔ `deeptutor/api/routers/book.py:1519`）、`/ws/mastery-paths`（`web/lib/mastery-ws.ts:8` ↔ `mastery_path.py:771`）、`/ws/knowledge-bases/{kb}/progress`（`web/hooks/useKnowledgeProgress.ts:174` ↔ `knowledge.py:4219`）、`/ws/questions/{mimic,generate}`、`/ws/questions/judge`（`web/lib/quiz-judge.ts:40` ↔ `quiz_judge.py:226`，经 main.py:788 `prefix="/ws"`）、`/ws/partners/{id}`、`/ws/partner-groups/{id}`。

## F2（低风险）`/api/question` 空挂载

- `deeptutor/api/main.py:603` 挂载 `question.router`（prefix `/api/question`，带 `_auth`）
- `deeptutor/api/routers/question.py:30` — `router = APIRouter()` 无任何 HTTP 路由（仅 `ws_router` 有 2 个 websocket，另挂 `/ws/questions`）
- 全仓无其他地方向 `question.router` 注册路由；前端也无 `/api/question` 调用
- 风险：无行为影响，属死挂载；后续有人往该 router 加路由时可能误以为 `/api/question` 前缀已有契约。可与 F1 修复卡合并清理（删除挂载或加注释说明）。

## F3（低风险，文案）locale 残留 `/api/v1` 字样

- `web/locales/fr/app.json:2236,2237,3072` 错误提示文案仍引用 `/api/v1/capabilities/settings`、`/api/v1/settings/providers/openai-codex/` 等旧路径（en 文案已同步与否未逐一核对）。仅为用户可见文案，不影响路由。可并入 F1 修复卡顺手修正。

## 方法比对说明

- 自动比对：`compare_routes.py` 对每个非参数化字面量做「精确路径 + 方法集合」检查，对含 `${}` 的模板只做路径对齐（方法在调用点可能由包装函数注入，不可静态确证）。
- 初报 16 个疑似方法不匹配，逐一人工复核（`app-update.ts`、`video-learning-api.ts`、`skills-api.ts`、`SettingsStore.tsx`、`learning-api.ts`、`partners-api.ts`、`multi-user/api.ts` 等）全部为相邻调用干扰的误报，实际方法均与后端一致。
- 对照明细中 `comparison.tsv` 的 `/ws`（TurnRuntimeClient.ts:127）一行被自动比对按前缀对齐判为 OK，系脚本对 WS 基座路径的对齐语义偏宽；经人工 WS 契约分析升级为 F1 漂移。原始脚本输出未改动，以保留审计痕迹。

## 局限性

- 静态扫描：运行时动态注册路由、反代层改写（本仓库 proxy.ts 为原样透传，已核对）、以及非字面量拼接的 URL（变量拼接后再 fetch）不在覆盖范围。
- 方法维度依赖调用点局部启发式，仅对非参数化精确匹配出报告，已辅以人工复核。
- 未启动服务、未导入 app（遵守只读边界），路径合成规则（mount prefix + router prefix + route path）与 FastAPI 语义一致，关键发现附人工验证命令。

## 可拆卡片建议

1. 修复卡（高优）：F1 统一 WS 路径对齐 + 契约测试（两侧常量比对，无需起服务）。
2. 清理卡（低优，可并入 1）：F2 空挂载清理 + F3 locale 旧路径文案修正。

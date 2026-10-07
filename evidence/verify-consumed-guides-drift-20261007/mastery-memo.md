# guide-mastery（docs/guides/mastery-path.md @ fcb131a96）逐结论复核

- 基线漂移：`ef2d9e5c3`（v1.6.12）→ `f07029cfc`（v1.6.13）
- 判定：仍成立 / 漂移（本体成立、行号或数字过期）/ 失效（被 v1.6.13 推翻）

| # | 导读结论（节） | 判定 | 依据（新基线 path:line） |
|---|---|---|---|
| 1 | §1 模块地图：TurnCapability/Loop/Pipeline/领域服务/存储/REST/WS/前端分层与挂载 | 仍成立 | `capability.py:57`、`learning/service.py:266`、`learning/storage.py:348`、`api/main.py:615-620` 均未动；`mastery_path.py` 锚点整体 +17（`:771`→`:788`） |
| 2 | §2 状态机：mode 三态与工具准入、quiz 交互生命周期、turn 状态集、知识点游标、路径租约 | 仍成立 | `mode.py`、`learning/{models,policy,service}.py` 未动；turn 状态常量逐字未变（`sqlite_store.py:115-117`→`:123-125`，内容相同）；`models.py:342-350` 租约模型未动 |
| 3 | §3 回合流动：绑定预处理→执行→协议注入→prompt→KB 接入 | 仍成立 | `request_preparer.py`、`capabilities/mastery/pipeline.py` 未动；`executor.py` 锚点 +6（`:141`→`:141`，`:790`→`:796`，`:935`→`:941`）；`loop.py` 协议注入段逐字保留（`:239/:299` 未动） |
| 4 | §3.1 十四个导师工具（注册表、类型映射、类→execute 位置） | 仍成立（行号 +28～+31） | 14 个工具类全部还在：`mastery_status` cls `tools.py:672`→`:700` … `mastery_leave` cls `:2283`→`:2314`；`MASTERY_TOOL_NAMES :92`→`:93`、`MASTERY_TOOL_TYPES :2678`→`:2709`。新增漂移面：选项洗牌 `_shuffle_choice_options`（`tools.py:290-316`，#1691）+ prompt 同步（`prompts/en/mastery_loop.yaml:95`），导读未覆盖、不推翻原结论 |
| 5 | §3.2/3.3 REST 速查与 WS（路由行号、`_exclusive_path_mutation`、事件流） | 仍成立（`_cancel_active_learning_turn` 语义微调：失败改 409） | 路由锚点全部平移 +17（`:439`→`:456` … `:1143`→`:1160`）；`_cancel_active_learning_turn :101-130`→`:107-146` 现改为 `cancel_turn_and_wait` 失败抛 409（`mastery_path.py:116-146`）；`unified_ws.py`、`learning/event_hub.py` 未动 |
| 6 | §4 前端组件（页面、MasteryStudy/MasteryComposer、chat 卡片、hooks/lib） | 仍成立 | mastery 页面路由文件未动；`MasteryStudy.tsx` 锚点 +15（`:418`→`:433`、`:635`→`:650`、`:830`→`:846`），改动为 additive（kbDisplayNames）；`MasteryQuestionCard.tsx`、`MasteryHandoffCard.tsx`、`mastery-*.ts` hooks/lib 未动；`ChatMessageList.tsx` 卡片渲染 `:798`→`:803`、判分收集 `:2032`→`:2067`，内容逐字保留 |
| 7 | §5 锁与持久化（activity 锁、路径租约表、SQLite 表位） | 仍成立 | `workspace/activity.py`、`learning/storage.py`、`learning/assessment.py` 未动；`sqlite_store.py` 表位 +8（`:276`→`:284`、`:313`→`:321`、`:3339`→`:3367`）；+184 行为 turn 命令 outbox/幂等 ACK 扩展，不推翻表位结论 |
| 8 | §6 #1646：删除会话可遗留持有活动锁的孤儿回合（缺口=弱运行时取消不处理 waiting_input） | **失效（已修）** | `sessions.py:486-497` DELETE 改走应用层 `cancel_turn_and_wait`，失败 409；`app/service.py:262-283` `cancel_turn` 纳入 `waiting_input` 且无租约时 `_reap_unowned_live_turn`（`app/service.py:391`）；`mastery_path.py:107-149` 同步改造。`lifecycle.py:305-323` 本身未变，但删除/管理路径已不再使用它 |
| 9 | §6 #1624：测验答案字母触发无上下文 KB 检索（播种路径不识别 mastery_answer） | **失效（已修）** | `pipeline.py:851-874` 新增 `_capability_skips_kb_seed`，KB 预播种入口 `:1484-1485` 短路；`loop.py:428-447` 新增 `skip_kb_seed`；`executor.py:953-956` 新增 `mastery_card_answered` 元数据。原锚点行均逐字保留（`pipeline.py:1458`→`:1481` 等），但行为结论已不成立 |
| 10 | §6 #1566：复习条目多时精通大纲过矮（ReviewTrail 硬封顶与布局挤压） | 仍成立 | `web/components/space/learning/ReviewTrail.tsx`、`learning/mastery/[pathId]/page.tsx`、`LearnerProfileCard.tsx` 在 `ef2d9e5c3..f07029cfc` 均无变更（变更清单核过），CSS 断言锚点原样 |

小结：10 项主要结论 = 仍成立 8 / 漂移 0 / 失效 2；锚点 115 个 = 未动 17 / 平移 98 / 失效 0；另 1 处区间内措辞更新（`mastery_loop.yaml:95`）。行号漂移为系统性 +6～+31（插入所致），全部旧行原文逐字保留，修订导读时只需重排行号并改写 §6 #1646/#1624 两节。

# Python 循环导入与函数内 lazy import 清点（AGEN-661，2026-10-05）

- 基线：origin/main `f07029cfcf2c`（v1.6.13，只读扫描，未改任何产品代码）
- 范围：`deeptutor/` `deeptutor_cli/` `scripts/`（排除 tests/conftest；共 1041 个 .py 文件，AST 解析全部成功，0 个语法错误）
- 工具：`scan_imports.py`（纯标准库：ast / json / hashlib），本目录下 `python3 scan_imports.py --repo <仓库根> --out <本目录>` 可复现
- 机器可读数据：`cycles.json` `lazy_hotspots.json` `side_effects.json`

## 1. 总览

| 指标 | 数值 |
|---|---|
| 模块级（top-level）import 记录 | 14546 |
| 函数内（lazy）import 记录 | 2219（426 个文件含 lazy import） |
| 强连通分量（SCC，≥2 模块） | 7 |
| 其中纯模块级 import 环 | **0** |
| 由函数内 lazy import 掩盖的环 | 7（最大 303 个模块） |
| import 副作用条目 | 160（其中启动路径可达 118） |

**核心结论**：代码库已经没有任何“纯模块级”import 环——但代价是把环 全部推迟到了函数内：2219 处函数内 import、426 个文件涉入，7 个 SCC 的环边全部依赖 lazy import 才能在导入期不炸。这正是 DT-22 “大量函数内 import”的系统性成因：函数内 import 不是风格问题，而是当前解开循环依赖的唯一手段，任何一处被“顺手”提到模块级，都可能当场触发 ImportError。治理应按第 6 节按卡拆解，不要全量上提。

## 2. 方法与局限

- 用 `ast` 解析每个文件，区分模块级 import 与函数/类体内 import（`TYPE_CHECKING` 块单独计数、`if __name__` 块忽略）。
- 相对 import 按所在包解析为绝对模块名；`from pkg import name` 优先解析为子模块，其次回退到包本身。仅保留仓库内部边。
- 环检测：Tarjan SCC；对每个 SCC 再在其**模块级边诱导子图**上复检是否成环，以区分“导入期就会成环”与“仅运行时成环”。每个 SCC 给出一条最短代表环路径。
- 局限：①动态导入（`importlib.import_module`）不进图，第 5.4 节单列；②子模块导入隐式执行父包 `__init__` 的级联边未画（避免假环，但意味着`__init__` 聚合导出会放大实际导入面）；③不追踪字符串拼出的模块名。

## 3. 循环导入环清单

### 3.1 纯模块级环：0 个

把 303+14+…=全部 SCC 成员间的模块级边诱导子图逐一复检，均无环。即当前 origin/main 导入期不会因循环导入直接失败。

### 3.2 lazy import 掩盖的环（7 个 SCC）

| # | 规模 | 模块级边 | lazy 边 | 判定 | 代表环（⇢=lazy 边） |
|---|---|---|---|---|---|
| S1 | 303 | 484 | 472 | 运行时环，面积极大（303 模块互达）；模块级边 484 条无环，全靠 lazy 边维持。治理见 F6/F7 | `d.agents._shared.tool_composition ⇢ d.services.session → d.services.session.turn_runtime → d.services.session._turn_runtime_shared ⇢ d.learning.topic_materials ⇢ d.services.session.source_inventory ⇢ d.services.partners → d.services.partners.runtime ⇢ d.agents._shared.tool_composition` |
| S2 | 14 | 13 | 13 | 运行时环，blocks 注册模式所致，拆卡 F5 | `d.book.blocks.animation → d.book.blocks.base ⇢ d.book.blocks.animation` |
| S3 | 2 | 0 | 2 | 运行时环，两模块互需，拆卡 F4 | `d.learning.models ⇢ d.learning.pending ⇢ d.learning.models` |
| S4 | 2 | 1 | 1 | 运行时环，两模块互需，拆卡 F4 | `d.services.rag.eval.report → d.services.rag.eval.runner ⇢ d.services.rag.eval.report` |
| S5 | 2 | 0 | 2 | 运行时环，两模块互需，拆卡 F4 | `d.services.web_source.scheduler ⇢ d.services.web_source.sync ⇢ d.services.web_source.scheduler` |
| S6 | 2 | 1 | 1 | 运行时环，两模块互需，拆卡 F4 | `d.agents.loop.agent_loop ⇢ d.agents.loop.pipeline → d.agents.loop.agent_loop` |
| S7 | 2 | 1 | 1 | 运行时环，两模块互需，拆卡 F4 | `d.textbook_struct.chapter_rebuild ⇢ d.textbook_struct.page_headers → d.textbook_struct.chapter_rebuild` |

各 SCC 明细（关键证据，完整数据见 `cycles.json`）：

**S1（303 模块）** 代表环逐边：

- `deeptutor/agents/_shared/tool_composition.py:349` lazy（函数内） `from deeptutor.services.session import get_sqlite_session_store`
- `deeptutor/services/session/__init__.py:10` 模块级 `from .turn_runtime import TurnRuntimeManager, get_turn_runtime_manager`
- `deeptutor/services/session/turn_runtime.py:5` 模块级 `from . import _turn_runtime_shared`
- `deeptutor/services/session/_turn_runtime_shared.py:478` lazy（函数内） `from deeptutor.learning.topic_materials import build_topic_materials, render_topic_manifes`
- `deeptutor/learning/topic_materials.py:286` lazy（函数内） `from deeptutor.services.session.source_inventory import _load_history_session`
- `deeptutor/services/session/source_inventory.py:970` lazy（函数内） `from deeptutor.services.partners import get_partner_manager`
- `deeptutor/services/partners/__init__.py:13` 模块级 `from deeptutor.services.partners.runtime import PartnerRunner, PartnerTurnOptions`
- `deeptutor/services/partners/runtime.py:848` lazy（函数内） `from deeptutor.agents._shared.tool_composition import admin_enabled_optional_tools, defaul`
- 该 SCC 覆盖 services/session、services/partners、services/llm、services/rag、services/workspace、learning、reading、multi_user、tools 等几乎全部业务核心；成员清单见 `cycles.json` 的 `lazy_only_sccs[0].members`。
- 其中 `__init__.py` 聚合导出贡献的模块级边（放大导入面的首要嫌疑，拆卡优先对象）：
  - `deeptutor/agents/notebook/__init__.py:3` `from .analysis_agent import NotebookAnalysisAgent`
  - `deeptutor/agents/notebook/__init__.py:4` `from .summarize_agent import NotebookSummarizeAgent`
  - `deeptutor/logging/__init__.py:3` `from .config import LoggingConfig, get_default_log_dir, get_global_log_level, load_logging`
  - `deeptutor/logging/__init__.py:4` `from .configure import configure_logging`

**S2（14 模块）** 代表环逐边：

- `deeptutor/book/blocks/animation.py:22` 模块级 `from .base import BlockContext, BlockGenerator, GenerationFailure`
- `deeptutor/book/blocks/base.py:207` lazy（函数内） `from .animation import AnimationGenerator`

**S3（2 模块）** 代表环逐边：

- `deeptutor/learning/models.py:284` lazy（函数内） `from deeptutor.learning.pending import parse_options`
- `deeptutor/learning/pending.py:20` lazy（函数内） `from deeptutor.learning.models import PendingQuestion`

**S4（2 模块）** 代表环逐边：

- `deeptutor/services/rag/eval/report.py:17` 模块级 `from .runner import SOURCE_MODE_CONTEXT, QueryEvaluation`
- `deeptutor/services/rag/eval/runner.py:28` lazy（函数内） `from .report import EvalReport`

**S5（2 模块）** 代表环逐边：

- `deeptutor/services/web_source/scheduler.py:198` lazy（函数内） `from deeptutor.services.web_source.sync import sync_source`
- `deeptutor/services/web_source/sync.py:194` lazy（函数内） `from deeptutor.services.web_source.scheduler import get_web_source_sync_scheduler`

**S6（2 模块）** 代表环逐边：

- `deeptutor/agents/loop/agent_loop.py:79` lazy（函数内） `from deeptutor.agents.loop.pipeline import AgenticLoopPipeline`
- `deeptutor/agents/loop/pipeline.py:44` 模块级 `from deeptutor.agents.loop.agent_loop import AgentLoop`

**S7（2 模块）** 代表环逐边：

- `deeptutor/textbook_struct/chapter_rebuild.py:222` lazy（函数内） `from .page_headers import page_facts`
- `deeptutor/textbook_struct/page_headers.py:18` 模块级 `from .chapter_rebuild import CHAPTER_RE, Chapter, assign_page_ranges, layout_page_count`

### 3.3 风险判定

- **无导入期爆炸风险**：现在没有任何两模块在模块级互相 import。
- **高脆弱性风险**：303 模块的大 SCC 意味着“谁先导入谁都行，但谁也不能在模块级引用谁”。任何把 lazy import 上提为模块级的改动，或新增一条跨层模块级边，都可能引入首个真环。 review 时凡见到把函数内 import 移到模块级的 PR，应对照本清单确认该边不在 SCC 内。
- **两模块小环（S3–S7）**：低风险、易拆——把环上一条 lazy 边改为参数注入/类型仅 TYPE_CHECKING 即可解除（拆卡 F4）。

## 4. 函数内 lazy import 热点 Top20

全库函数内 import 共 2219 处。下表为按出现次数排序的 Top20（次数 / 涉及文件数 / 目标）：

| # | 次数 | 文件数 | 被重复导入的目标 | 主要成因 |
|---|---|---|---|---|
| 1 | 31 | 23 | `from deeptutor.services.workspace import get_content_workspace_service` | 服务单例访问器（F6 卡） |
| 2 | 22 | 16 | `from deeptutor.multi_user.context import get_current_user` | 多用户上下文访问器（F7 卡） |
| 3 | 21 | 21 | `from deeptutor.services.path_service import get_path_service` | 服务单例访问器（F6 卡） |
| 4 | 21 | 15 | `from deeptutor.services.session import get_session_store` | 服务单例访问器（F6 卡） |
| 5 | 18 | 12 | `asyncio` | 标准库为省启动成本被下放（F8 卡） |
| 6 | 16 | 12 | `from deeptutor.services.session import get_sqlite_session_store` | 服务单例访问器（F6 卡） |
| 7 | 16 | 11 | `from deeptutor.knowledge.manager import KnowledgeBaseManager` | 跨层类引用（环 S1 内） |
| 8 | 14 | 12 | `from deeptutor.services.llm.config import get_llm_config` | 服务单例访问器（F6 卡） |
| 9 | 14 | 11 | `from deeptutor.learning.storage import LearningStore` | 跨层类引用（环 S1 内） |
| 10 | 14 | 10 | `from deeptutor.services.workspace.models import WorkspaceError` | 异常类跨层引用，可安全上提 |
| 11 | 14 | 8 | `from deeptutor.services.workspace.context import workspace_context` | 上下文管理器访问器（F7 卡） |
| 12 | 14 | 3 | `from deeptutor.services.config import get_runtime_settings_service` | 设置服务访问器（F6 卡） |
| 13 | 13 | 10 | `from deeptutor.services.workspace.context import current_workspace_id` | 上下文访问器（F7 卡） |
| 14 | 13 | 8 | `from deeptutor.services.partners import get_partner_manager` | 服务单例访问器（F6 卡） |
| 15 | 11 | 10 | `from deeptutor.services.llm import complete` | LLM 门面函数（环 S1 内） |
| 16 | 11 | 8 | `from deeptutor.multi_user.knowledge_access import resolve_kb_metadata` | 多用户访问控制（F7 卡） |
| 17 | 10 | 10 | `from deeptutor.services.model_selection.tasks import TaskKind, task_llm_scope` | 模型选择工具函数（环 S1 内） |
| 18 | 10 | 9 | `msvcrt` | Windows 平台分支（F8 卡） |
| 19 | 10 | 9 | `fcntl` | POSIX 平台分支（F8 卡） |
| 20 | 10 | 9 | `from deeptutor.multi_user.paths import get_admin_path_service` | 服务单例访问器（F6 卡） |

### 4.1 同一文件内重复 import（DT-22 症状最直接证据）

| 文件 | 同一 import 在函数内重复次数 | 行号（示例） |
|---|---|---|
| `deeptutor/api/routers/knowledge.py` | 12× `from deeptutor.services.config import get_runtime_settings_s` | 1470, 1493, 1520, 1546, 1590, 1606, 1630, 1642 |
| `deeptutor/api/routers/knowledge.py` | 6× `from deeptutor.services.config import get_kb_config_service` | 1410, 1443, 2031, 2044, 2058, 2120 |
| `deeptutor/capabilities/mastery/tools.py` | 5× `from deeptutor.learning.service import MasteryInteractionErr` | 973, 1159, 1358, 1492, 1596 |
| `deeptutor/api/routers/memory.py` | 5× `from deeptutor.services.memory.consolidator.runs import get_` | 184, 355, 365, 400, 417 |
| `deeptutor/api/routers/reading.py` | 5× `from deeptutor.services.session import get_session_store` | 770, 833, 874, 915, 928 |
| `deeptutor/api/routers/knowledge.py` | 5× `from contextlib import nullcontext` | 283, 3354, 3440, 3554, 4036 |
| `deeptutor/api/routers/knowledge.py` | 5× `from deeptutor.services.workspace.context import workspace_c` | 995, 1155, 1894, 3444, 3752 |
| `deeptutor/api/routers/knowledge.py` | 5× `from deeptutor.services.embedding.config import embedding_co` | 3356, 3540, 3556, 4001, 4038 |
| `deeptutor/capabilities/reading/capability.py` | 4× `from deeptutor.multi_user.learning_access import learning_ma` | 185, 202, 366, 440 |
| `deeptutor/app/facade.py` | 4× `from deeptutor.services.workspace.context import current_wor` | 71, 138, 160, 173 |

`deeptutor/api/routers/knowledge.py` 一处文件内同一函数级 import 重复 12 次（另有 6×、5×、5×、5× 共 5 组），是 DT-22 的典型样本。

## 5. import 副作用与启动影响

启动路径 = `deeptutor_cli.__main__` / `deeptutor.api.main` / `scripts/start_web` 等 7 个入口沿模块级边的前向闭包（443 个文件）。

### 5.1 导入期执行的真实副作用（高优先）

| 位置 | 副作用 | 风险判定 |
|---|---|---|
| `deeptutor/api/main.py:20` | `ensure_runtime_settings_files()` 在导入时创建/校验运行时设置文件 | 高：导入 API 应用即落盘；测试中 import 也会写用户目录 |
| `deeptutor/api/main.py:21` | `export_runtime_settings_to_env(overwrite=True)` 导入时覆盖进程环境变量 | 高：同进程内先 import 后启动的顺序被固化；覆盖语义对嵌入方不友好 |
| `deeptutor/api/main.py:22` | `configure_logging()` 导入时改全局日志配置 | 高：import 副作用经典反模式，且 `deeptutor_cli/main.py:29` 又配一次，双重初始化 |
| `deeptutor/api/main.py:515-526` | `init_user_directories()` 放在模块级 `try/except Exception` 里，失败静默走 fallback 只建一个目录 | 高：吞错 + 启动语义，DT-22 同症状（与 fix-init-singletons 主题相邻、位置不同） |
| `deeptutor/api/main.py:528-529` | 注释自证顺序敏感：“Import routers only after runtime settings are initialized. Some router modules load YAML settings at import time.” | 高：模块导入顺序即业务正确性，属 scan-startup-order 主题 |
| `deeptutor_cli/main.py:29,65-78` | 导入时 `configure_logging()` 并串行 register 13 个子命令模块 | 中：CLI 启动即拉起全部子命令 import 链，拖慢 `--help` 且失败点提前 |

### 5.2 导入期注册/自注册（顺序耦合）

| 位置 | 副作用 |
|---|---|
| `deeptutor/services/partner_groups/memory.py:196-197` | 模块级实例化 `SharedMemoryRegistry` 并自注册 `WhiteboardMemory` |
| `deeptutor/services/partner_groups/modes.py:181-184` | 模块级实例化 `DiscussionModeRegistry` 并注册 3 个模式 |
| `deeptutor/services/app_update.py:654` | 模块级 `_version_service = VersionCheckService()` |
| `deeptutor/services/partner_groups/manager.py:1622` | 模块级 `_manager = PartnerGroupManager()` |
| `deeptutor/services/workspace/service.py:801` | 模块级 `_service = ContentWorkspaceService()` |
| `deeptutor/config/settings.py:50` | 模块级 `settings = Settings()` |

这些单例本身构造轻，但都属“谁 import 谁触发”的隐式初始化，与 scan-startup-order 主题重叠；F1/F2 卡一并处理。

### 5.3 其余模块级实例化

共 107 处模块级赋值实例化，绝大多数为良性常量（`APIRouter`×52、`typer.Typer`×13、`httpx.Timeout`×4 等），已从拆卡清单剔除；全量明细见 `side_effects.json`。

### 5.4 动态导入（静态图外）

28 处 `importlib.import_module` / `__import__`。值得单列的：

- `deeptutor/services/config/__init__.py:51,138,142` 用 f-string 自导入子模块——若只是为了打破本包内环，可改静态 import（F9 卡）。
- `deeptutor/partners/channels/registry.py:42`、`deeptutor/runtime/registry/capability_registry.py:32`、`deeptutor/tools/builtin_specs.py:26` 等为插件/通道动态发现，属设计内，保留。
- `deeptutor/api/utils/task_log_stream.py:325`、`deeptutor/services/rag/service.py:248` 导入 `lightrag.utils`（第三方），疑为规避其导入副作用，建议注释说明。

### 5.5 平台分支与标准库下放

`msvcrt`（10 处）与 `fcntl`（9 处）在函数内按平台导入是正确做法但散落多处；`asyncio` 被函数内导入 18 处纯属可上提项（F8 卡）。

## 6. 可拆修复卡清单

> 每卡独立可交付；**改动原则：只减少函数内 import，不新增模块级跨层边**，动前先跑 `scan_imports.py` 对比 SCC 数量不增。

| 卡 | 标题 | 范围（path:line） | 风险 | 工作量 | 去重标注 |
|---|---|---|---|---|---|
| F1 | api/main.py 导入期初始化收敛到 lifespan/工厂函数（ensure_runtime_settings_files / export_runtime_settings_to_env / configure_logging 三连） | `deeptutor/api/main.py:20-22` | 高 | 中 | 与 scan-startup-order 主题重叠，拆卡需与其合并（该卡未在板上找到，见 §7） |
| F2 | init_user_directories 导入期吞错可见化（top-level try/except Exception 静默 fallback） | `deeptutor/api/main.py:515-526` | 高 | 小 | DT-22 吞错同症状；与 fix-init-singletons 主题相邻、位置不同，不重复 |
| F3 | routers/knowledge.py 函数内重复 import 收敛（12×/6×/5×/5×/5× 五组，含 get_runtime_settings_service 12 处） | `deeptutor/api/routers/knowledge.py:1470,1493,1520,1546,1590,1606,1630,1642` 等 | 中 | 中 | 无重叠；依赖 F1 先收敛（否则上提会改变导入时序） |
| F4 | 两模块小环拆除（S3-S7）：环上一条 lazy 边改参数注入或 TYPE_CHECKING | `deeptutor/learning/pending.py:20`↔`models.py`；`deeptutor/services/rag/eval/runner.py:28`↔`report.py`；`deeptutor/services/web_source/sync.py:194`↔`scheduler.py`；`deeptutor/agents/loop/pipeline.py:44`↔`agent_loop.py`；`deeptutor/textbook_struct/page_headers.py:18`↔`chapter_rebuild.py` | 低 | 小 | 无重叠 |
| F5 | book/blocks 注册模式改造：base.py 不再逐块 lazy import，改为块自注册 | `deeptutor/book/blocks/base.py:207` + blocks/*（S2，14 模块） | 中 | 中 | 无重叠 |
| F6 | 服务访问器统一访问层：get_path_service(21)/get_session_store(21)/get_content_workspace_service(31)/get_partner_manager(13) 等 Top 访问器收敛到模块级或 FastAPI Depends | `deeptutor/services/path_service.py`、`deeptutor/services/session/__init__.py`、`deeptutor/services/workspace/service.py` 等 | 中 | 大 | 无重叠；注意这些模块都在 S1 大 SCC 内，须逐边验证 |
| F7 | 多用户上下文访问器收敛：get_current_user(22×)/workspace_context(14×)/current_workspace_id(13×)/resolve_kb_metadata(11×) | `deeptutor/multi_user/context.py`、`deeptutor/services/workspace/context.py` | 中 | 大 | 无重叠 |
| F8 | 标准库函数内 import 上提：asyncio 18 处；msvcrt/fcntl 19 处改为模块顶部 `sys.platform` 分支 | 全库（热点见 §4/§5.5） | 低 | 小 | 无重叠 |
| F9 | config/__init__ 动态自导入改静态（f-string importlib 三处） | `deeptutor/services/config/__init__.py:51,138,142` | 中 | 小 | 无重叠；改前确认 loader/provider_runtime/test_runner 不回导 `__init__` |
| F10 | CLI 启动瘦身：main.py 导入期 configure_logging + 13 个 register_* 移入 main() | `deeptutor_cli/main.py:29,65-78` | 中 | 中 | 无重叠 |
| F11 | partner_groups 注册器导入期自注册改显式注册清单 | `deeptutor/services/partner_groups/memory.py:196-197`、`modes.py:181-184` | 低 | 小 | 与 scan-startup-order 主题轻度重叠，标注即可 |

优先级建议：F1 → F2 → F3（先消掉导入期副作用与最痛的重复 import）；F4/F8/F9/F11 为低风险快赢；F6/F7 大卡建议再切子卡。

## 7. 与既有卡去重说明

- **fix-init-singletons**（储备卡，覆盖 `deeptutor_cli/init_cmd.py:35`、`deeptutor/runtime/launcher.py:146` 的 PathService 重置吞错 HIGH，及 `init_cmd.py:41/47`、`launcher.py:152/158` 同模式 MEDIUM）：本扫描在这 4 处均**未**发现 import 环或 lazy 热点，无条目冲突；F2（api/main.py:515-526 的 try/except 吞错）与其“吞错可见化”主题同族但位置、机制不同，独立成卡不重复。
- **scan-startup-order**（卡上未找到，按描述理解为主题为启动/导入顺序）：本扫描 §5.1/§5.2/§5.4 的发现（api/main.py 导入期初始化三连、顺序敏感注释、导入期自注册、config/__init__ 动态自导入）与该主题高度重叠。F1/F11 已标注“拆卡需与 scan-startup-order 合并”；若该卡后续建卡，建议以本报告 §5 作为其输入之一。
- 上游 PR 撞车检查：`gh pr list -R HKUDS/DeepTutor --author @me --state open` 30 个开放分支及全量开放 PR 检索（import cycle / circular / lazy import）均无本主题条目。

## 8. 校验和

完整清单（含 report.md 本身）见本目录 `SHA256SUMS` 文件；数据与脚本文件的校验和：

```
ca4d070a7650ed12095a04baf5a5350f491658254e1caad2bb6df20df384bd7f  build_report.py
b871414711794fb4dcf3446af93b47ca5b360ac8a3775ab7ce2deb0c2f035bc6  cycles.json
3a875290791a13d698779dcb6f25534d8a81d2d814f8deef4358f0136c5b88ae  lazy_hotspots.json
bd7361631d7970e4ad445dd91c9a6378d27009c5fac5567bea583be01d3d10ca  scan_imports.py
42698f180b7a7ce82e13de9c45ab4899f6170468dcb5583b78a370f58c36c58e  side_effects.json
```

（report.md 与 SHA256SUMS 由 `build_report.py` 生成；复现：`python3 scan_imports.py --repo . --out <dir>` 后 `python3 build_report.py --repo .`）
# DeepTutor 插件系统导读：加载链路、生命周期与失败隔离

- 基线：`origin/main` @ `f07029cfc`（v1.6.13，2026-10-04）
- 对照卡：test-plugins-loader（分支 `test/plugins-entrypoint-loader-20261004`，上游 PR #1740，基于 v1.6.12 `ef2d9e5c3`；经 diff 验证，本文涉及的加载器文件在 v1.6.12 与 v1.6.13 之间完全一致，因此该分支的断言逐条适用于本文描述的 main 代码）
- 本文只读代码，不改任何实现；所有小节附 `path:line`（行号以基线提交为准）。

## 1. 总览：插件系统的三层结构

DeepTutor 的"插件"不是一个单一机制，而是共用同一套入口点（entry point）基础设施的三个层次：

| 层次 | 职责 | 核心文件 |
| --- | --- | --- |
| 基础设施 | 读入口点组、逐项导入、失败跳过 | `deeptutor/core/entry_points.py:27` |
| 发现与装配 | 把入口点对象解析成 manifest 并注册进目录 | `deeptutor/plugins/loader.py:42`、`deeptutor/runtime/registry/capability_registry.py:102` |
| 回合消费 | 每次请求按名字/上下文实例化并运行 | `deeptutor/runtime/orchestrator.py:61`、`deeptutor/capabilities/registry.py:196` |

入口点组共四代并存（能力体系内三代 + 两个独立插件面）：

- `deeptutor.extensions` —— 规范组（canonical），turn 能力与 loop 扩展都优先读它：`deeptutor/runtime/registry/capability_registry.py:26`、`deeptutor/capabilities/registry.py:21`
- `deeptutor.plugins` —— 遗留组（turn 能力），加载时发 `DeprecationWarning`：`deeptutor/runtime/registry/capability_registry.py:27`、`deeptutor/plugins/loader.py:26`
- `deeptutor.loop_capabilities` —— 遗留组（loop 扩展），同样弃用：`deeptutor/capabilities/registry.py:22`
- 独立插件面（不走上述三代）：`deeptutor.reading_extensions`（内置五个，声明在 `pyproject.toml:99-104`，加载器 `deeptutor/reading/extensions.py:22`）与 `deeptutor.partners.channels`（外部渠道插件，`deeptutor/partners/channels/registry.py:55`）

`pyproject.toml` 里没有为 `deeptutor.extensions` / `deeptutor.plugins` / `deeptutor.loop_capabilities` 声明任何内置条目——这三组纯粹留给外部包注册；内置能力走的是另一条"类路径字符串 + 懒加载"的路（`deeptutor/runtime/bootstrap/builtin_capabilities.py:51`，经 `CapabilityRegistry.load_builtins` 注册，`deeptutor/runtime/registry/capability_registry.py:84-100`）。

## 2. 插件发现与加载链路

### 2.1 入口点基础设施：`load_entry_point_group`

`deeptutor/core/entry_points.py:27-57` 是所有插件面共用的唯一管道：给定组名和一个组特定的"强转函数"（coerce），读 `importlib.metadata.entry_points(group=...)`，对每个入口点调用 `coerce(名字, ep.load())`，保留非 `None` 的返回值。

模块 docstring 明确了它的保证边界（`deeptutor/core/entry_points.py:10-12`）：第三方代码在导入时执行——这是入口点的本义——本模块只保证"一个坏插件不能阻止其他插件加载"，不保证更多。四个出口：

- 组整体读取失败 → 返回空列表 + 带 `exc_info` 的 warning（`deeptutor/core/entry_points.py:42-46`）
- 单个入口点导入或强转抛异常 → 跳过该入口点，warning 里点名组名与入口点名（`deeptutor/core/entry_points.py:48-56`）
- 强转函数返回 `None` → 视为强转方自己的"拒绝"判断，静默丢弃，不记错误（`deeptutor/core/entry_points.py:55-56`；docstring `:35-38` 要求强转方自行说明原因）
- 正常路径 → 按发现顺序返回强转结果列表（`deeptutor/core/entry_points.py:40-57`）

### 2.2 遗留中立 loader：`discover_plugins` 与 manifest 解析

`deeptutor/plugins/loader.py` 自述"领域无关"（`:1-11`）：只发现 manifest、只实例化 `TurnCapability` 子类，对外暴露两个调用点约定的函数——`discover_plugins()`（`:42-44`，读 `deeptutor.plugins` 组）与 `load_plugin_capability(manifest)`（`:47-57`）。

**manifest 解析**在 `_coerce_manifest`（`deeptutor/plugins/loader.py:60-103`），一个入口点对象按顺序尝试六种形态：

1. 本身就是 `PluginManifest` 实例（`:61-64`；名字为空时回填入口点名）
2. 可调用对象且不是能力类 → 当作 **manifest 工厂**调用（`:66-77`）：产物可以是 `PluginManifest`、能力类或能力实例
3. 能力类（`TurnCapability` 子类，`:79-80`）→ 从 `cls.manifest` 提取（`_manifest_from_capability_class`，`:106-114`）
4. 能力实例（`:82-83`）→ 从 `cap.manifest` 提取（`:117-124`）
5. 模块/对象属性 `PLUGIN_MANIFEST` 是 `PluginManifest`（`:85-89`）
6. 可调用属性 `create_capability()`（`:91-97`）——产物是实例或类均可

六种形态全不匹配 → warning（点名入口点）并返回 `None` 拒绝（`:99-103`）。`PluginManifest` 是纯静态元数据 dataclass：`name / type / description / stages / version / author / entry` 七个字段（`deeptutor/plugins/loader.py:29-39`）。

### 2.3 入口加载：`load_plugin_capability` 的门与实例化

`deeptutor/plugins/loader.py:47-57` 在真正解析 `entry` 之前有三个**结构性门**，全部在任何 import 发生之前短路：

- `entry` 为空 → `None`（`:49-50`）
- `entry` 以 `tool.py` 结尾（工具脚本不是能力）→ `None`（`:51-52`）
- `type` 已声明且不等于 `"capability"` → `None`（`:53-54`）

通过门后：`_resolve_entry`（`:139-147`）按 `"模块:属性.路径"` 拆分，`importlib.import_module` + 逐段 `getattr`；`_instantiate_capability`（`:150-161`）按四种形态实例化——已是实例原样返回、类则 `obj()`、可调用工厂则取其产物（产物是类再调一次）。

注意 `_resolve_entry` 找不到模块时**不做隔离**，`ModuleNotFoundError` 会直接抛出（PR #1740 的 `test_load_plugin_capability_propagates_missing_module` 固定了这一现状契约，见 §5.2）。发现阶段（§2.2）与实例化阶段的隔离强度不同：发现隔离、实例化不隔离。

### 2.4 能力注册：`CapabilityRegistry.load_plugins` 与 `CapabilityCatalog`

真正的装配在 `CapabilityRegistry.load_plugins()`（`deeptutor/runtime/registry/capability_registry.py:102-138`），两段式：

1. **规范组**（`:116`）：强转函数 `_accept`（`:105-114`）先用 `_turn_factory`（`:36-54`，类/工厂/实例三形态归一为 `(实例, 工厂)`）解析，再查目录去重——同名已注册则 warning"already registered; ignoring"并放弃（`:110-112`，先到先得），否则 `register()` 注册。
2. **遗留组**（`:118-138`）：动态导入 `deeptutor.plugins.loader`，拿到 `discover_plugins` 的 manifest 列表；只要有遗留插件就发 `DeprecationWarning` 提示迁往规范组（`:124-128`）；逐个跳过重名（`:130-131`）与 `tool.py`（`:132-133`），然后 `load + register`。**整个遗留块包在一个 try/except 里**（`:137-138`）——任何一个遗留 manifest 实例化抛异常，剩余全部丢弃，只记一条 debug 级"Legacy plugin loader unavailable"（短板，见 §4.2）。

注册的落点是 `CapabilityCatalog`（`deeptutor/runtime/capability_catalog.py:33-79`）：一个"只存工厂"的目录，键为 `(kind, name)`（`turn` / `loop_extension` 两种 kind，`:11`）。`register()`（`:39-63`）默认重名抛 `ValueError`，`replace=True` 时覆盖（`:47`、`:53-54`）；`create()`（`:68-70` → `entry.create()` `:29-30`）每次调用都执行工厂新建实例——**目录里没有单例**。能力注册时同时落一个 pydantic 配置模型：显式传入，或按名字查 `CAPABILITY_CONFIG_MODELS`，缺省 `EmptyConfig`（`deeptutor/runtime/registry/capability_registry.py:73`；模型表在 `deeptutor/runtime/request_contracts.py:154`）。

### 2.5 loop 扩展的发现与注册（第二条能力线）

loop 扩展（挂在聊天循环上的每回合扩展点）走同一基础设施但独立装配：

- 内置 15 个以零导入描述符声明（`deeptutor/capabilities/registry.py:49-95`），保证"不 import 也能列出名单"。
- `discover_external_loop_capabilities()`（`:152-181`）用 `@cache` 做进程级缓存，先读规范组再读 `deeptutor.loop_capabilities` 遗留组（`:173-174`，遗留有 `DeprecationWarning` `:175-180`）；`_coerce_loop_factory`（`:123-149`）做结构校验——必须有非空 `name`、可迭代的 `owned_tools`、可调用的 `is_active`（`:139-148`）；重名时内置或先到者赢，后来者 warning"shadowed"（`:156`、`:164-170`）。
- `all_loop_capabilities()`（`:196-207`）每次调用都把内置 + 外部工厂逐个 `_register_loop_entry`（`:184-193`，注册 kind 为 `loop_extension`、manifest 只含 `name`/`owned_tools`）并**新建一整套隔离实例**返回。
- loop 扩展的结构契约是 `LoopExtension` Protocol（`deeptutor/capabilities/protocol.py:38-128`）：必选 `name`（`:100`）、`owned_tools`（`:104`）、`is_active`（`:106-107`）、`system_block`（`:109-116`）、`augment_kwargs`（`:118-124`）、`pre_loop_seed`（`:126-127`）；可选钩子 `pre_loop` / `on_user_pause` / `on_user_resume` / `finish_instruction` / `tool_round_output_policy` / `final_text_override` / `rebinding_tools` 全部以 `getattr` 默认值读取（docstring `:53-97`）。`KnowledgeCapability` 子类通过类属性 `exclusive_tools=True` 独占回合（`:130-156`，`exclusive_tools` 定义 `:145`）。

## 3. 生命周期与启停

### 3.1 进程级装配：插件在什么时候被加载

加载是一次性的、懒触发的：`get_capability_registry()`（`deeptutor/runtime/registry/capability_registry.py:170-176`）在首次调用时构造单例并依次执行 `load_builtins()` + `load_plugins()`，此后不再重复。触发点有三处：

1. **API 启动**：lifespan 第一步 `validate_tool_consistency()`（`deeptutor/api/main.py:115`；函数体 `:45-70`）内部调用 `get_capability_registry()`（`:54`），并把所有 manifest 的 `tools_used` 对运行时工具注册表做差集校验，发现漂移直接 `RuntimeError` 拒绝启动（`:62-64`）。也就是说：**插件在应用启动时就被加载并参与一致性校验**。
2. **CLI**：`deeptutor plugin list` / `plugin info`（`deeptutor_cli/plugin.py:19-40`、`:42-81`）触发同一单例；`info` 还会给出能力的 `availability`（`:59-77`）。
3. **编排器构造**：`ChatOrchestrator.__init__` 默认参数取 `get_capability_registry()`（`deeptutor/runtime/orchestrator.py:58`）。

loop 侧的进程级装配点是 `@cache` 的 `discover_external_loop_capabilities`（`deeptutor/capabilities/registry.py:152`）——首次调用后缓存，测试必须 `cache_clear()`（`tests/capabilities/test_loop_registry.py:15-21` 的 fixture 专门处理这一点）。

### 3.2 回合级执行：每次 turn 的实例化

turn 能力没有"常驻实例"：`ChatOrchestrator.handle`（`deeptutor/runtime/orchestrator.py:61`）按 `context.active_capability` 用 `self._cap_registry.get(cap_name)`（`:97`）取能力，而 `get()` 走 `catalog.create`（`deeptutor/runtime/registry/capability_registry.py:140-142`）——**每回合一个新实例**，`run()` 跑完即弃（`TurnCapability.run` 是唯一必须实现的抽象方法，`deeptutor/core/capability_protocol.py:66-69`）。自动路由的 turn 还会在准备阶段把工具面收窄到该 manifest 的 `tools_used`（`deeptutor/services/session/turns/request_preparer.py:537-548`，取能力在 `:542`）。

loop 扩展同样每回合新建：`active_loop_capabilities(context)`（`deeptutor/capabilities/registry.py:210-211`）→ `all_loop_capabilities()` 新建全套实例（`:196-207`）→ 按 `is_active(context)` 过滤。聊天管线经 `_active_loop_capabilities` 消费（`deeptutor/agents/loop/pipeline.py:798-799`），在系统块注入、工具装配、pre_loop 种子、暂停/恢复等约 20 个挂点逐个调用（`pipeline.py:814`、`:827`、`:833`、`:859`、`:906`、`:929`、`:978`、`:996`、`:1170`、`:1426`、`:1763` 等）。

### 3.3 启停现状：没有声明式开关

- `PluginManifest` 没有 `enabled` / `disabled` 字段，loader 也不读任何开关（PR #1740 的 `test_plugin_manifest_has_no_enable_disable_gate` 用 `dataclasses.fields` 固定了字段全集，见 §5.2）。
- 唯一的"门"是 §2.3 的三个结构性门，且都发生在任何 import 之前。
- loop 扩展的"停"等价于 `is_active(context)` 返回 False；turn 能力的"停"等价于回合不路由到它。想要"用户可开关的插件"，当前代码里没有挂点——这是 PR #1740 刻意记录的现状（"disable-gating status quo"）。

## 4. 失败隔离

### 4.1 四层防线

1. **组读取失败**：整组返回空 + warning，应用继续（`deeptutor/core/entry_points.py:42-46`）。
2. **单个入口点失败**：导入/强转异常只跳过该入口点，warning 点名（`:48-56`）——"一个坏插件不能阻止其他插件加载"是模块唯一承诺（`:10-12`）。
3. **注册去重**：turn 侧规范组先到先得 + warning（`deeptutor/runtime/registry/capability_registry.py:110-112`），遗留重名静默跳过（`:130-131`）；loop 侧内置/先到者赢，遮蔽者 warning（`deeptutor/capabilities/registry.py:156`、`:164-170`）；目录层兜底：无 `replace` 的重名注册抛 `ValueError`（`deeptutor/runtime/capability_catalog.py:53-54`）。
4. **运行期隔离**：目录只存工厂、每回合新建实例（`deeptutor/runtime/capability_catalog.py:29-30`、`:68-70`），单个实例运行失败不会污染注册表；loop 侧 `all_loop_capabilities()` 每回合返回全新隔离集合（`deeptutor/capabilities/registry.py:196-207`）。

### 4.2 两个已知短板（都在遗留链路）

1. **实例化阶段不隔离**：`load_plugin_capability` 会把 `_resolve_entry` 的 `ModuleNotFoundError` 原样抛出（`deeptutor/plugins/loader.py:56`；无 try/except）。发现阶段隔离了，实例化阶段没有——PR #1740 的 docstring 把这定性为"current contract"。
2. **遗留块级联放弃**：`CapabilityRegistry.load_plugins` 的遗留段整体 try/except（`deeptutor/runtime/registry/capability_registry.py:137-138`），一个遗留 manifest 实例化抛异常，排在它后面的所有遗留 manifest 全部不再加载，且只留 debug 级日志。PR #1740 的 `test_legacy_instantiation_error_aborts_remaining_legacy_manifests` 复现并固定了这一点（好插件排在坏插件后面时会被连坐）。规避方式：把插件注册到规范组 `deeptutor.extensions`——规范组每个入口点的失败都在基础设施层被隔离（§4.1 第 2 条）。

### 4.3 其他插件面的隔离对照

- 渠道插件：逐入口点 try/except + warning（`deeptutor/partners/channels/registry.py:55-61`），外部插件不能遮蔽内置名（`:64-70`、`:92-95`）；导入失败会作为 UI 可见的 error 上报（`discover_all_with_errors`，`:73-90`）。
- 阅读扩展：manifest 走 pydantic 强校验（`deeptutor/reading/extensions.py:35-41`、`:92-106`），校验失败该扩展被拒；运行期还有执行锁 + 熔断（`ReadingExtensionRegistry.begin_action`，`:130` 起）。

## 5. 对照 test-plugins-loader 卡已覆盖断言

### 5.1 main 上已有的测试（v1.6.13 基线）

`tests/plugins/test_loader.py`（6 个）：

| 测试 | 断言要点 | 位置 |
| --- | --- | --- |
| `test_discover_plugins_from_capability_class` | 类形态 → manifest 字段与 `entry` 限定名 | `tests/plugins/test_loader.py:30` |
| `test_discover_skips_broken_entry_points` | 坏入口点被跳过，其余照常 | `tests/plugins/test_loader.py:49` |
| `test_load_plugin_capability_instantiates` | manifest → 实例，名字回填 | `tests/plugins/test_loader.py:66` |
| `test_load_plugin_capability_skips_tool_entry` | `type="tool"` 门返回 `None` | `tests/plugins/test_loader.py:80` |
| `test_discover_from_manifest_factory` | 工厂形态 → manifest → 实例 | `tests/plugins/test_loader.py:92` |
| `test_capability_registry_loads_plugins` | `CapabilityRegistry.load_plugins` 端到端注册 | `tests/plugins/test_loader.py:116` |

`tests/capabilities/test_loop_registry.py`（10 个，loop 侧，测试起点 `:88`-`:235`）覆盖：内置名单不变量、无插件时合并结果等于内置、外部类追加、工厂形态、内置名遮蔽告警、坏入口点跳过、非法对象拒绝、重名先到先得、`active_loop_capabilities` 含外部扩展、工具归属映射等。

环境注记（本机实测）：`test_active_loop_capabilities_includes_external`（`:220`）在本机新鲜环境下失败——内置 `setup` 能力因本地 onboarding 缺口判定为激活（`deeptutor/capabilities/setup/binding.py:242-244`），而该测试假设裸上下文无内置激活。这是 main 上既有的环境敏感断言，与本文档改动无关（本分支仅含 evidence/ 文档）。

### 5.2 PR #1740 新增的断言（`tests/plugins/test_entrypoint_loader.py`，13 个，五条路径族）

该分支一个文件、385 行、13 个测试（基线 v1.6.12，加载器代码与 main 完全一致，断言逐条适用）。相对 main 已有测试，**净新增的契约**是：

1. **正常加载族**：管道保序返回（`test_load_entry_point_group_returns_coerced_values_in_order`）；类与实例两种形态的 manifest 提取（`test_discover_plugins_normal_load_from_class_and_instance`）；规范组 `deeptutor.extensions` 注册直通 `CapabilityRegistry`（`test_registry_load_plugins_loads_canonical_extensions_group`——main 的 `test_loader.py` 只测了遗留组路径）。
2. **缺依赖族**：缺依赖入口点被跳过、其余照常且 warning 点名（`test_missing_dependency_entry_point_is_skipped_others_still_load`）；**实例化阶段不隔离**——`load_plugin_capability` 抛 `ModuleNotFoundError`（`test_load_plugin_capability_propagates_missing_module`）；遗留块级联放弃（`test_legacy_instantiation_error_aborts_remaining_legacy_manifests`，§4.2 第 2 条）。
3. **加载错误隔离族**：坏入口点被隔离且 warning 点名组与入口点（`test_entry_point_load_error_is_isolated_and_named_in_warning`）；组读取失败返回空 + warning（`test_group_read_failure_returns_empty_with_warning`）；强转 `None` 静默拒绝（`test_coercer_none_rejects_entry_point_without_error`）。
4. **重复注册族**：规范组两个入口点同能力名 → 先到先得 + warning（`test_duplicate_extension_registration_first_wins_with_warning`）；规范组已占名时遗留同名被跳过且发 `DeprecationWarning`（`test_legacy_plugin_with_taken_name_is_ignored`）。
5. **启停门现状族**：`PluginManifest` 字段全集固定、无 enabled/disabled（`test_plugin_manifest_has_no_enable_disable_gate`）；三个结构性门在任何 import 之前短路（`test_structural_gates_short_circuit_before_resolving_entry`——用"门后是坏模块"反证门先于导入生效）。

### 5.3 差异与注意

- 该 PR 尚未合入 main（2026-10-05 查询时 open）；其断言对 main 代码有效，但它记录的"现状契约"中两条短板（§4.2）本身就是**待改进项**而非理想行为。
- 分支只新增这一个测试文件，未改任何生产代码。

## 6. 新增一个插件需要实现什么

### 6.1 选型：三种形态

| 形态 | 入口组 | 适合场景 | 状态 |
| --- | --- | --- | --- |
| Turn 能力（`TurnCapability`） | `deeptutor.extensions`（推荐） | 深度模式/多步管线，整回合接管 | 规范 |
| Loop 扩展（`LoopExtension`） | `deeptutor.extensions`（推荐） | 挂在聊天循环上的每回合增强 | 规范 |
| Turn 能力（同上） | `deeptutor.plugins` | —— | 遗留，加载时发弃用告警 |
| Loop 扩展（同上） | `deeptutor.loop_capabilities` | —— | 遗留，弃用告警 |

### 6.2 最小实现：Turn 能力插件（推荐路径）

在你自己的包里（DeepTutor 主仓库外）：

```python
# my_plugin/capability.py
from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus

class HelloCapability(TurnCapability):
    manifest = CapabilityManifest(
        name="hello",              # 全局唯一；重名会被先到者挡下并告警
        description="Say hello.",
        stages=["responding"],
        tools_used=[],             # 必须都是真实注册的工具名，否则启动校验失败
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        ...
```

```toml
# my_plugin/pyproject.toml
[project.entry-points."deeptutor.extensions"]
hello = "my_plugin.capability:HelloCapability"
```

入口点值可以是类、零参工厂（返回类或实例）或实例——三种形态都会被 `_turn_factory` 归一（`deeptutor/runtime/registry/capability_registry.py:36-54`）。**不需要** manifest 工厂、`PLUGIN_MANIFEST` 属性或 `create_capability`——那些是遗留组 `_coerce_manifest` 的宽容形态（§2.2），规范组用不上。

若要接配置：在 `deeptutor/runtime/request_contracts.py:154` 的 `CAPABILITY_CONFIG_MODELS` 里没有你的名字时，注册会落到 `EmptyConfig`（`deeptutor/runtime/registry/capability_registry.py:73`）；主仓库内插件才改得到这张表，外部插件的配置面目前即空配置。

### 6.3 最小实现：Loop 扩展插件

```python
# my_plugin/loop.py
class HelloLoop:
    name = "hello_loop"
    owned_tools = ("hello_tool",)      # 元组，可为空；必须是可迭代

    def is_active(self, context) -> bool:
        return getattr(context, "active_capability", None) == "hello_loop"

    def system_block(self, context, *, language, prompts):
        return None                    # 或返回 PromptBlock

    def augment_kwargs(self, tool_name, kwargs, context):
        return kwargs                  # 为自己的 owned_tools 注入服务端私有参数

    def pre_loop_seed(self, context):
        return ""
```

```toml
[project.entry-points."deeptutor.extensions"]
hello_loop = "my_plugin.loop:HelloLoop"
```

结构校验要点（`deeptutor/capabilities/registry.py:139-148`）：`name` 非空字符串、`owned_tools` 可迭代、`is_active` 可调用，三者缺一即被拒。可选钩子（`pre_loop`、`on_user_pause`/`on_user_resume` 等）不实现也不影响加载（`deeptutor/capabilities/protocol.py:53-97`）。工具本身还需注册进运行时工具注册表，否则触发启动校验漂移（§3.1 第 1 条）。

### 6.4 检查清单

- [ ] 选对形态：整回合管线选 `TurnCapability`，聊天循环增强选 `LoopExtension`（§6.1）
- [ ] 实现必须的类/协议面：`TurnCapability.manifest` + `run`（`deeptutor/core/capability_protocol.py:64-69`）或 `LoopExtension` 六件套（`deeptutor/capabilities/protocol.py:100-127`）
- [ ] 能力/扩展名全局唯一，不与内置及已装插件重名（重名被静默或告警丢弃，§4.1 第 3 条）
- [ ] `tools_used` / `owned_tools` 只列真实注册的工具名（`deeptutor/api/main.py:62-64` 启动校验）
- [ ] 在自己包的 `pyproject.toml` 声明 `[project.entry-points."deeptutor.extensions"]`，值写 `模块:类` 或工厂（§6.2/§6.3）
- [ ] 不要用 `deeptutor.plugins` / `deeptutor.loop_capabilities`（遗留；且遗留链路有级联放弃短板，§4.2）
- [ ] `entry` 不要指向 `*.py` 脚本、`type` 不要写 `"tool"`（结构性门，`deeptutor/plugins/loader.py:49-54`）
- [ ] 插件导入期代码保持可失败——失败会被隔离跳过，但别在导入期做重活（导入即执行，`deeptutor/core/entry_points.py:10-12`）
- [ ] 验证：`deeptutor plugin list` 能看到名字；对应测试目录里补一条契约测试（模仿 `tests/plugins/test_entrypoint_loader.py` 的形态）

### 6.5 验证手段

- `deeptutor plugin list` / `deeptutor plugin info <name>`（`deeptutor_cli/plugin.py:19-81`）
- 测试范式：`tests/plugins/test_loader.py`（最小）、`tests/capabilities/test_loop_registry.py`（loop 侧，注意 `cache_clear` fixture）、PR #1740 的 `tests/plugins/test_entrypoint_loader.py`（契约级）

## 7. 未决事项

- 声明式启停（用户可见的 enable/disable）当前不存在，PR #1740 只记录现状未实现开关（§3.3、§5.2 第 5 族）。
- 遗留链路的实例化不隔离与级联放弃（§4.2）是已固定的现状契约；迁往规范组可完全规避。
- 外部插件的配置模型面当前为空（`EmptyConfig` 兜底，§6.2）；主仓库未提供按名注册外部配置模型的机制。

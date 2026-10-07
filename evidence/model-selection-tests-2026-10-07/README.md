# model_selection 单元测试说明（2026-10-07）

基线：origin/main @ f07029cfcf2c8dfccdb671cdfc343db8334f5741（v1.6.13），新 worktree + 新分支 `test/model-selection-unit-tests`。仅新增测试文件与证据，无产品代码改动。

## 覆盖场景（对应验收三类路径）

新增 4 个测试文件、35 个用例（目录 `tests/services/model_selection/`）：

| 文件 | 用例数 | 覆盖点 |
| --- | --- | --- |
| test_reasoning_efforts.py | 13 | reasoning.py 回退顺序：managed catalog 声明 > capabilities.reasoning=False > openai 兼容二值 wire 映射 > 家族默认（gemini/anthropic/openai/deepseek 等按代际区分）> capabilities.reasoning=True 兜底 > 空列表；binding 别名（google/claude/GEMINI/azureopenai/anthropic_compatible）；metadata=None 容错 |
| test_llm_option_candidates.py | 11 | llm.py 候选过滤（跳过非 dict/缺 id/缺 model 的 profile 与 model）、context_window 到 context_window_tokens 的回退与非法值丢弃、is_active_default 双 id 匹配、apply 接受 None/空 payload/原始 dict、apply 拒绝未知 profile、from_payload 拒绝非对象与半缺 id、空白裁剪、LLMSelection 透传 |
| test_runtime_selection.py | 6 | runtime.py：ResolvedLLMConfig 到 LLMConfig 的全字段转换（含 __post_init__ 对 wire_api 的归一化）、无 selection 时回退全局 get_llm_config、经 provider_runtime 解析指定 selection、垃圾 selection 拒绝（ValueError）、activate 安装 scoped config 后 reset 还原 contextvar、reset(None) 容错 |
| test_task_scope.py | 5 | tasks.py：task_kind_payload 列全 10 个 TaskKind 且分组非空、catalog 不可读时 task_llm_scope 回退 yield None、task 服务为空时回退、配置了 task 模型时安装 scoped config 并在退出后还原、激活失败（resolve 抛错）时回退且不残留 scoped config |

选择/回退/拒绝对应关系：候选选择=候选项过滤与 selection 应用（llm/tasks/runtime）；回退顺序=reasoning 五级回退链、context_window 字段回退、task override→global→inherit 链、激活失败回退；非法输入拒绝=from_payload/apply 的 ValueError 路径与垃圾 selection 拒绝（非法 override 按设计读作"未配置"而非报错，test_task_models.py 已有覆盖，此处不重复）。

## 命令与数字

- 范围内（本模块 + 关联任务模型测试）：59 passed, 0 failed（其中原有 24 个用例不回归）
  - `python -m pytest tests/services/model_selection tests/services/test_task_models.py -q -p no:cacheprovider`
- 更大范围回归：4627 passed, 33 skipped, 6 failed（78.97s）
  - `python -m pytest tests/services -q -p no:cacheprovider`
  - 6 个失败均为 origin/main 上预先存在的环境相关失败，与本模块无关；将本分支新增的 4 个测试文件从收集排除后逐组复跑，失败完全一致（llm_probe_config 2、sandbox 1、session/model_history 1、config_loader 1、runtime_storage_guard 1）。
- 测试限时：本机（macOS）无 `timeout` 二进制，用 Python `subprocess(..., timeout=900)` 等效执行 900 秒上限，两次全套运行分别用时 0.4s 与 78.97s，远低于上限。
- 解释器：仓库自带 venv（`/Users/Shared/DeepTutor/.venv`）。

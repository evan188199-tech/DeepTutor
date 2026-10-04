# 提示词模板渲染失败分支测试（AGEN-555）

基准：`origin/main` @ `f07029cfc`（release v1.6.13）。只新增测试与说明，未改任何产品代码。

## 覆盖场景（四类分支）

### 1. 变量替换与缺省
- `render_message_template`（`deeptutor/knowledge/progress_tracker.py:24`）：单/多参数替换、重复占位符全量替换、非字符串值 `str()` 强转、未使用参数忽略、空参数表与无占位符模板原样返回。
- `LoopPromptAssembler._t`（`deeptutor/agents/loop/prompt_blocks.py:253`）：键缺失回退 default、中间路径缺失回退、非字符串叶子回退、空字符串叶子按"存在值"返回（与 `prompt_text` 契约不同，已用注释固定）。
- `prompt_text`（`deeptutor/services/prompt/lookup.py:15`）：命中返回、键缺失/中间非 dict/空串/非串叶子均回退 default。
- `user_message` 默认模板与自定义模板替换、kb_seed 追加。

### 2. 缺失变量行为
- `render_message_template`：未知占位符保留 `{{name}}` 字面量；部分参数命中时只替换已知项。
- `user_message`：模板含未知命名占位符或位置占位符时回退为原始用户消息（KeyError/IndexError 分支）。
- `_runtime_context_block`：模板含未知命名占位符（KeyError）或位置占位符（IndexError）时走 fallback，模板原样保留并把真实日期拼接在尾部，模型仍能拿到真实日期。

### 3. 特殊字符按字面处理（仅断言输出契约，不含绕过样例）
- `render_message_template` 基于逐对 `str.replace`：模板与取值中的 `{}`、`{{}}`、`%s`、反斜杠一律按字面通过，不被 format/percent 语义重新解释；带空格的 `{{ name }}` 不算变量。
- `user_message`：用户文本作为 format **参数**传入，其中的花括号原样进入提示词，不会被解释。
- `_runtime_context_block`：`{{literal}}` 转义形式渲染为 `{literal}`。

### 4. 超长输入截断策略
- `ExecResult.render`（`deeptutor/services/sandbox/spec.py:112`，模型可见的 exec 结果模板）：恰好等于预算不截断；超预算保留 head+tail 各一半并带丢失字节数标记；stderr 块保留在尾部且 exit code 行始终最后；error 分支短路；timeout 追加标记。
- KB seed 截断（`agents/loop/pipeline.py:1487`，`KB_SEED_CHARS_PER_KB=4000`）：上游已有 `tests/agents/chat/test_kb_seed_context.py::test_run_clips_oversized_seed_passages` 覆盖，本卡不重复。

## 新增文件
- `tests/knowledge/test_message_template_rendering.py`（15 例）
- `tests/services/prompt/test_prompt_lookup_defaults.py`（8 例）
- `tests/agents/chat/test_prompt_template_fallbacks.py`（14 例）
- `tests/services/sandbox/test_exec_result_render_strategy.py`（10 例）

## 命令与数字
```
python -m pytest -q -p no:cacheprovider \
  tests/knowledge/test_message_template_rendering.py \
  tests/services/prompt/test_prompt_lookup_defaults.py \
  tests/agents/chat/test_prompt_template_fallbacks.py \
  tests/services/sandbox/test_exec_result_render_strategy.py
# 47 passed in 0.52s（python 3.14 / pytest 9.1.1 / pytest-asyncio 1.4.0）

ruff check <上述4文件>   # 0 error
ruff format --check <上述4文件>  # 全部已格式化
```

## 备注（观察，不属本卡修改范围）
1. `ExecResult.render` 源码中的 `"(no output)"` 占位分支当前不可达（exit code 行总是先追加进 parts）。测试按实际行为固定为"空流输出裸 exit code 行"，并在测试内注释说明；未改产品代码。
2. 本机（PDT 时区）运行上游既有 `tests/agents/chat/test_runtime_context.py` 有 3 例日期断言失败（其 fixture 固定 +08:00 时间但 `.astimezone()` 再转本地时区），`tests/services/sandbox/test_sandbox.py::test_runner_server_executes_and_truncates_output` 因本机执行环境 exit_code=127 失败。两者在不含本次新增文件的 origin/main 工作区同样失败，属预存环境性失败，与新增用例无关。新增用例的时间断言改为本地时区锚定，不受影响。

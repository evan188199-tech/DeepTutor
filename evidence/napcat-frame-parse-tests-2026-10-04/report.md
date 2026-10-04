# napcat frame self_id parsing — failing regression tests

Card: AGEN-592 · Date: 2026-10-04 · Branch: `pr/test-napcat-frame-parse`
Baseline: `origin/main` @ `f07029cfc` (release: v1.6.13)
Source evidence: branch `agent/dt22-todo-scan`, `evidence/todo-scan-2026-10-03/report.md` §7 (MEDIUM, `napcat.py:219`)

## 1. 结论（按预期失败，PASS）

新增失败测试集 `tests/services/partners/test_napcat_frame_parse.py`（10 个用例），
锁定 `NapcatChannel._dispatch_frame` 中 `self_id` 解析的现状契约。

- 运行结果：**5 failed, 5 passed**（与设计一致）
- 5 个失败全部落在同一类断言上：畸形 `self_id` 被拒绝后**没有任何日志痕迹**
  （`assert any("self_id" in line.lower() for line in log_sink)` 为 False）。
  这就是待修复的"静默吞掉"缺陷的可检面。
- 5 个通过用例是修复不得破坏的回归锁：正常帧自识别、畸形帧不抛出、
  身份不被污染、消息照常分发。
- 未改任何产品代码：`git status` 仅新增 1 个测试文件。

## 2. 缺陷定位

`deeptutor/partners/channels/napcat.py:216-220`（基线 `f07029cfc`，行号 219）：

```python
if (sid := payload.get("self_id")) is not None:
    try:
        self._self_id = int(sid)
    except (TypeError, ValueError):
        pass
```

畸形 `self_id`（如 `"not-a-number"`、`{...}`、`[...]`，均为合法 JSON，
可能来自有 bug 的 NapCat 插件/网关）命中 `except` 分支后被静默丢弃：
无日志、无状态变化。若这是连接后的第一个身份帧，`self._self_id` 保持
`None`，通道自识别静默失败。

用户可见后果（`napcat.py:327,350-353`）：`_self_id is None` 时
`self_id_str` 为 None，`at` 段永远不触发 `mentioned_self`；在
`group_policy: "mention"` 下 `_should_reply_in_group` 恒为 False，
群里 @机器人 不再得到回复。

## 3. 测试矩阵

| 类 | 用例 | 覆盖 | 现状 |
|---|---|---|---|
| TestSelfIdCapture | test_meta_event_int_self_id | 正常 int self_id 自识别 | pass |
| TestSelfIdCapture | test_message_event_numeric_string_self_id_coerced | 数字字符串强制转换 + 消息照常分发 | pass |
| TestSelfIdCapture | test_latest_valid_self_id_wins | 多帧身份以最新为准 | pass |
| TestMalformedSelfIdRejected | test_malformed_self_id_does_not_raise_set_or_stay_silent[non-numeric-string/dict/list] | 三种畸形类型不抛出、不污染身份、**必须有日志** | fail（缺日志） |
| TestMalformedSelfIdRejected | test_malformed_self_id_keeps_previous_valid_value | 畸形帧不覆盖既有有效身份 + **必须有日志** | fail（缺日志） |
| TestMalformedSelfIdRejected | test_malformed_self_id_still_dispatches_message | 身份解析失败不丢消息帧 + **必须有日志** | fail（缺日志） |
| TestMissingSelfIdFields | test_notice_without_self_id_leaves_identity_unset | 缺 self_id 字段不崩溃、身份保持未设 | pass |
| TestMissingSelfIdFields | test_self_id_null_is_skipped_by_design | 显式 null 走 `is not None` 守卫，视为"无身份声明" | pass |

夹具：`_make_channel()`（与 `test_napcat_channel.py` 同款构造）、
`_frame()`（dict → JSON 文本）、`log_sink`（loguru 自定义 sink；
loguru 不进 pytest caplog，沿用 `tests/services/llm/test_tool_argument_repair.py` 的模式）。

## 4. 复现命令与数字

```
cd /Users/Shared/DeepTutor/dt-agen592-wt
perl -e 'alarm 900; exec @ARGV' /Users/Shared/DeepTutor/.venv/bin/python \
  -m pytest -q -p no:cacheprovider tests/services/partners/test_napcat_frame_parse.py
→ 5 failed, 5 passed in 0.28s（每次失败均为且仅为日志断言）

环境基线（同一 worktree）：
  tests/services/partners/test_napcat_channel.py → 61 passed（本卡改动前）
  加本卡测试后全量回归：
  python -m pytest -q -p no:cacheprovider tests/services/partners/test_napcat_channel.py \
    tests/services/partners/test_napcat_frame_parse.py
  → 61 passed, 5 failed, 5 passed … （失败均为预期失败，见 §5）

Lint: ruff check / ruff format --check 均通过。
```

（macOS 无 GNU timeout，用 perl alarm 900 等价限时。）

## 5. 修复卡可直接领取的实施要点

目标契约（让 5 个失败转绿、5 个通过保持绿）：

1. 在 `except (TypeError, ValueError)` 分支补一条至少可见的日志，文案包含
   `self_id` 字样并附上被拒值（建议 `logger.warning("napcat: ignoring malformed self_id: {!r}", sid)`；
   测试只断言"存在提及 self_id 的日志记录"，级别与措辞可由修复卡定夺）。
2. 行为保持：畸形值不设置 `_self_id`、不抛出、消息/notice 分发不受影响、
   显式 `None` 继续走 `is not None` 守卫（不需要日志）。
3. 可选加固（超出本测试锁定范围，修复卡自行判断）：`bool` 型 `self_id`
   目前会被 `int(True)=1` 静默接受；若要拒绝需扩测试。

## 6. PR 标题与描述草稿（未向上游开 PR，由人决定）

- 标题：`test(napcat): lock self_id parsing contract for malformed frames`
- 描述：
  - 背景：todo-scan §7 指出 `napcat.py:219` 的 `except (TypeError, ValueError): pass`
    使通道自识别可静默失败（MEDIUM）。
  - 变更：仅新增 `tests/services/partners/test_napcat_frame_parse.py`
    （10 用例：3 正常自识别锁 + 5 畸形输入契约（当前失败：缺日志痕迹）+ 2 缺字段锁）。
  - 验证：`pytest tests/services/partners/test_napcat_frame_parse.py` →
    5 failed（缺日志断言）/ 5 passed；既有 `test_napcat_channel.py` 61 全绿不受影响；
    ruff check/format 通过。不改产品代码。
  - 后续：修复卡按 §5 在 except 分支补日志即可转绿。

## 7. 边界确认

- 分支：`pr/test-napcat-frame-parse`（本卡新建；推 `myfork`）。
  开工前已核对上游开放 PR 列表，无同名/同范围分支，无 napcat 相关开放 PR/issue。
- 仅新增测试与 evidence，未改产品代码、未动 main 工作区未提交内容。
- 测试均限时（alarm 900），无服务器/守护进程/后台进程。

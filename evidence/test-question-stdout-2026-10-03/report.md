# test-question-stdout-2026-10-03 · 出题路由 Tee 输出转发失败回归补测

对应卡：AGEN-433（DT-22 HIGH：`deeptutor/api/routers/question.py:131` `write` 内 `except Exception: pass`）。

## 范围

- **本卡覆盖**：`websocket_mimic_generate` 内 `StdoutInterceptor` 的标准输出转发链路。
- **本卡不覆盖**：`question.py:323`（`websocket_mimic_generate` 外层 `except Exception: pass`，error 事件发送）——已由 fix-question-ws 线（分支 `test/question-mimic-ws-error-paths-20261004`）认领。

## 涉及的吞错点（origin/main @ `ef2d9e5c3`，v1.6.12）

| 行号 | 位置 | 现状 |
| --- | --- | --- |
| `question.py:125-147` | `StdoutInterceptor.write` | `:130` `self.original_stdout.write(message)` 失败被 `:131` `except Exception: pass` 吞掉（DT-22 HIGH）；`:146` 队列侧吞 `QueueFull/RuntimeError` |
| `question.py:149-154` | `StdoutInterceptor.flush` | `:152` `original_stdout.flush()` 失败被 `:153` `except Exception: pass` 吞掉 |

后果：终端一侧转发失败完全不可见——终端缺日志、无任何告警记录，任务日志可能静默缺失（Tee 双写只剩前端一半）。

## 产物

- `tests/api/routers/test_question_tee_write.py`（新增，含 `tests/api/routers/__init__.py`）
- 本说明 `evidence/test-question-stdout-2026-10-03/report.md`

未修改任何产品代码（`git diff origin/main --stat` 为空；仅新增测试与证据目录）。

## 测试设计

复用 `tests/api/test_question_router.py` 的既有模式：以桩替换 `deeptutor.logging` / `deeptutor.services.config` 导入环境后导入真实 question 路由模块，经 `TestClient` 打 `/ws/questions/mimic`，把生成接缝 `mimic_exam_questions` 换成会 `print` 的桩，`sys.stdout` 换成可控 `_TerminalStub`（可让 `write`/`flush` 抛 `OSError`）。因此被测对象是 `websocket_mimic_generate` 内**真实的** `StdoutInterceptor` 代码路径，非复制品。

4 个用例与验收对应：

1. `test_stdout_tee_forwards_print_to_terminal_and_frontend` —— 正常转发：终端收到原文（ANSI 码原样），前端收到去 ANSI、去首尾空白副本，最后 `complete`。
2. `test_terminal_write_failure_does_not_crash_and_frontend_copy_survives` —— 底层 write 抛错不致崩溃：终端零写入，前端副本照发，任务正常 `complete`（无 error 事件）。
3. `test_terminal_write_failure_leaves_no_log_record` —— 异常被吞的可观测缺口：DEBUG 级 caplog 下，任何 logger 均无提及失败的记录，question 路由 logger 无 WARNING+ 记录。**该用例故意锁定缺口本身**；后续若修复为记录告警，须同步更新此用例。
4. `test_terminal_flush_failure_is_swallowed` —— 同族 `:153`：flush 抛错不影响 write 半边，任务正常完成，无任何日志记录。

## 命令与结果

```
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/api/routers/test_question_tee_write.py -v
→ 4 passed in 0.29s

连续 5 次重复运行：均 4 passed（无 flake）。

与既有用例合跑（回归互扰检查）：
/Users/Shared/DeepTutor/.venv/bin/python -m pytest \
  tests/api/routers/test_question_tee_write.py \
  tests/api/test_question_router.py tests/api/test_question_bank_api.py -q
→ 28 passed in 0.73s
```

## 与上游的关系

- 检索到开放 PR [HKUDS/DeepTutor#1707](https://github.com/HKUDS/DeepTutor/pull/1707)（"fix: log silently swallowed failures in five services"）：其对 `question.py` 只改 `:320` 附近 ws_callback 的 error 发送吞错（即 `:323` 项），**未触及 :131 的 `StdoutInterceptor.write`**。本卡补充的测试与该 PR 不重叠，也不冲突。
- 本卡只补测试、不改产品代码，故不与 #1707 产生合并冲突；若日后修 `:131`，用例 3 是唯一需要同步改动的断言。

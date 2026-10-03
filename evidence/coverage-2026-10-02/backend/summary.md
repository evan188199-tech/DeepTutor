# 后端 pytest-cov 摘要

命令：`pytest --cov=deeptutor --cov=deeptutor_cli --cov-report=term-missing:skip-covered --cov-report=json --cov-report=xml -q`（完整命令见 ../README.md）

## 总计
- statements: 128732, covered: 97437, missing: 31295
- 行覆盖率: **75.69%** (显示为 76%)
- 测试结果: 8615 passed / 55 skipped / 4 failed (254.48s)，4 个失败均为 origin/main 已有问题（3 个时区相关日期断言 + 1 个沙箱 runner 缺失 exit 127），与本覆盖率测量无关。

## Top 20 按缺失行数
| 模块 | 缺失行 | 总语句 | 覆盖率 |
|---|---:|---:|---:|
| `deeptutor/api/routers/knowledge.py` | 758 | 2367 | 68.0% |
| `deeptutor/partners/channels/mochat.py` | 562 | 683 | 17.7% |
| `deeptutor/partners/channels/matrix.py` | 522 | 533 | 2.1% |
| `deeptutor/book/engine.py` | 506 | 945 | 46.5% |
| `deeptutor/partners/channels/feishu.py` | 495 | 1112 | 55.5% |
| `deeptutor/partners/channels/weixin.py` | 463 | 806 | 42.6% |
| `deeptutor/partners/channels/telegram.py` | 418 | 599 | 30.2% |
| `deeptutor/agents/research/pipeline.py` | 408 | 1090 | 62.6% |
| `deeptutor/api/routers/partners.py` | 340 | 1097 | 69.0% |
| `deeptutor/book/agents/spine_synthesizer.py` | 339 | 394 | 14.0% |
| `deeptutor/knowledge/manager.py` | 329 | 1252 | 73.7% |
| `deeptutor/api/routers/book.py` | 312 | 906 | 65.6% |
| `deeptutor/runtime/launcher.py` | 295 | 886 | 66.7% |
| `deeptutor/agents/question/pipeline.py` | 283 | 823 | 65.6% |
| `deeptutor/api/routers/reading.py` | 279 | 843 | 66.9% |
| `deeptutor/agents/research/utils/citation_manager.py` | 264 | 419 | 37.0% |
| `deeptutor/partners/channels/discord.py` | 251 | 355 | 29.3% |
| `deeptutor/api/routers/co_writer.py` | 246 | 410 | 40.0% |
| `deeptutor/api/routers/memory.py` | 246 | 361 | 31.9% |
| `deeptutor/partners/channels/dingtalk.py` | 240 | 290 | 17.2% |

（完整明细见 coverage.json / coverage.xml；224 个 100% 覆盖文件已在 term 报告中 skip）

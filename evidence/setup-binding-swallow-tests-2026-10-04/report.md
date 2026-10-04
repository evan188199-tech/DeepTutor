# setup binding 吞异常边界回归测试（2026-10-04）

## 目标

为 `deeptutor/capabilities/setup/binding.py` 的两处静默吞异常点补失败测试，
先锁定现状契约防回归，并为后续修复卡提供可直接领取的断言与夹具：

- `setup_gaps`（基线 :135）：`document_parsing.engine` 规格行的
  `read()` / `choices()` 抛异常时，整个解析差距分支被 `except: pass` 吞掉。
- `mark_intro_shown`（基线 :207）：`set_ui_setting` 写入抛异常时被吞。

来源：分支 `agent/dt22-todo-scan` 的
`evidence/todo-scan-2026-10-03/report.md` §7（两处均为 MEDIUM）。

## 变更清单

- 新增 `tests/capabilities/setup/__init__.py`
- 新增 `tests/capabilities/setup/test_binding_swallow_edges.py`（12 个测试）
- 新增本 evidence 目录
- 未改动任何产品代码

## 测试契约分类

### 锁定现状契约（当前通过，修复时不得回归，9 个）

| 测试 | 锁定内容 |
| --- | --- |
| `test_unreadable_spec_table_returns_empty_tuple` | 整张规格表读取失败时 `setup_gaps()` 返回 `()`，不外抛 |
| `test_unreadable_parsing_row_keeps_shape_and_other_gaps` | 解析行畸形时结果仍为 `SetupGap` 元组、此前已算出的 embedding 差距保留、不外抛 |
| `test_missing_parsing_row_reports_no_parsing_gap` | 规格行缺失（`get` 返回 None）时不报解析差距 |
| `test_missing_embedding_selection_reports_blocking_gap` | embedding 未配置 → blocking 差距 |
| `test_text_only_parser_with_installed_alternatives_reports_count` | text_only 且有可用更强引擎 → remedy 报告数量 |
| `test_text_only_parser_without_alternatives_suggests_install` | text_only 且无更强引擎 → remedy 指向一步安装 |
| `test_strong_parser_selected_reports_no_gap` | 已选强引擎 → 无解析差距 |
| `test_mark_intro_shown_writes_true_once` | 成功路径以 `(INTRO_SHOWN_KEY, True)` 恰好写一次 |
| `test_mark_intro_shown_never_raises` | 写入失败不外抛（no-raise 契约保留） |

### 失败测试（当前失败，即修复卡要满足的可观察性契约，3 个）

| 测试 | 期望行为 |
| --- | --- |
| `test_unreadable_parsing_row_is_logged[read]` | 解析行 `read()` 抛异常时，模块 logger `deeptutor.capabilities.setup.binding` 上有 WARNING 且消息含 `document_parsing.engine` |
| `test_unreadable_parsing_row_is_logged[choices]` | 解析行 `choices()` 抛异常时同上 |
| `test_failed_intro_write_is_logged` | `set_ui_setting` 抛异常时，同一 logger 上有 WARNING 且消息含 `setup_intro_shown` |

## 运行命令与数字

```
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/capabilities/setup/test_binding_swallow_edges.py
→ 3 failed, 9 passed in 0.35s（失败即预期：可观察性契约尚未实现）

.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/capabilities/test_setup_capability.py
→ 53 passed in 0.97s（既有套件无回归）
```

测试以 900 秒限时运行（macOS 无 `timeout`，用 Python `subprocess` 包装）。

## 修复线索（给修复卡）

1. 在 `binding.py` 顶部加 `logger = logging.getLogger(__name__)`
   （仓库惯例，参考 `deeptutor/capabilities/mastery/binding.py:31`）。
2. `setup_gaps` :135 的 `except Exception: pass` 改为
   `logger.warning(..., exc_info=True)`，消息含 `document_parsing.engine`，
   保持"advisory 只记日志、不外抛、不改变返回形态"的语义。
3. `mark_intro_shown` :207 同法，消息含 `INTRO_SHOWN_KEY`。
4. 夹具已就绪：测试通过 monkeypatch
   `deeptutor.services.config.settings_spec.setting_specs` /
   `deeptutor.services.settings.interface_settings.set_ui_setting`（均为函数内
   import，补丁点即模块属性），断言按 `caplog` + 模块 logger 名过滤。
   修复落地后本文件 12 个测试应全部转绿，无需再改测试。

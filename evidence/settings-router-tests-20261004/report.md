# settings 路由读取失败回退分支 · 失败测试集说明（AGEN-420 / DT-22 MEDIUM）

## 范围与基线

- 基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），独立 worktree + 分支 `test/settings-read-fallbacks-20261004`，**未改任何产品代码**。
- 证据来源：分支 `agent/dt22-todo-scan` 的 `evidence/todo-scan-2026-10-03/report.md` §附录 A，基线行号 :518 / :2247，本基线按函数名重定位为 `load_ui_settings`（settings.py:502-520，吞错点 :518）与 `tour_status`（settings.py:2236-2249，吞错点 :2247）。
- 上游查重：HKUDS/DeepTutor 开放/历史 PR 中无覆盖这两个函数吞错行为的修复或测试（2026-10-04 检索 "settings / tour_status / load_ui_settings"）。myfork 上另有 `fix/ui-settings-corrupt-backup-154`（AGEN-154，未合并）处理同一 `load_ui_settings` 吞错点并采用"收窄 except + logger.warning + 损坏文件备份"方案，本测试集的告警断言与其兼容。

## 测试文件

`tests/api/routers/test_settings_read_fallbacks.py`，8 个用例（含参数化），矩阵如下。

| 输入类别 | load_ui_settings（interface.json） | tour_status（.tour_cache.json） | 现状 |
| --- | --- | --- | --- |
| 文件缺失 | 返回值 == `DEFAULT_UI_SETTINGS.copy()`；且**无** WARNING（新装不告警） | 返回 `{"active": False, "status": "none", "launch_at": None, "redirect_at": None}`；且**无** WARNING | PASS ×2 |
| 坏 JSON（截断 JSON / 二进制乱码，参数化×2） | 回退默认值 + 必须有引用 `interface.json` 的 WARNING | 回退 inactive 载荷 + 必须有引用 `.tour_cache.json` 的 WARNING | FAIL ×4（值断言过、告警断言红） |
| 只读/不可读（chmod 0o000，root 或无 POSIX 权限位平台 skipif） | 回退默认值 + WARNING | 回退 inactive 载荷 + WARNING | FAIL ×2 |

合计：**8 用例 = 2 PASS + 6 FAIL**；FAIL 全部停在"告警必须出现"断言，回退值断言当前已全部成立。

## 设计说明

- 失败测试的"绿目标"：修复卡在两条吞错路径上加 `logger.warning`（引用文件名）即可让 6 个红用例转绿；2 个绿用例锁定回退值，修复不得改变。
- "必须告警"用例同时断言消息中出现文件名（`getMessage()` 内含 `%s` 参数展开），不限定措辞与日志来源 logger，给修复留实现自由度；与仓库既有同类修复（notebook-index、partners-index、snapshot-skip-warn、154）的 warning 模式一致。
- 缺失文件断言"无告警"，防止修复卡走"任何回退都告警"的方向制造新装噪音。
- "只读目录"在 POSIX 上并不阻止读取目录内文件（需要的是 execute 位），因此不可读夹具落在**文件** chmod 0o000 上——这才是路由必须存活的真实 PermissionError 路径；目录 0o000 会让 `exists()` 返回 False，走的是"缺失"分支，测不到吞错点。
- root / 非 POSIX 平台：skipif 守卫（`os.geteuid() == 0`），失败集在 root CI 会缩为 6→4 红（两个 unreadable 跳过），属预期。

## 运行命令与结果

```
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/api/routers/test_settings_read_fallbacks.py -v
# 6 failed, 2 passed（详见 pytest-run.txt，完整输出在附件）
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/api/routers/test_settings_read_fallbacks.py tests/api/test_settings_router.py -q
# 6 failed, 73 passed —— 既有 settings 路由测试无回归，失败仅为上述红用例
```

## 给修复卡的输入

- 建议方案（与 154 一致）：两条 `except Exception: pass` 收窄为 `except (OSError, json.JSONDecodeError) as exc:` 并 `logger.warning(...)`（含文件路径与 exc）；`load_ui_settings` 可选损坏文件备份改名（154 已实现，可复用其分支）。
- 覆盖之外的已知同族点（未测，供参考）：`json.load` 成功但顶层非 dict（如 `[]`/`null`）会走 TypeError 同一吞错点，收窄 except 时注意保留对 TypeError 的处理决策；`DEFAULT_UI_SETTINGS.copy()` 为浅拷贝，嵌套 `sidebar_nav_order` 与模块级默认共享，调用方就地修改会污染后续读取——修复卡可顺带评估，本测试集未断言。

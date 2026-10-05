# MinerU 本地引擎探测回归测试（check_mineru_installed）

日期：2026-10-04 · 基线：origin/main `f07029cfc`（v1.6.13）· 分支：`test/mineru-probe-20261004`

## 背景与来源

- 扫描证据：`agent/dt22-todo-scan` 分支 `evidence/todo-scan-2026-10-03/report.md` §7 第 204–205 行：
  `deeptutor/services/parsing/engines/mineru/local.py:36` 与 `:50` 的 `check_mineru_installed`
  在 `subprocess.run(...)` 外层 `except FileNotFoundError: pass`。
- 目标：不改产品代码，用失败测试锁定探测契约，为修复卡提供直接可领取的规格。

## 问题分析（可用性结论失真的两个具体形态）

`check_mineru_installed`（`local.py:80-111`）只捕获 `FileNotFoundError` 且对结论只回答
`"mineru" / "magic-pdf" / None` 三值：

1. **捕获面过窄 → 直接崩溃**：exec 阶段的兄弟 `OSError`（二进制存在但不可执行 →
   `PermissionError`；PATH 条目被文件占用 → `NotADirectoryError`）不在捕获范围内，
   异常直接穿透到调用方（`parse_document_with_mineru_result` 与 readiness 预检），
   "未安装"的兜底结论根本无法产生。
2. **存在性结论失真**：`mineru` 在 PATH 上但 `--version` 非零退出（pip 包装坏、依赖缺失、
   shebang 指向不存在的解释器等）时，函数落到第二个候选再返回 `None`，调用方据此打印
   "MinerU installation not detected / please pip install"。而 CLI 其实已安装——这违背了
   `backend.py:35` 已成文的契约："a runtime failure must not be reported as a missing
   installation (issue #1612, outcome 4)"。正确结论应是"已安装但不健康"，让解析尝试走
   `NONZERO_EXIT` 路径给出真实错误。

## 锁定的探测契约（测试即规格）

| # | 路径 | 场景 | 期望 | 基线 |
| - | ---- | ---- | ---- | ---- |
| 1 | 缺失 | 两个候选都不在 PATH | `None`，不抛异常 | 通过 |
| 2 | 缺失 | `mineru` 缺失、`magic-pdf` 健康 | `"magic-pdf"`（顺延） | 通过 |
| 3 | 缺失 | `mineru` exec 抛 `PermissionError` | `None`，不抛异常 | **失败**（异常穿透） |
| 4 | 缺失 | `mineru` exec 抛 `NotADirectoryError` | `None`，不抛异常 | **失败**（异常穿透） |
| 5 | 非零退出 | `mineru` 探测退出 1、`magic-pdf` 退出 0 | `"magic-pdf"`（健康者优先） | 通过 |
| 6 | 非零退出 | `mineru` 退出 1、`magic-pdf` 缺失 | `"mineru"`（已安装但失健，不得答"未安装"） | **失败**（返回 None） |
| 7 | 输出畸形 | 退出 0 + 乱码 stdout | `"mineru"`（版本文本不解析） | 通过 |
| 8 | 输出畸形 | 退出 0 + 空输出 | `"mineru"` | 通过 |
| 9 | 输出畸形 | 退出 0 + 仅 stderr 有版本行 | `"mineru"` | 通过 |
| 10 | 输出畸形 | 退出 0 畸形输出 + 备选健康 | `"mineru"`（次序不受影响） | 通过 |

另以夹具内断言固定探测卫生（无论修复实现如何均适用）：探针 argv 恒为
`[<候选>, "--version"]`、`capture_output=True`（输出不外泄）、`check=False`（非零退出
不得转为 `CalledProcessError`）、`shell=False`。

## 修复线索（两条实现路线均能让本套件转绿）

- **最小修**：把两处 `except FileNotFoundError: pass` 收窄为 `except OSError: pass`
  （或显式列举 `PermissionError`/`NotADirectoryError`），即可转绿 #3、#4；#6 仍需存在性
  语义。
- **存在性语义修（推荐，与 backend 对齐）**：仿照 `backend.local_cli_probe`（`shutil.which`
  判存在）与 `backend.local_cli_version`（`except Exception` 兜底）的组合：候选按
  `mineru → magic-pdf` 顺延，先取健康者；全部存在但不健康时返回第一个存在的候选名；
  都不存在才 `None`。
- 测试夹具同时伪造 `subprocess.run` 与 `shutil.which` 且二者一致，因此无论修复采用哪条
  路线，断言都不绑定实现细节。

## 运行与结果（本运行实测，Python 3.13.13 + pytest 9.1.1）

```
cd <worktree>
# macOS 无 GNU timeout，等价 900s 时限用 perl alarm 实现：
perl -e 'alarm 900; exec @ARGV' /Users/Shared/DeepTutor/.venv/bin/python \
  -m pytest -q -p no:cacheprovider tests/services/parsing/test_mineru_probe.py
→ 3 failed, 7 passed in 0.42s
（预期失败：test_unlaunchable_binary_degrades_to_none、
  test_broken_path_entry_degrades_to_none、test_broken_install_is_not_reported_missing）
```

回归确认（同 worktree，均绿）：

```
tests/services/parsing/test_mineru_local_failures.py
tests/services/parsing/test_mineru_normalization.py
tests/services/parsing/test_engines.py
→ 86 passed, 2 skipped in 2.00s
tests/tools/test_mineru.py → 25 passed in 0.27s
```

## 边界声明

- 本分支零产品代码改动（`git diff origin/main --stat` 仅新增测试与本说明）。
- 测试不触网、不写文件系统、不启动子进程（`subprocess.run` 与 `shutil.which` 全部被
  monkeypatch 替换），夹具经 monkeypatch 自动还原。

# test: 附件存储写入/清理/读回契约补测（2026-10-05）

## 范围

`deeptutor/services/storage/attachment_store.py`（`LocalDiskAttachmentStore`）此前无直接单测。
本卡新增 `tests/services/storage/test_attachment_store.py`，全部基于 `tmp_path`，不触产品代码。

对照持久化扫描（atomic-write 报告 MEDIUM 项）：`_write_sync` 的 `finally` 中
`tmp.unlink()` 以 `except OSError: pass` 抑制清理错误。本组测试将该行为固化为契约断言，
不修改产品实现。

## 测试点与断言（四类）

1. 写入/失败清理（`TestWriteSync`，5 例）
   - 成功写入字节正确，且无 `.tmp` 残留
   - 写入失败（staged 路径被目录占用 → `open("wb")` 失败）：原始错误正常抛出，
     finally 内 unlink 的清理错误被吞（不得掩盖主错误），旧目标字节保持不变
   - 失败后 staged `.tmp` 被清理（patch `os.replace` 失败路径）
   - unlink 自身失败时被吞，不替换主错误（patch `os.replace` + `Path.unlink` 双失败）
   - 父路径被文件占用时 mkdir 硬失败并抛 `OSError`
2. 同路径重复写入（`TestPutOverwrite`，2 例）
   - 同 session/attachment/filename 重复 `put`：覆盖旧字节、URL 不变、目录内仅 1 个文件、无 `.tmp` 残留
   - 不同 attachment_id 同名文件互不覆盖（`{aid}_` 前缀防碰撞）
3. 读回一致性（`TestReadBack`，2 例）
   - `put` → `resolve_path` → 读回字节与原始完全一致（含全 256 字节值与 UTF-8 中文、含空格文件名）
   - 主根缺失时回落 `legacy_root` 命中
4. 删除后状态（`TestDelete`，4 例）
   - `delete_attachment` 只删匹配 `{aid}_` 前缀文件，同会话其他附件保留
   - 删除最后一个附件后空会话目录被回收
   - `delete_session` 同时清理主根与 legacy 根，`resolve_path` 返回 None
   - 对不存在会话删除为 no-op 不抛错

## 与既有测试去重

- origin/main 无 `tests/services/storage/`；`attachment_store.py` 无直接单测。
- `tests/multi_user/test_session_cleanup.py` 仅覆盖多用户隔离下的会话清理路由，与本卡单测不重叠。
- 开放分支 `agent/dt22-file-library-deletion-tests-v2`（PR #1719）新增的是
  `tests/services/storage/test_file_library.py`（file_library 模块），不重叠。
- `scan/atomic-write-tmp-fsync-20261005`、`agent/agen539-upload-residue-cleanup` 均未新增
  attachment_store 测试。

## 执行

```
python -m pytest -q -p no:cacheprovider tests/services/storage/test_attachment_store.py
（经 subprocess 包装强制 900s 超时上限）
```

结果：**13 passed in 0.27s**（修复 1 处测试内断言笔误后全绿；无跳过、无告警新增）。

环境：Python 3.13.13，pytest 9.1.1，工作分支基于 origin/main `f07029cfc`（v1.6.13）。

## 文件

- `tests/services/storage/__init__.py`
- `tests/services/storage/test_attachment_store.py`

# KB 上传入口边界补测证据（AGEN-495）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12）。

## 产物

- `tests/api/routers/test_upload_bounds.py` — 8 个用例，全部走 HTTP 路由层
  （`POST /api/knowledge-bases/{kb}/upload`，TestClient + 真实
  `KnowledgeBaseManager` 写临时目录），锁定上传入口五类边界的现状行为。
- `tests/api/routers/__init__.py` — 包标记（仓库 tests 子目录惯例）。
- 无任何产品代码改动（`git diff ef2d9e5c3 --stat` 仅新增以上文件与本证据）。

## 覆盖分支（五类边界 × 现状断言）

| 类别 | 用例 | 现状断言 |
| --- | --- | --- |
| 不支持类型 | `test_upload_rejects_unsupported_extension_with_readable_error` | `.bat` 被拒 400；错误信息含原文件名、被拒后缀与 `Allowed types` 白名单（可读性）；raw/ 无落盘、无后台任务、KB 状态不变 |
| 空文件 | `test_upload_entry_accepts_empty_text_file` | 0 字节 `.txt` 入口放行 200（内容检查属于解析阶段），空文件原样落盘且任务已派发 |
| 空文件（压缩包） | `test_upload_rejects_empty_zip_archive_with_readable_error` | 0 字节 `.zip` 无法通过解包，400 且报错点名压缩包（`not a valid zip archive`） |
| 超大小 | `test_upload_rejects_oversize_file_before_writing` | 缩小 `MAX_FILE_SIZE` 后超限文件写盘前被拒 400；错误信息含原文件名与具体上限数字；raw/ 无落盘、无任务、状态不变 |
| 损坏内容·假后缀 | `test_upload_entry_defers_content_checks_for_fake_pdf` | 纯文本假 `.pdf` 入口放行 200，字节原样落盘并派发任务（入口只校验后缀不嗅探内容，内容校验延迟到解析） |
| 损坏内容·假后缀（压缩包） | `test_upload_rejects_fake_zip_content_with_readable_error` | 垃圾字节假 `.zip` 被解包层拒绝 400，报错点名文件且不含利用细节 |
| 损坏内容·截断 | `test_upload_entry_defers_content_checks_for_truncated_pdf` | 截断 PDF 入口放行 200，截断字节逐字节落盘（入口不做内容嗅探） |
| 损坏内容·截断（压缩包） | `test_upload_rejects_truncated_zip_with_readable_error` | 中央目录被截断的真实 zip 被拒 400（`not a valid zip archive`） |

要点：`.bat`/`.apk` 等确实不在 `FileTypeRouter.get_supported_extensions()` 白名单内
（该白名单当前 301 项，含 `.exe`/`.sh` 等解析引擎格式），不支持类型用例据此选定；
白名单本身不在本卡范围。

## 运行命令与结果

```bash
# worktree 根目录，Python 3.13（/Users/Shared/DeepTutor/.venv）
python -m pytest tests/api/routers/test_upload_bounds.py -q -p no:cacheprovider
# → 8 passed in 1.28s

python -m pytest tests/api/routers/ tests/api/test_knowledge_zip_upload.py \
  tests/api/test_upload_off_event_loop.py tests/api/test_knowledge_router.py \
  -q -p no:cacheprovider
# → 139 passed in 4.26s（含既有上传/zip 相关测试，无回归）

ruff check tests/api/routers/ && ruff format --check tests/api/routers/
# → All checks passed!
```

## 环境备注

- 纯 worktree 缺 `data/user/settings/main.yaml`（`knowledge.py` 模块导入时读取），
  本次从主 checkout 复制该文件到 worktree 同路径（`.gitignore` 已忽略 `data/`，
  不会进入提交）；与 AGEN-144 证据记录的环境限制一致。
- 与开放 PR #1709（`pr/test-api-router-contracts`，`test_knowledge_upload_guards.py`）
  的关系：该 PR 已覆盖「不支持类型 / 超大小 / 批内重名 / 提供商不匹配 / 写中超限清理」，
  本卡补充其未覆盖的「空文件、假后缀、截断文件」三类入口边界，并逐条断言错误信息
  可读性；两份文件路径不同（`tests/api/` vs `tests/api/routers/`），可独立评审。

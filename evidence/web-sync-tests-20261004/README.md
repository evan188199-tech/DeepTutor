# 网页源同步生命周期离线测试说明

- 基线：`origin/main` @ `f07029cfc`（release v1.6.13）
- 分支：`test/web-source-sync-20261004`
- 新增文件：`tests/services/test_web_source_sync_lifecycle.py`（仅测试，无产品代码改动）

## 场景与四态覆盖

| 状态 | 测试 | 断言要点 |
| --- | --- | --- |
| 新增（首次抓取落库） | `test_first_sync_persists_pages_hashes_and_success_state` | 2 页落盘到 `raw/_web/<ns>/`，`page_hashes`/`page_count` 持久化，`last_sync_status=success`，所有请求 URL 均指向夹具站点 |
| 变更（增量更新） | `test_changed_content_updates_only_changed_pages` | 1 增 1 更 1 不变；仅变更页送索引（`add_documents` 收到 2 个变更文件，不含未变首页）；磁盘内容与远端一致；首页 hash 不变 |
| 失败（状态标记） | `test_failed_sync_marks_error_and_preserves_snapshot` | 全站 503 → `ok=False`、`last_sync_status=error`、错误信息落库；hash 不推进、快照逐字节不变 |
| 失败（重试） | `test_fetch_page_retries_transient_5xx_then_succeeds` | 503×2 后 200 → 第 3 次成功，请求数 = 1 + `_MAX_RETRIES` |
| 失败（重试放弃） | `test_fetch_page_gives_up_after_max_retries` | 持续 503 → 返回 `None`，请求数 = 1 + `_MAX_RETRIES` |
| 恢复（故障后自愈） | `test_sync_recovers_after_transient_outage` | 失败→恢复后 `success`、错误清空、`pages_unchanged=2`，不重复索引（恢复期 `add_documents` 调用 0 次） |
| 恢复（索引故障后补挂） | `test_indexing_outage_recovery_restages_changed_page` | 索引失败时快照已写、hash 未推进；下次同步以 `pages_updated=1` 重新入索引并回到 `success` |
| 一致性（快照 ↔ 元数据 ↔ 索引） | `test_snapshot_and_index_stay_consistent_through_change_and_removal` | 删除 1 页 + 修订 1 页后：`raw/` 文件集合 == `page_hashes` 键集合；重建索引收到的文件 == 幸存文件集合；被删页的 `file_hashes` 记录清除 |

## 命令与数字

```bash
timeout 900 python -m pytest -q -p no:cacheprovider \
  tests/services/test_web_source_sync_lifecycle.py
# 8 passed in ~1.0s（连跑 3 次结果一致）

# 与既有网页源测试合跑，确认无相互干扰
timeout 900 python -m pytest -q -p no:cacheprovider \
  tests/services/test_web_source_sync_lifecycle.py \
  tests/services/test_web_source_sync.py \
  tests/services/test_crawler_scope.py tests/services/test_crawler_robots.py \
  tests/services/web_source/ tests/knowledge/test_web_source_metadata.py
# 77 passed in ~1.5s

ruff check tests/services/test_web_source_sync_lifecycle.py   # All checks passed
ruff format --check tests/services/test_web_source_sync_lifecycle.py  # clean
```

本机无 GNU `timeout` 时可用等价限时包装（如 `perl -e 'alarm shift; exec @ARGV' 900 …`）。

## 离线可重放说明

- 所有 HTTP（含 `robots.txt`）由 `FakeDocsSite` + `httpx.MockTransport` 内存夹具应答，真实 `crawl_docs_site` 管线通过注入 `client_factory` 走本地传输。
- `crawl_clock` 夹具将 `_is_disallowed_host` 置空、`time.monotonic` 冻结、`asyncio.sleep` 桩化：无 DNS 解析、无真实等待、无外网出口。
- 抓取层断言了每次请求 URL 都属于夹具 origin（`https://docs.example.com`），首屏测试还校验了完整请求路径集合。
- 索引侧以 `AsyncMock` 替身记录调用（`add_documents` / `RAGService.initialize`），不依赖任何嵌入模型或外部服务；临时 KB 建在 `tmp_path`。

## 边界

- 未修改任何产品代码；`git diff` 仅含本测试文件与本说明目录。
- 若后续开 PR，需先从分支移除本 `evidence/` 目录。

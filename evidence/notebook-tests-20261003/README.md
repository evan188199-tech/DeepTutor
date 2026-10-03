# Question Notebook API 契约补测说明（notebook-tests-20261003）

对应卡片：AGEN-114（test: Question Notebook API 契约补测）。基线：`origin/main` @ `ef2d9e5c3`（v1.6.12）。分支：`myfork/test/notebook-api-contract-20261003`。上游背景：HKUDS/DeepTutor#1244（v1.6.4 报告，开放、无关联 PR）。

## 结论先行

**跑通：PASS（20/20 新增契约测试全绿，无失败测试）**。开工前上游核查发现卡片前提已过时：

| #1244 根因 | 上游现状（v1.6.12） | 证据 |
| --- | --- | --- |
| 根因 1：`AssessmentSource` 不含 `partner_chat`，来源被拒 | **已修复**。`partner_chat` 自 `deeptutor/core/assessment.py` 创建（`fe482d64e`，2026-09-19）即为合法来源；`import` 于 `0fff9246c`（2026-09-21）加入。实测 `POST /entries/upsert` 带 `source=partner_chat` 返回 200 并落库 | 本分支测试实跑 |
| 根因 2：Partner 无写错题本工具 | 未在本卡范围（属 partner 工具面，非 notebook API 契约） | #1244 原文 |

关联 PR 核查：`gh pr list --search "1244"`（open）为空、按标题检索 notebook/partner 相关 PR 为空——#1244 修复未挂 PR，故按卡片走补测路径而非复核路径。"partner_chat 拒绝路径"在 v1.6.12 已不存在，本卡改为：**钉住当前契约（全部 6 个合法来源接受 + 未收录来源 422 拒绝）+ 去重 + 并发写入**，作为 #1244 类改动的回归护栏。

## 本分支新增（仅测试，未改任何产品代码）

- `tests/api/test_notebook_api_contract.py` — 11 个测试函数 / 20 个用例

## 场景与结果（origin/main @ ef2d9e5c3 实跑）

| 用例 | 数字 | 契约点 |
| --- | --- | --- |
| `test_assessment_source_catalog_is_pinned` | 1 PASSED | 钉住 6 来源全集；上游增删来源时此测试显式失败提醒 |
| `test_upsert_accepts_every_valid_source[6 来源]` | 6 PASSED | 6 来源 upsert 均 200 且回显 source（含 partner_chat） |
| `test_upsert_rejects_unlisted_source[5 非法值]` | 5 PASSED | 未收录来源（wechat_chat/partner/大小写变体/空串）→ 422 literal_error @ body.source，且零落库 |
| `test_entries_filter_rejects_unlisted_source` | 1 PASSED | `GET /entries?source=wechat_chat` → 422 |
| `test_partner_chat_entry_roundtrip_and_filter` | 1 PASSED | #1244 目标终态：partner_chat 落库、按 id 读回、按 source 过滤 |
| `test_upsert_dedupes_identity_and_updates_content` | 1 PASSED | 同 (origin_type, origin_ref, turn_id, question_id) 两次 upsert → 1 行，内容为第二次，score_trend new→declined |
| `test_upsert_identity_is_turn_scoped` | 1 PASSED | 同题不同 turn_id → 2 行（身份含 turn 维度，不误杀） |
| `test_upsert_rejects_conversation_origin_ref_mismatch` | 1 PASSED | conversation origin_ref ≠ session_id → 422，零落库 |
| `test_upsert_requires_origin_ref_for_non_conversation` | 1 PASSED | external_import 缺 origin_ref → 422，零落库 |
| `test_concurrent_identical_upserts_keep_single_row` | 1 PASSED | 8 个并发同键 upsert（ASGITransport + asyncio.gather）→ 全 200，恰 1 行 |
| `test_concurrent_distinct_turns_create_distinct_rows` | 1 PASSED | 8 个并发不同 turn → 全 200，8 行不丢 |

## 命令与数字

```
PYTHONPATH=<worktree> python -m pytest tests/api/test_notebook_api_contract.py -q
→ 20 passed in 0.61s

PYTHONPATH=<worktree> python -m pytest tests/api/test_notebook_api_contract.py tests/api/test_notebook_router.py -q
→ 38 passed in 0.92s（现有 router 测试 18 个无回归）

ruff check tests/api/test_notebook_api_contract.py
→ All checks passed!
```

测试环境：独立 venv（fastapi、httpx、aiosqlite、pytest、pytest-asyncio、pydantic-settings、PyYAML、jinja2、aiohttp、tenacity、loguru、defusedxml），`PYTHONPATH` 指向本 worktree，避免主 checkout 的可编辑安装串味。精简 venv 下 `tests/api/` 其余文件因缺 python-multipart 等依赖无法收集，超出本卡范围未追。

## 修复卡领取指引

- 本组测试当前**全绿**：它们不是"失败测试集"（v1.6.12 上已无 partner_chat 拒绝路径可钉），而是 #1244 类改动的契约护栏——任何来源增删、身份键调整、并发写入回归都会在这里先红。
- #1244 剩余缺口在 partner 工具面（根因 2）与 mention 群聊纯图消息，需要新卡，非 API 契约测试可覆盖。

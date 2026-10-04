# 复核报告：PR #1466「Codex 凭据失效快速失败」（对应 #1454）

- 复核日期：2026-10-04
- 复核基线：origin/main @ `ef2d9e5c3`（v1.6.12），已包含 PR #1466（merge `a35935dc3`，源提交 `3b467ac0e`，2026-09-23 合入 dev）
- 重要背景：合入约 20 分钟后，同一作者又提交了后续修正 `3f77d8e4e`（Classify terminal Codex refresh rejection separately from outages），对 #1466 的判定逻辑做了两处调整。**复核结论以当前 origin/main（含该后续修正）为准**。
- 本卡为纯复核，未改任何业务代码。

## 一、结论

**#1454 报告的核心问题——「凭据已失效时，每轮对话都重复请求 token endpoint 与 chatgpt.com/backend-api、反复要求重新授权」——在「刷新被拒（invalid_grant/invalid_token）」场景下已被消除**：首次失败后被标记 60 秒冷却，冷却期内每轮 0 次网络调用直接快速失败；backend 请求在凭据死掉后不再被重复发起。

判定：**基本解决（PASS）**，但存在两处残余（见第四节）：

1. 持续 403（账号级/权限级拒绝）场景下，每轮仍会发起 **1 次** backend 请求（这是后续修正 `3f77d8e4e` 有意的选择，不再是 #1466 原实现的「403 也进冷却」）；
2. 冷却窗口到期后，若凭据仍死，每 60 秒会放行 1 次新的刷新尝试（设计上的瞬态逃生门，属可接受的限速重试而非循环）。

## 二、当前行为链路（检测 → 标记 → 提示）

以下行号均为 origin/main @ `ef2d9e5c3` 的当前代码。

### 检测

| 步骤 | 位置 | 行为 |
| --- | --- | --- |
| 1. 每轮对话取 token | `deeptutor/services/llm/provider_core/openai_codex_provider.py:79` → `:43-44` | `_call_codex` → `_load_token` → `CodexOAuthService.get_token()` |
| 2. 无凭据 | `deeptutor/services/codex_auth/service.py:724-729` | 抛 `authentication_required`（401） |
| 3. 冷却期内快速失败 | `service.py:730-739`（判定函数 `:952-954`） | 抛 `authentication_required`"Codex sign-in could not be renewed. Sign in to Codex again."，**不访问 token endpoint** |
| 4. token 仍新鲜（剩余 >300s） | `service.py:740-741` | 直接返回缓存 token，无网络 |
| 5. 需要刷新 | `service.py:795-806` → `deeptutor/services/codex_auth/oauth.py:300-309` | 调 token endpoint；`oauth.py:345-358`：HTTP 400/401 且响应体 `error ∈ {invalid_grant, invalid_token}` → 抛 `token_refresh_rejected`（**终态**）；传输错误/5xx → `token_refresh_failed`（502，**瞬态**） |
| 6. 后端 401 触发恢复 | `openai_codex_provider.py:91-93` → `service.py:827-838` | `recover_after_unauthorized` 持同一把 `_refresh_lock` 走同一 `_refresh_credentials`，同样受标记约束 |

### 标记

| 事件 | 位置 | 行为 |
| --- | --- | --- |
| 刷新被拒（`token_refresh_rejected`） | `service.py:801-806` → `:946-947` | `_reauth_until = clock + 60s`（`CODE_AUTH_FAILURE_COOLDOWN_S = 60`，`service.py:61`）。注意：**只有**终态拒绝才标记；瞬态 `token_refresh_failed` 不标记（`3f77d8e4e` 引入的区分） |
| 登录成功 | `service.py:642`（`_run_login` 完成） | 清除标记 |
| 刷新成功并提交 | `service.py:822` | 清除标记（`3f77d8e4e` 新增） |
| 登出 | `service.py:886` | 清除标记 |
| 60 秒到期 | `service.py:952-954` | 标记自动失效，允许一次新的刷新尝试 |
| 后端 403 | （无） | **不标记**——`3f77d8e4e` 删除了 #1466 原有的 `mark_reauth_required()` 公共入口与 403 标记（`tests/services/llm/test_openai_codex_oauth_provider.py:188` `test_403_does_not_mark_reauth_required` 固化该选择："A 403 may be model access denial, not a revoked OAuth grant"） |

### 提示（学习者可见）

| 场景 | 位置 | 文案 |
| --- | --- | --- |
| 后端 401 + 恢复失败（刷新被拒/需重新登录） | `openai_codex_provider.py:98-105` → `:113-117` | "Error calling Codex: Codex login expired and could not be renewed. Sign in again."，`finish_reason="error"` |
| 冷却期内后续轮次 | `service.py:735-738` → `openai_codex_provider.py:118-122` | "Error calling Codex: Codex sign-in could not be renewed. Sign in to Codex again."，`finish_reason="error"`，全程 0 网络调用 |
| 后端 403 | `openai_codex_provider.py:242-243`（`_friendly_error`）→ `:113-117` | "This Codex account is not allowed to make the requested call." |
| 401 但恢复成功（会话确实续期） | `openai_codex_provider.py:240-241` | "Codex login expired. The session was refreshed; retry this request."（仅在实际续期成功时承诺重试） |

## 三、「每轮重复请求」消除判定

修复前的循环（PR 描述与代码一致）：每轮 = 1 次 token endpoint 刷新（已死）→ 1 次 backend 请求 → 401 → `recover_after_unauthorized` 再刷 1 次（仍死）→ 每条消息都弹一次重新授权要求。即**每轮 2 次 token endpoint + 1 次 backend**。

修复后（凭据刷新被拒场景）：

- 第 1 轮：1 次 token endpoint（被拒并标记）+ 0~1 次 backend（若 token 未过期先 401 再触发恢复刷新，恢复也走同一标记路径）；
- 之后 60 秒内每轮：**0 次网络调用**（`get_token` 在 `service.py:730` 直接抛错，先于 `openai_codex_provider.py:83` 的 `_request_codex`）；
- 每个 60 秒窗口到期后：最多 1 次 token endpoint 重试；backend 在刷新成功前不会被再次请求。

**结论：token endpoint 与 backend 的每轮重复请求均已消除**（限速为每 60 秒 ≤1 次刷新尝试），且错误文案稳定为「请重新登录」而非反复触发授权流程。

测试覆盖（均已在本次复核中实际运行通过）：

- `tests/services/codex_auth/test_service.py:1695` `test_get_token_stops_refreshing_after_a_failed_refresh`（窗口内不再打 token endpoint）
- `test_service.py:1732` `test_get_token_retries_after_the_reauth_cooldown_elapses`（到期放行一次）
- `test_service.py:1757` `test_transient_refresh_failure_can_retry_next_turn`（瞬态失败不进冷却，下一轮即可重试）
- `test_service.py:1776` `test_failed_refresh_marks_reauth_required_until_next_login`（重新登录清除标记）
- `tests/services/codex_auth/test_oauth.py:429` `test_invalid_refresh_grant_requires_new_sign_in`（invalid_grant → `token_refresh_rejected`）
- `tests/services/llm/test_openai_codex_oauth_provider.py:157/188/211`（401 死 token 不承诺重试；403 不标记；429 不读 API key）

## 四、残余场景与边界

1. **持续 403（#1454 用户实际看到的 403 报错）**：token 未过期时 `get_token` 直接返回缓存 token（无 token endpoint 调用），但每轮仍发起 1 次 backend 请求并得到 403 错误文案。重复请求从修复前的「每轮 auth+refresh+backend 多次」降为「每轮 1 次 backend」，**未归零**。这是 `3f77d8e4e` 的有意取舍（403 可能只是某个模型无权限，不应锁整个凭据）。
2. **token 未过期但已被服务端吊销**：因 `service.py:740` 对剩余 >300s 的 token 不刷新，首轮仍要经历 backend 401 → 恢复刷新被拒，才进入冷却（每 60 秒窗口首轮代价 1 次 backend + 1 次 token endpoint）。
3. **冷却到期边界**：凭据持续死亡时，每个 60 秒窗口边界会出现 1 次刷新尝试 + 1 次同样的终态错误文案，学习者会周期性看到重复报错（限速正确，体验上仍非一次性）。
4. **进程内存态**：`_reauth_until` 不持久化；服务为进程内单例（`service.py:1169, 1282-1298`），重启即清零，多进程部署时各进程独立冷却。
5. **状态不外显**：`public_status`（`service.py:956-1002`）不暴露 reauth-needed，冷却期内 `connection` 仍为 `"connected"`，Dashboard 无法据此提示「需要重新登录」，学习者只能从逐条消息的错误文案获知。
6. **分类依赖响应体**：`token_refresh_rejected` 要求 token endpoint 返回 JSON 且 `error ∈ {invalid_grant, invalid_token}`（`oauth.py:345-358`）；若上游返回非 JSON 或其他错误码的 400/401，会落入瞬态 `token_refresh_failed`，退化为每轮重试（概率低，但存在）。

## 五、后续建议

1. 若要消除 403 场景的每轮 1 次 backend 请求，可考虑「连续 N 次 403 才进入冷却」的保守计数（需区分模型权限与账号封禁，与 `3f77d8e4e` 的设计选择冲突，应先在上游讨论）。
2. 将 reauth-needed 状态暴露进 `public_status`（如 `error_code: "authentication_required"` 或独立字段），让前端在冷却期内给出置顶「请重新登录 Codex」提示，而不是逐条报错。
3. 对 token endpoint 的非 JSON 400/401 拒绝考虑兜底分类（如 401 一律视为终态拒绝）。
4. #1454 正文建议的 API Key 方案是更长期的稳定性路径，与本次修复不冲突，可作为独立需求跟进。

## 六、验证记录

- worktree：`review/agen427-pr1466` @ `ef2d9e5c3`（自 origin/main 新建；主工作区 `/Users/Shared/DeepTutor` 未动）
- 祖先校验：`3b467ac0e`（#1466）与 `3f77d8e4e`（后续修正）均已在 origin/main 内（`git merge-base --is-ancestor` 通过）
- 测试命令（PYTHONPATH 钉在 worktree，已验证导入的是 worktree 代码而非主 checkout 的 editable 安装）：

```
PYTHONPATH="$PWD" /Users/Shared/DeepTutor/.venv/bin/python -m pytest \
  tests/services/codex_auth/test_service.py \
  tests/services/codex_auth/test_oauth.py \
  tests/services/llm/test_openai_codex_oauth_provider.py -q
# 结果：104 passed in 1.06s
```

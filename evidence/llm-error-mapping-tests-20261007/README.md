# evidence: services/llm error_mapping 单元测试补齐

- 日期: 2026-10-07
- 基线: origin/main @ f07029cfc (release v1.6.13)
- 分支: test/llm-error-mapping-20261007
- 改动: 仅 `tests/services/llm/test_error_mapping.py`（+194 行），无产品代码改动

## 场景覆盖

对 `deeptutor/services/llm/error_mapping.py` 的每个映射分支至少一例：

1. 状态码分支：401 → `LLMAuthenticationError`；429 → `LLMRateLimitError`（既有用例保留）。
2. 超时分支：`asyncio.TimeoutError` 与内建 `TimeoutError` → `LLMTimeoutError`（status 408）；
   空消息时回退默认文案 "Request timed out"。
3. 类名分支（`_class_named`，不导入 SDK）：`AuthenticationError`、`AuthenticationStatusError`
   → 认证错误；`RateLimitError` → 限流错误并保留 `retry_after` 属性；MRO 子类也能命中。
4. 消息分支（`_message_contains`，大小写不敏感）："rate limit" / "429" / "quota" → 限流；
   无提示时 `retry_after is None`；"context length" → `ProviderContextWindowError`。
5. 未知错误兜底：无 status_code 的未知异常 → `LLMAPIError`（status_code None、provider 透传）；
   401 优先于消息限流分支（优先级断言）。
6. LLMError 透传：身份保持（`mapped is error`）；provider 已知时不被覆盖，未知时原地补齐。
7. 重试建议字段（retry_after）：
   - 异常 `retry_after` 属性优先于响应头；
   - 响应头 `Retry-After` 与小写 `retry-after` 均可读取；
   - `parse_retry_after_seconds`：数值/字符串数值/空白包裹、HTTP 日期（过期钳制为 0.0、
     naive 日期按 UTC）、拒绝 bool/-1/inf/nan/空串/乱串/dict/list/None。

## 命令与数字

```
python -m pytest -q -p no:cacheprovider tests/services/llm/test_error_mapping.py
```

- 结果：**43 passed**（原 14 个运行时用例 + 新增 29 个，含参数化展开），0.26s，退出码 0
- 运行环境：/Users/Shared/DeepTutor/.venv（Python 3.13），worktree 于本分支
- lint：`ruff check` 与 `ruff format --check` 通过（format 已应用）

## 说明

- 原 origin/main 测试已覆盖 401/429 状态码、响应头 Retry-After、上下文窗口消息、
  API 兜底与 LLMError 透传；本次补齐的是规则表各分支（超时、类名、消息）与
  retry_after 解析的边界。
- 上游无关联开放 PR（已核对 HKUDS/DeepTutor 全部开放 PR，无 error_mapping 相关）。

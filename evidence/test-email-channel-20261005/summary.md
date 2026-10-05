# test: email 通道拉取与停止吞错路径补测（AGEN-645）

## 结论

PASS — 聚焦 pytest 21 passed（全部新增），partners 全目录回归 632 passed，未改产品代码。

## 范围

为 `deeptutor/partners/channels/email.py` 补充三类此前未覆盖的场景
（对应 DT-22 报告 §7 MEDIUM :377 的 `client.logout()` 吞错路径）：

1. 正常拉取与解析（`_fetch_messages` / `_fetch_new_messages`）：
   - 发件人归一化（小写）、RFC2047 编码主题解码、正文提取、content 拼装、
     metadata（message_id/subject/date/sender_email/uid）。
   - `mark_seen=False` 不写 `\\Seen`；UID 去重（第二次拉取同一 UID 返回空）；
     `limit` 只取最新 N 条；空正文占位 `(empty email body)`；
     `max_body_chars` 截断；multipart 纯文本优先、附件跳过；HTML-only 转文本；
     `fetch_messages_between_dates` 的 SINCE/BEFORE 英文日期、limit、不标记已读、
     空区间不发起连接。
2. 连接失败与吞错路径：
   - `client.logout()` 抛 `imaplib.IMAP4.abort` 时 `_fetch_messages` 不崩溃、
     消息照常返回、logout 仍恰好调用一次（:377 finally 吞错路径）。
   - select/search 返回 NO → 返回空且 logout 仍调用；fetch 失败与无发件人的
     消息被跳过；login 失败向上抛出但 logout 仍调用（finally 保证）；
     `imap_use_ssl=False` 走 `IMAP4` 且端口正确。
3. start/stop 生命周期：
   - 未授权（consent_granted=false）与配置缺失 → `action_required`，不发起连接。
   - 连接失败（ConnectionRefusedError）→ `start()` 降级为 setup state
     `error`（"Channel connection failed; the listener will retry."）并继续轮询重试。
   - `start()` 正常轮询：解析后的消息发布到 MessageBus，主题/Message-ID 记忆
     供回复引用，setup state `running`。
   - `stop()` 后轮询循环退出、任务无异常结束、不再发起新拉取/发布；
     每轮拉取后连接已释放（logout 在两次 poll 之间完成，不持有连接）。

实现方式：注入脚本化假 IMAP 客户端（记录 login/select/search/fetch/store/logout
调用并模拟 imaplib 响应形状），不访问网络、不需要真实邮箱账号。

## 变更

- `tests/services/partners/test_email_channel.py`（仅测试，+529 行，21 个用例）

## 去重核对

- 上游开放 PR（HKUDS/DeepTutor，2026-10-05 查询，含本人全部开放 PR）无
  email 通道相关改动，无撞车。
- 既有渠道测试（test-feishu-channel 系列覆盖 feishu/lark、
  test-telegram-message-parsing 覆盖 telegram、#1763 覆盖 manager 出站超时）
  均不涉及 `channels/email.py`；origin/main 的 `tests/services/partners/`
  下无任何 email 通道测试，无重复。

## 验证

环境：macOS，Python 3.13.13（/Users/Shared/DeepTutor/.venv），
worktree 基于 origin/main f07029cfc（release: v1.6.13）。

```text
timeout 900 python -m pytest -q -p no:cacheprovider tests/services/partners/test_email_channel.py
# 21 passed in 0.32s
timeout 900 python -m pytest -q -p no:cacheprovider tests/services/partners/
# 632 passed in 8.12s
ruff check / ruff format --check：通过
scripts/check_repo_hygiene.py：通过
```

完整输出见 pytest-output.txt；SHA256SUMS 为本目录各文件校验和。

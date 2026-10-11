# verify-channel-fix-branches 复核结论（20261011）

- 基线 `origin/main` `6cf793bd868b`（v1.6.14）；复核时 `origin/main` 与 `origin/dev` 均停在 `6cf793bd8`（fetch origin+myfork 后实测 `rev-list --count 6cf793bd8..origin/main` = 0）
- 口径同 `evidence/weak-done-drift-20261009/summary.md`：逐分支与 main diff，patch-id 经 `git cherry` 核对
- 判定方法：8 个分支的 merge-base 全部等于 `6cf793bd8`（即当前 main），故 `git diff origin/main <branch>` 恰为分支自身改动；main 自基线零前进 ⇒ 不存在 landed/drift 的可能路径，逐分支再以 `git cherry origin/main <branch>` 全 "+" 复证
- 汇总：**landed 0 / drift 0 / missing 8**

## 逐分支结论表

| 卡片别名 | myfork 分支 | 头 commit | diff 统计（vs origin/main） | 结论 |
|---|---|---|---|---|
| fix-feishu-send-raise | `fix/feishu-send-raise` | `784479726f20` | 3 文件 +189/−11 | missing |
| fix-mochat-send-raise | `fix/mochat-send-raise-20261010` | `4bf76d34b1a1`（2 commits，含 `e1edb3fdd21d` 测试） | 2 文件 +593/−0 | missing |
| fix-dingtalk-delivery | `fix/dingtalk-delivery-timeout-streamclient-20261010` | `7a29b614c976` | 2 文件 +333/−7 | missing |
| fix-channel-stop-cleanup | `fix/channel-stop-cleanup` | `ba46084c41bd` | 9 文件 +365/−12 | missing |
| fix-channel-eventloop-blocking | `fix/channel-eventloop-blocking-20261010` | `944da099a7e9` | 4 文件 +294/−10 | missing |
| fix-channel-inbound-idempotency | `agent/agen1497-inbound-dedup`（myfork 无同名分支，按 commit "deduplicate redelivered inbound messages" 对应） | `c13ecbf5827f` | 7 文件 +397/−0 | missing |
| fix-qq-wecom-ephemeral-state | `dt/fix-qq-wecom-ephemeral-state` | `1e1e89d2b2c4` | 4 文件 +279/−3 | missing |
| AGEN-1499 发送超时 | `agent/agen1499-send-timeouts` | `992dfc68baf3` | 9 文件 +498/−74 | missing |

各分支 `git cherry` 结果（"+" = patch 不存在于 main）：8/8 全 "+"。

## 各分支修复要点（diff 实读，供续放复核）

- **feishu-send-raise**：`feishu.py` send 链路加 `raise_on_failure` 透传、失败聚合后 `RuntimeError`，使 manager `send_with_retry` 退避生效；top-level except 改为记日志后 re-raise
- **mochat-send-raise**：`mochat.py` send 的 except 记日志后 `raise`（单行修复）+ 592 行新测试 `test_mochat_channel.py`
- **dingtalk-delivery**：`dingtalk.py` send 失败改 raise；`httpx.AsyncClient` 加 30s 超时；stop() 经 `_stream_until_stopped`/`_teardown_stream_client` 可中断 SDK 无界 stream 循环并关 websocket
- **channel-stop-cleanup**：dingtalk/discord/feishu/mochat/slack/telegram/zulip/lark_http 共 8 处 stop 路径补齐资源关闭（任务 cancel 后 gather 等待、web client session 关闭、keep-alive 连接池 `close_keep_alive()`、流缓冲清理、telegram 三段式拆解）
- **channel-eventloop-blocking**：msteams server shutdown、weixin 媒体读取/AES 加密、zulip get_profile/deregister/listener join 改 `asyncio.to_thread` 移出事件循环
- **agen1497-inbound-dedup**：新增 `channels/dedup.py`（71 行）+ base.py 钩子，dingtalk/discord/msteams/slack 接入入站去重
- **qq-wecom-ephemeral-state**：qq 出站路由优先用 reply metadata 的 `chat_type`（经 `runtime.py` `_thread_delivery_meta` 透传），缺失时 raise 而非默认 c2c；wecom 缺 frame 丢弃改为计数器 + 可选告警钩子
- **agen1499-send-timeouts**：`config/schema.py` 加 send 超时配置（16 行），base/dingtalk/feishu/qq/slack/wecom/whatsapp 共 7 通道发送路径网络调用套共享超时（−74 为重排）

## 续放清单（全部 missing → 建议续放）

main 无任何等价实现（分支基线即 main，修复内容均为 main 所无；`git grep` 抽查 `raise_on_failure`、`close_keep_alive`、`dedup.py` 在 main 均无命中）。8 个分支全部进入续放候选，无 drift 需重做，无 landed 可关账：

1. `fix/feishu-send-raise`
2. `fix/mochat-send-raise-20261010`
3. `fix/dingtalk-delivery-timeout-streamclient-20261010`
4. `fix/channel-stop-cleanup`
5. `fix/channel-eventloop-blocking-20261010`
6. `agent/agen1497-inbound-dedup`（对应别名 fix-channel-inbound-idempotency）
7. `dt/fix-qq-wecom-ephemeral-state`
8. `agent/agen1499-send-timeouts`

上游开放 PR 核对（`gh pr list -R HKUDS/DeepTutor --author @me --state open`，20261011）：#1743、#1699、#1384、#1374，均与本批分支无关，本批分支亦无在途上游 PR。

## 复核命令（全部只读）

```bash
git -C /Users/Shared/DeepTutor fetch --multiple origin myfork
git -C /Users/Shared/DeepTutor rev-list --count 6cf793bd8..origin/main        # 0
git -C /Users/Shared/DeepTutor merge-base origin/main myfork/<branch>          # = 6cf793bd8（8/8）
git -C /Users/Shared/DeepTutor diff --shortstat origin/main myfork/<branch>   # 上表 diff 统计
git -C /Users/Shared/DeepTutor cherry origin/main myfork/<branch>             # 全 "+"
git -C /Users/Shared/DeepTutor diff origin/main myfork/<branch> -- deeptutor/ # 逐分支实读
```

（`<branch>` 取上表 myfork 分支名；未 checkout/reset/clean 任何既有工作区，未改动任何既有分支。）

## 附注

- `myfork/myfork/fix/partner-outbound-timeout-visibility`（`275ff298a`，test 性质）与 `fix/channel-notrunning-send-contract-20261010` 属同主题近邻分支，未列入本卡指定清单，如需同口径复核见后续卡
- mochat 分支含 2 个 commit（测试先行 + 修复），diff 统计已按分支整体 vs main 计

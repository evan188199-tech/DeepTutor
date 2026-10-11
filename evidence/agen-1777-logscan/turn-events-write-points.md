# turn_events 持久化点与元数据生产点（仅中性条目）

## 持久化层（写点本体）

| 文件:行 | 域 | 说明 | 建议 |
| --- | --- | --- | --- |
| deeptutor/services/session/sqlite_store.py:1733 | services | `INSERT INTO turn_events`，`content` 与 `metadata_json` 全量落盘 SQLite（表定义 358-371） | 中：属设计内持久化，建议明确保留期/清理策略并文档化敏感字段清单 |
| deeptutor/services/session/pocketbase_store.py:1695 | services | `turn_events` collection `create`，同上 | 中（同上） |

## 元数据生产点（按敏感类别）

| 文件:行 | 域 | 类别 | 中性依据 | 建议 |
| --- | --- | --- | --- | --- |
| deeptutor/services/session/turns/executor.py:874 + deeptutor/services/session/_turn_runtime_shared.py:862-936 | services | 用户内容 | `_request_snapshot_metadata` 将原始用户消息 `content`、config、各类 references 全量写入事件 metadata（注释标明用于失败重发） | 中：设计内行为；建议对 snapshot 中 content 做长度/用途标注与保留期策略 |
| deeptutor/services/session/turns/executor.py:719 | services | 用户内容 | history 事件 `"output": transcript`、`"summary"` 写入 content/metadata | 中 |
| deeptutor/services/session/turns/executor.py:943 | services | 用户内容 | metadata 含 `conversation_summary`、`conversation_context_text` | 中 |
| deeptutor/agents/loop/pipeline.py:1205 | agents | 用户内容 | metadata 含 `ask_user` 完整负载 | 中 |
| deeptutor/services/session/turns/learning_adapter.py:189 | services | 用户内容（学习者数据） | metadata `tool_metadata.mastery_grade` 携带评分负载 | 中 |
| deeptutor/services/session/turns/learning_adapter.py:284 | services | 用户内容（学习者数据） | metadata `tool_metadata.mastery_skip_question` | 中 |
| deeptutor/services/session/turns/title_service.py:159 | services | 用户内容 | `content=title` + `metadata.title`（由会话内容生成的标题） | 低 |
| deeptutor/services/session/turns/executor.py:389 | services | 用户文件名 | metadata 含附件 `filename` | 低 |
| deeptutor/services/session/turns/lifecycle.py:579-599 | services | 异常/错误文本 | 合成 ERROR 事件将持久化错误文本原样写入 `content` | 中：错误文本可含 URL/内网主机，建议与日志层同规则清洗 |
| deeptutor/partners/channels/wecom.py:321 | partners | 合作伙伴消息 | metadata 含 message_id/msg_type/chat_type（不含正文） | 低 |

## 相关读点（不新增落盘，仅供复核）

- 导出/迁移同样携带 turn_events 全量数据：`deeptutor/services/workspace/data_migration.py:440,456,728,752`、`deeptutor/services/workspace/session_transfer.py:48` —— 属备份/导出链路，建议在保留策略中一并覆盖。

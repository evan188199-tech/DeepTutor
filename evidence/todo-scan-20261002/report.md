# TODO/FIXME 与吞错扫描报告

- 基准：HKUDS/DeepTutor `origin/main` @ `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`（v1.6.12，2026-10-02 fetch）
- 扫描范围：worktree 全量 `deeptutor/`、`deeptutor_cli/`、`scripts/`、`tests/`、`web/`（不含 node_modules/构建产物）
- 方法：rg 关键字扫描（TODO/FIXME/XXX/HACK，大小写不敏感复查）+ Python `ast` 全量 except 处理器分类（脚本 `scan_except.py`）+ TS/JS noop-catch 正则 + 全部命中点逐一人工上下文复核
- 未修改任何代码；本分支仅新增本证据目录

## 结论（跑通：PASS）

| 项 | 数字 |
|---|---|
| 真实 TODO/FIXME/XXX/HACK 标记 | **0**（8 处原始命中均为误报：TODO.md 文档引用 ×2、测试 base64 占位 `XXX` ×4、看板 `todo` 状态字面量/注释 ×2） |
| Python 生产代码 except 处理器 | 1644 个（含测试 1672） |
| 其中吞错型（body 仅 `pass`/`continue`） | 344 个（pass 208 / continue 136）；**无裸 `except:`**；宽 `except Exception` 共 1414 处（部分与吞错重叠） |
| 前端 noop catch / 空 catch | 41 处（其中测试文件 3 处） |
| 逐点复核后风险分布 | **HIGH 10 / MEDIUM 60 / LOW 315** |

说明：LOW 多为带注释的尽力而为惯用法（fsync 容错、进程已亡的 kill 竞态、解析回退默认值、finally 清理、已取消任务收尾等），不逐条展开，全量清单见 `raw-py-except.json`。

## HIGH 风险清单（10）

| 位置 | 类别 | 问题 | 上游对应 |
|---|---|---|---|
| `deeptutor/services/partners/workspace.py:317` | py swallow | 索引读失败时从空 `{"notebooks": []}` 起步后整体覆写索引文件，其余 notebook 条目被清空（数据丢失） | 无 |
| `deeptutor/services/workspace/data_migration.py:891` | py swallow | `operations()` 跳过损坏的 operation.json，`assert_no_pending_recovery()` 对损坏日志失效，迁移可在有 pending 恢复时继续 | 无 |
| `deeptutor_cli/init_cmd.py:35` | py swallow | `_reset_runtime_singletons()` 中 PathService 重置失败被吞，docstring 自述后果为"静默写错 home 目录"，无日志 | 无 |
| `deeptutor/runtime/launcher.py:146` | py swallow | 同上一逻辑的第二副本（launcher 内），失败同样静默 | 无 |
| `deeptutor/services/notebook/service.py:153` | py swallow | 索引重建时损坏的 notebook 文件被静默跳过（`except Exception: continue`），条目从列表消失且无逐条日志 | 无 |
| `web/context/QuizFollowupContext.tsx:280` | ts noop-catch | 追问会话 ID 写回笔记条目失败被吞，问答↔笔记关联静默丢失 | 无 |
| `web/components/chat/home/ChatComposer.tsx:545` | ts noop-catch | 草稿恢复失败被吞；后续 pagehide 保存路径会用当前（空）内容覆盖已存草稿 → 未发送内容丢失 | 无 |
| `web/components/reading/EpubDocumentView.tsx:411` | ts noop-catch | 阅读位置恢复失败静默返回 null，电子书从开头打开 | #1673 / PR #1686、PR #1688（同主题） |
| `web/components/reading/workspace/MediaReadingStage.tsx:240` | ts noop-catch | 播放进度保存失败被吞，续播位置静默丢失 | #1644 / PR #1645（同主题） |
| `web/components/reading/workspace/MediaReadingStage.tsx:328` | ts noop-catch | 播放进度恢复链失败被吞，视频静默从头播放 | 同上 |

## MEDIUM 风险清单（60）

### Python（40）

| 位置 | 一句话原因 |
|---|---|
| `deeptutor/services/memory/trace.py:111` | OSError 跳过整个 trace 文件，记忆分析静默缺数据 |
| `deeptutor/services/config/settings_spec.py:471` | 宽 Exception 清缓存，失败则用户改配置不生效 |
| `deeptutor/services/config/model_catalog.py:642` | 宽 Exception 静默回退默认路径，掩盖用户上下文故障 |
| `deeptutor/services/workspace/data_migration.py:789` | 非 UTF-8 文件跳过重绑，迁移后链接静默失效 |
| `deeptutor/services/workspace/dependencies.py:105` | 坏 book 清单跳过，迁移闭包漏会话 |
| `deeptutor/services/workspace/dependencies.py:214` | 坏 feature json 跳过，迁移闭包漏依赖 |
| `deeptutor/services/workspace/dependencies.py:327` | 坏 metadata_json 跳过，迁移漏引用会话 |
| `deeptutor/services/workspace/dependencies.py:345` | PocketBase 元数据坏行跳过，迁移闭包不全 |
| `deeptutor/services/codex_auth/service.py:872` | revoke 失败被吞，远端令牌仍有效且无日志 |
| `deeptutor/services/partners/workspace.py:369` | 索引读失败则列表为空，notebook 静默不可见 |
| `deeptutor/services/partners/workspace.py:432` | 删资产时索引读失败不更新，留幽灵条目 |
| `deeptutor/services/parsing/engines/mineru/readiness.py:74` | 宽 Exception 跳过扫描，误报模型未就绪 |
| `deeptutor/services/rag/pipelines/llamaindex/storage.py:175` | 损坏向量库文件逃过嵌入校验 |
| `deeptutor/services/rag/pipelines/lightrag/engine.py:199` | meta 读取失败算错工作区名，打开空库 |
| `deeptutor/services/rag/pipelines/graphrag/provider.py:119` | 宽 Exception 吞配置解析错误，回退默认 provider |
| `deeptutor/services/memory/snapshot/adapters.py:87` | 坏 notebook 文件跳过，记忆快照缺内容无日志 |
| `deeptutor/services/memory/snapshot/adapters.py:138` | 坏 co-writer 清单跳过，快照静默缺失 |
| `deeptutor/services/memory/snapshot/adapters.py:171` | 坏 book 清单跳过，快照静默缺失 |
| `deeptutor/services/memory/consolidator/modes/update.py:692` | 宽 Exception 跳过坏 L2，更新缺整面记忆无日志 |
| `deeptutor/services/memory/consolidator/modes/audit.py:477` | 宽 Exception 跳过坏 L2，审计范围静默缺失 |
| `deeptutor/services/llm/provider_core/codebuddy_provider.py:553` | interrupt 失败被吞，后台生成继续消耗无日志 |
| `deeptutor/services/sandbox/runner/server.py:136` | 内存 rlimit 失败被吞，沙箱内存保护静默失效 |
| `deeptutor/services/sandbox/runner/server.py:142` | CPU rlimit 失败被吞，CPU 限额静默失效 |
| `deeptutor/services/office_preview.py:142` | 超时后两次 kill 均失败被吞，可能残留进程 |
| `deeptutor/services/codebuddy_auth.py:79` | 取消 OAuth 流程吞宽泛 Exception，无日志 |
| `deeptutor/services/codebuddy_auth.py:99` | 登出时吞 flow.cancel 宽泛异常，无日志 |
| `deeptutor/services/sandbox/artifacts.py:26` | 不可读目录被静默跳过，产物列表悄然缺失 |
| `deeptutor/services/persona/service.py:169` | 不可读 persona 文件静默消失于列表 |
| `deeptutor_cli/init_cmd.py:41` | 配置服务缓存清理失败静默，可能读到旧 home 配置 |
| `deeptutor_cli/init_cmd.py:47` | 模型目录缓存清理失败静默 |
| `deeptutor/runtime/launcher.py:152` | RuntimeSettings 缓存重置失败静默 |
| `deeptutor/runtime/launcher.py:158` | ModelCatalog 缓存重置失败静默 |
| `deeptutor/runtime/update_worker.py:144` | 更新失败标记/自重启再失败被吞，更新可能卡死 |
| `deeptutor/runtime/launcher.py:1252` | handoff 失败时 mark_failed 也被吞，更新状态停滞 |
| `deeptutor/api/routers/settings.py:518` | UI 设置文件损坏静默回退默认值，用户偏好丢失 |
| `deeptutor/reading/references.py:118` | 存储整体损坏时所有引用源被静默丢弃 |
| `deeptutor/reading/references.py:135` | 单元读取失败静默跳过，喂给模型的内容缺失 |
| `deeptutor/api/utils/tool_options.py:97` | 工具定义加载失败静默，MCP 工具从授权列表消失 |
| `deeptutor/knowledge/progress_tracker.py:105` | 进度广播失败静默，服务端进度事件全部丢失 |
| `deeptutor/co_writer/docx_converter.py:356` | 表格行解析失败静默丢弃，转换后内容缺失 |

### 前端（20）

| 位置 | 一句话原因 |
|---|---|
| `web/app/(utility)/courses/[courseId]/page.tsx:70` | 课程状态加载失败静默，卡片渲染空态 |
| `web/app/(workspace)/partners/new/page.tsx:113` | 工具选项加载失败，创建向导工具列表为空 |
| `web/features/chat/components/ChatWorkspace.tsx:1887` | 子代理预算设置加载失败静默回退 |
| `web/features/settings/sections/DataMigrationSettingsSection.tsx:113` | 迁移操作 5 秒轮询失败静默，进度不更新 |
| `web/features/settings/sections/DataMigrationSettingsSection.tsx:136` | 操作列表初始加载失败静默，迁移记录不可见 |
| `web/components/chat/home/StandaloneComposer.tsx:615` | 子代理预算加载失败静默，预算保持空 |
| `web/components/chat/home/ConsultationTabBody.tsx:153` | 咨询身份获取失败静默，永远显示"等待中" |
| `web/components/chat/home/SessionActivityPanel.tsx:87` | 会话标题加载失败，活动面板显示裸 ID |
| `web/components/chat/home/SessionActivityPanel.tsx:103` | 笔记本名加载失败，显示裸 ID |
| `web/components/chat/home/SessionActivityPanel.tsx:120` | 书名加载失败，显示裸 ID |
| `web/components/chat/BookReferencePicker.tsx:106` | 书籍详情加载失败，详情面板空白 |
| `web/components/partners/PartnerConfigure.tsx:136` | 伙伴资产加载失败，已配置资产显示为空 |
| `web/components/partners/PartnerConfigure.tsx:164` | 工具选项加载失败，勾选列表为空 |
| `web/components/partners/PartnerComposer.tsx:143` | 斜杠命令加载失败，命令面板为空 |
| `web/components/memory/MemoryHub.tsx:66` | 快照计数失败按 0 计，记忆统计虚低 |
| `web/components/reading/library/AddMaterialsDialog.tsx:714` | 资料库列表加载失败，显示为空库 |
| `web/components/reading/workspace/useReadingWorkspace.ts:453` | 会话列表加载失败，侧栏列表为空 |
| `web/components/reading/library/MaterialLibrary.tsx:482` | 用户点重试失败被吞，无失败提示 |
| `web/components/reading/library/ReadingLibrary.tsx:512` | 重试失败被吞，仅结束转圈 |
| `web/components/chat/home/ChatComposer.tsx:658` | 发送后清空草稿失败被吞，旧草稿复活似未发送 |

## 与已开上游 issue/PR 的对应关系

开工前已查 HKUDS/DeepTutor 全部 open issue/PR（2026-10-02）：**无与"TODO/吞错清扫"主题重复的 issue 或 PR**。逐项对应：

| 本报告发现 | 上游 | 关系 |
|---|---|---|
| `EpubDocumentView.tsx:411`、`MediaReadingStage.tsx:240/328` | #1673（EPUB 阅读位置，PR #1686）、PR #1688（PDF 阅读位置） | 同主题（阅读进度静默丢失/恢复），非同一代码路径，可作补充证据 |
| `settings_spec.py:471`、`api/routers/settings.py:518` | #1630 / PR #1634 | 主题相关：设置持久化静默失败 |
| `parsing/engines/mineru/readiness.py:74` | PR #1670 | 主题相关：MinerU 本地失败原因/就绪误报 |
| `knowledge/progress_tracker.py:105` | #1612 | 主题相关：进度真实性与可恢复 |
| `rag/pipelines/llamaindex/storage.py:175` | #1478、#1481 | 主题相关：reindex 损坏 / KB 未初始化 |
| 其余 HIGH（partners/workspace.py:317、data_migration.py:891、notebook/service.py:153、init_cmd.py:35、launcher.py:146、QuizFollowupContext.tsx:280、ChatComposer.tsx:545） | 无已开上游 issue | 新发现，供人工决定是否开 issue/PR |

## 复现命令

```bash
# TODO/FIXME（0 真实命中）
rg -n --no-heading -g '*.py' -g '*.ts' -g '*.tsx' -g '*.js' -g '*.mjs' \
  -e '\b(TODO|FIXME|XXX|HACK)\b' .
rg -n --no-heading -i -g '*.py' -g '*.ts' -g '*.tsx' -g '*.js' -g '*.mjs' \
  -e '\b(todo|fixme)\b' .          # 仅 kanban 'todo' 状态字面量

# Python 吞错分类（生成 raw-py-except.json）
python3 scan_except.py <repo-root>

# TS noop catch（41 处）
rg -n --no-heading -g '*.ts' -g '*.tsx' -g '*.js' -g '*.mjs' \
  -e '\.catch\(\s*\(\s*\)?\s*=>\s*(\{\s*\}|null|undefined|false|0|\{\})\s*\)' \
  -e 'catch\s*(\([^)]*\))?\s*\{\s*\}' .
```

## 证据文件

- `raw-todo-fixme.txt` / `raw-todo-ci.txt` — TODO/FIXME 原始扫描（大小写敏感/不敏感）
- `raw-py-except.json` — Python 全部 except 处理器分类结果（含测试，含 kind 与 snippet）
- `raw-ts-swallow.txt` — 前端 noop catch / 空 catch 原始命中
- `scan_except.py` — AST 分类脚本
- `SHA256SUMS` — 以上文件校验和

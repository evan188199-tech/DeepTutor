# 崩溃场景矩阵：indexing_run.py 恢复状态机（#1612）

严重度：高 / 中高 / 中 / 中低 / 低。窗口行号以基线 `6cf793bd8` 为准。

## 矩阵总览

| ID | 崩溃场景 | 窗口位置 | 现状 | 失败后果 | 严重度 |
| --- | --- | --- | --- | --- | --- |
| S1 | preflight 哈希阶段崩溃（首个 journal 写入前） | `indexing_run.py:211-285` | 无 journal 痕迹；flock 随进程消亡释放；旧 journal 原样 | 本次尝试不可观测（previous_task_id 链断档）；无孤儿产物、无状态损坏 | 低 |
| S2 | journal 原子写中途断电/SIGKILL | `file_io.py:78-92`（tmp 写入→`:89` rename 前） | rename 原子，journal 不撕裂；`finally:90-92` 仅进程内清理 | kb_dir 留下 `tmpXXXX` 孤儿文件，无任何 GC；fsync 失败降级为限频 warning（`file_io.py:25-45`）→ 断电时"已写 checkpoint"可能回退，文档状态退回重跑（安全但浪费） | 低 |
| S3 | 运行中崩溃（state=running + 死亡 pid） | `indexing_run.py:133-162` | `visible_run` 投影 interrupted、in-flight→unknown、只读不写；未发布 version-N fail-closed（`index_versioning.py:84-87,156-157`），旧版本继续服务 | 设计成立。边界缺口：writer 无 psutil（`process_started_at=None`, `:240-242`）+ reader 有 psutil 时 `:140` 判死（活跑被投影 interrupted）；跨版本 psutil 可用性变化才触发 | 低 |
| S4 | 非 ASCII journal 被 locale 编码读回失败 | `indexing_run.py:88,100` vs `file_io.py:85` | 写 UTF-8 `ensure_ascii=False`；读 `Path.read_text()` 默认 locale 编码 → UnicodeDecodeError → `:91-98` OSError "unreadable" | 中文来源名写入 journal 后，该 KB 的 `_start`(`:232`)、`check`、`document`、`finish`、reindex API（`knowledge.py:4119`）全部永久失败；**开放 PR #1919 覆盖中** | 高 |
| S5 | journal 损坏 / 未来 schema 无隔离恢复路径 | `indexing_run.py:91-98,232` | 保留原文件（测试固化语义 `tests/knowledge/test_indexing_run.py:61-72`），但无归档/重置命令或端点 | 一次损坏（历史写入、外部编辑、schema 降级 `:95`）永久阻断该 KB：索引 500、cancel 端点（`:441`）也抛 OSError → 无法取消、无法恢复，只能人工删文件 | 中高 |
| S6 | `__exit__`/`finish` 期间 journal 变化 → 异常掩蔽 | `indexing_run.py:296-306`（`:302` 表达式内 load_run）、`:413-415` | journal 损坏或被换时 `finish`/`__exit__` 内 load_run 抛 OSError，从 `__exit__` 传播替换原始异常（Python 语义）；journal 停留 running | 原始失败根因（如 embedding 超时）从日志与 journal 双双丢失，只剩 "Indexing journal is unreadable"；锁仍正常释放（`finally:309-313`） | 中 |
| S7 | `.indexing-cancel.json` 永不清除 + 终态 TOCTOU | `indexing_run.py:440-447`（`:442` 检查→`:444` 写入）；读侧 `:107-109,350-354` | 全仓库无删除点（grep 核实：仅 `:100` 读、`:445` 写）；run 在检查与写入之间 finish 时 cancel 文件仍被写入，终态 journal 的 `cancel_requested=true`（`:107-109` 不看 state） | 现网 API task_id 均唯一（`knowledge.py:3468,3666,4241`），故"同 id 重试被陈旧取消毒化（`check():350` 立即抛 IndexingCancelled）"当前为潜在路径（`rag/service.py:86` 允许显式传 task_id）；终态误标为属性缺陷 | 中 |
| S8 | 注入 key 使 `verify_sources` KeyError | `indexing_run.py:395`（setdefault）、`:404`（`_source_paths[key]` 未捕获 KeyError）；注入面：`rag/service.py:96-98`、`llamaindex/pipeline.py:491-494`、`document_loader.py:182` | `document()` 可创建不在候选登记表 `_source_paths` 的文档（路径 resolve 差异、符号链接、外部→raw 复制后回调路径不一致） | KeyError 在 `_publish_verified` 内、`write_version_meta`（`pipeline.py:478`）之前抛出 → 索引已持久化但无发布 meta → 版本 not ready → **整轮嵌入成果作废**，journal=failed；旧版本存活可恢复 | 中 |
| S9 | `usable_version` 双真相 / meta 写后崩溃 | `llamaindex/pipeline.py:490`（记 storage_dir.name）vs `rag/service.py:116-123`（finish 用 `latest_ready_provider_version`）；窗口：`pipeline.py:478` meta 写后、`:490` 记录前崩溃 | 索引实际已 ready（meta published），journal 停留 running→投影 interrupted 且 usable_version=None | `knowledge.py:4125-4130` 视 interrupted/partial 强制全量重索引 → 成果误判为不可用；两条记录路径可能记下不同版本号，审计失真 | 中低 |
| S10 | 发布前崩溃留下的非空孤儿 version-N | `llamaindex/pipeline.py:459-463`（异常路径）+ `storage.py:47-60`（仅清空目录）；硬崩溃无清理 | `resolve_add_storage_plan`（`storage.py:59-66`）增量也写全新 guarded 目录（评审中已证伪"就地覆写"假设），旧版本始终兜底 | 孤儿目录（部分向量文件、无 meta）永久堆积；`index_versioning.py:116-118` 版本号单调递增无上限回收 | 低 |
| S11 | MinerU 输出交换窗口崩溃 | `mineru/local.py:325-336`（`:328` output→backup 与 `:330` attempt→output 之间；`:331-334` 仅覆盖进程内异常） | 崩溃于窗口内：正式输出目录缺失，旧输出滞留 `.{name}.previous-{hex}`；无任何 GC/恢复扫描 | `:203-204` 注释承诺"prior usable output survives until validated replacement"在崩溃窗口失效：缓存复用落空，重试必须全量重跑 CLI；backup/attempt 目录孤儿化 | 中 |
| S12 | worker 被 SIGKILL → mineru 子进程孤儿化 | `mineru/local.py:224-233`（Popen 无进程组/job 对象）、`:358-371`（finally 仅进程内生效） | 无父进程时无人 terminate；常规超时路径也只 kill 直接子进程（`:258-263,364-369`），孙进程可能泄漏 | 孤儿 CLI 持续占用 CPU/GPU（自身无 7200s 上限约束），attempt 目录持续写入并永久残留（`state.json` 停留 "running", `:209`） | 中 |
| S13 | 无 IndexingRun 上下文时 MinerU 无看门狗 | `mineru/local.py:240`（`if run is not None` 才启动 watch） | CLI 直用/非索引路径无 idle(600s)/总(7200s) 超时 | 解析可无限挂起 | 低 |
| S14 | `__aenter__` 双重取消窗口 | `indexing_run.py:193-202`（`:196` shield 抛出后 `:198` 再 await 期间二次 cancel） | future 被放弃，`_start` 可能在后台完成写 running journal 并持锁，aenter 直接重抛 | 锁与 running journal 泄漏至进程死亡；存活后由 `visible_run` 投影自愈，概率低 | 低 |
| S15 | checkpoint 写放大 | `indexing_run.py:356-385`（每次 phase 全量 `_save`）+ `parsing/service.py:110-113`（每行输出一次 phase）+ `:430-437`（全量 JSON+fsync） | 长文档大量输出行 → 每行全量重写 journal | 慢盘吞吐劣化；disk-full 时进度更新升级为运行失败（OSError 传播路径同 S6） | 中低 |

## 已核实成立的关键不变量（现有测试已覆盖，无需重复拆卡）

- journal 不撕裂：tmp+同目录 rename（`file_io.py:89`），Windows PermissionError 退避重试（`:48-69`）。
- 死亡 owner 的 running journal 投影 interrupted 且只读（`test_indexing_run.py:75-91`）。
- 未发布/损坏缓存 fail-closed：`.building.json` 须 meta state=published（`index_versioning.py:156-157`）；LightRAG 候选无 schema-2 meta 不 ready（`:151-165`）。
- 换源不可发布（`test_indexing_run.py:94-103`）；错误详情脱敏（`:121-125`）。
- 增量 add 与 rebuild 均写全新 guarded 目录（`storage.py:59-66`、`index_versioning.py:364-387`），旧 ready 版本始终可服务。

## 评审中证伪的假设（避免后续重复排查）

- ~~"增量 add 就地覆写已发布目录 → 撕裂索引可被查询"~~：`resolve_add_storage_plan` 总是分配新目录并带 `.building.json`，existing 仅被读入内存。
- ~~"flock 与 journal task_id 双重防护存在 TOCTOU 覆写窗口"~~：锁存活期内新 run 无法 `_start`（`indexing_run.py:226-230`），task_id 校验（`:348-349,:392,:414`）为纯防御。

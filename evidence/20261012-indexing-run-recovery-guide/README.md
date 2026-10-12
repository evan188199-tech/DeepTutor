# 长文档索引恢复机制导读（guide-indexing-run-recovery-20261012）

- 基线：`origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14）。
- 方法：只读静态导读，未修改任何源码。对象是 #1612 引入的长文档索引恢复机制：
  `deeptutor/knowledge/indexing_run.py`（447 行）状态机、checkpoint（journal）、发布校验与恢复入口，
  以及其在 `deeptutor/api/routers/knowledge.py`、`deeptutor/services/rag/service.py` 的接线。
- 行号锚均为该基线下的 `path:line`，相对仓库根目录。

## 去重声明

| 既有文档 | 轴 | 本文边界 |
| --- | --- | --- |
| `docs/guides/knowledge-base.md`（分支 `myfork/docs/guides/knowledge-base`） | KB 域总览：创建/上传/重建/检索全流程与引擎路由 | 本文只写恢复机制本身，不重复域流程 |
| `docs/guides/mineru-local-indexing.md`（分支 `myfork/dt-agen1335-mineru-indexing-guide`） | 解析引擎轴：MinerU 子进程生命周期/看门狗/缓存 | 本文只把解析缓存当作恢复的复用点引用 |
| `evidence/20261011-indexing-run-crash-window/`（分支 `evidence/indexing-run-crash-window-20261011`） | 崩溃窗口 × 严重度矩阵与补测候选 | 本文是使用者/运维者视角的操作指南，不重复窗口矩阵 |

## 文件清单

| 文件 | 内容 |
| --- | --- |
| `state-machine.md` | 状态机：journal/checkpoint 存储、run 与 document 两层状态、全部转换（附 path:line） |
| `recovery-operations.md` | 恢复操作手册：6 条可照做的使用者/运维者操作 |
| `test-clues.md` | 可拆补测线索：机制合同级测试候选（与 crash-window 的候选不重叠） |
| `SHA256SUMS` | 本目录全部文件的 SHA256 校验和 |

## 结论摘要（PASS）

机制的核心合同成立：journal 每次 `phase`/`document` 更新都以 `atomic_write_json`
原子落盘（`indexing_run.py:430-431` → `file_io.py:72-92`），崩溃后由 `visible_run`
把死主人的在途工作投影为 `interrupted`/`unknown`（只读、不落盘，`indexing_run.py:133-162`），
发布前有双重校验（源文件重哈希 `verify_sources` `:400-407` + 引擎就绪探针
`service.py:116-118`），未经验证的上下文退出一律 fail-closed 为 `failed`
（`indexing_run.py:307-308`），旧 ready 版本继续服务。

使用者/运维者的完整恢复闭环不需要碰文件系统：读状态、取消、retry、reindex
四个 API 加上重启后的孤儿任务调和（`knowledge_task_interrupted`，retryable）即可覆盖
running/partial/failed/cancelled/interrupted 五种非完成态。唯一需要人介入磁盘的是
journal 损坏场景——按设计原样保留、无管理端点（详见 crash-window 报告 S5）。

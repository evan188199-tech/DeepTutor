# 长文档索引恢复状态机崩溃窗口静态评审

- 基线：`origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14）
- 方法：只读静态评审（read-only），未修改任何源码；评审对象为 #1612 引入的
  `deeptutor/knowledge/indexing_run.py`（447 行）状态机及其直接关联面。
- 关联面：
  - `deeptutor/services/file_io.py`（atomic_write_json / fsync / rename 重试）
  - `deeptutor/services/parsing/engines/mineru/local.py`（解析 attempt 与发布交换）
  - `deeptutor/services/rag/index_versioning.py`（version-N 目录与发布元数据）
  - 消费方核对：`deeptutor/services/rag/service.py:84-124`、
    `deeptutor/services/rag/pipelines/llamaindex/pipeline.py:404-494`、
    `deeptutor/api/routers/knowledge.py:4117-4130`、
    `deeptutor/services/parsing/service.py:105-121`、
    `deeptutor/knowledge/initializer.py:111-118`
- 现有测试基线：`tests/knowledge/test_indexing_run.py`（179 行，8 个用例）。

## 文件清单

| 文件 | 内容 |
| --- | --- |
| `crash-scenario-matrix.md` | 崩溃场景 × 窗口(path:line) × 现状 × 失败后果 × 严重度矩阵 |
| `test-candidates.md` | 可直接拆卡的补测候选（含断言要点与红/绿现状） |
| `SHA256SUMS` | 本目录全部文件的 SHA256 校验和 |

## 结论摘要（PASS）

状态机的核心承诺成立：journal 写入原子（同目录 tmp+rename），崩溃后的
running journal 由 `visible_run` 投影为 `interrupted`，未发布 version-N 目录
fail-closed，旧版本继续服务，且投影是只读的（现有测试覆盖）。

评审发现 15 个窗口（S1-S15），其中值得优先拆卡的 4 个：

1. **S4 journal 编码裂缝**：`load_run` 以 locale 编码读 UTF-8 写入的
   journal（`indexing_run.py:88,100` vs `file_io.py:85`）。非 ASCII
   （中文）来源名一旦写入 journal，该 KB 的所有后续索引操作永久抛
   OSError —— 开放 PR #1919（`fix/indexing-journal-read-retry`，base
   dev）正在修复此窗口，落地前该场景为必现。
2. **S5 损坏 journal 无隔离/恢复路径**：保留语义正确，但没有任何
   管理端点或命令能归档损坏 journal，KB 被永久阻断（含 cancel 端点
   也 500，见矩阵）。
3. **S8 `verify_sources` KeyError**：`document()` 的 `setdefault`
   允许注入不在 `_source_paths` 的 key，发布校验阶段
   `indexing_run.py:404` 未捕获 KeyError，整轮嵌入成果作废。
4. **S11/S12 MinerU 发布交换与孤儿进程**：`output_dir→backup` rename
   与 attempt→output rename 之间存在"旧输出已摘下、新输出未挂上"的
   崩溃窗口，backup 与 `.mineru-attempt-*` 目录无 GC；worker 被
   SIGKILL 时 mineru 子进程（无进程组约束）继续运行最长可达
   `_LOCAL_PARSE_TIMEOUT_SECONDS` 级别。

上游重叠核对：`gh pr list -R HKUDS/DeepTutor --state open` 中仅
#1919 与本模块直接相关（S4），其余场景在开放 PR 中无覆盖；本次为
纯证据产出，不改源码、不开 PR。

# 补测候选：可直接拆卡

每条含：对应场景、建议落点、断言要点、现状（红=现基线失败 / 绿=现基线已过 /
设计缺口=需先补实现再补测）。测试命令一律限时：
`timeout 900 python -m pytest -q -p no:cacheprovider <path>`。

## T1 journal 非 ASCII 内容可读回（S4）——红，PR #1919 覆盖中

- 落点：`tests/knowledge/test_indexing_run.py`
- 断言要点：
  1. 构造含非 ASCII 来源名（如 `深度学习.pdf`）的 run，`finish()` 后
     `load_run()` 返回 dict 且 `documents` 含该 key、`error` 中文字段保真。
  2. 以 locale 编码非 UTF-8 的环境（monkeypatch
     `locale.getpreferredencoding` 或以 `PYTHONLEGACYWINDOWSSTDIO` 类
     手段模拟 cp1252）读回同一文件，
     `load_run` 仍成功 —— 锁定"读侧必须显式 `encoding='utf-8'`"
     （`indexing_run.py:88,100`）。
  3. `.indexing-cancel.json` 同样以非 ASCII task_id 走一遍读回断言。
- 依赖：若 #1919 合并则本条转绿，可直接作为其回归测试核对项。

## T2 `__exit__` 不掩蔽原始异常（S6）——红

- 落点：`tests/knowledge/test_indexing_run.py`
- 断言要点：
  1. run 体内抛 `ValueError("embedding boom")`；在 `__exit__` 触发前把
     journal 换成 `{broken`（模拟终局并发损坏）。
  2. 断言：向调用方传播的异常链保留原始 `ValueError`（`__cause__`/
     `__context__` 可为 OSError，但 `str(原异常)` 不丢失）；现基线在
     `indexing_run.py:302` 直接抛 OSError 替换原异常，本断言失败。
  3. 断言事后 `.indexing.lock` 可被新 `IndexingRun` 获取（锁已释放，
     `finally:309-313` 行为回归保护）。

## T3 陈旧 cancel 文件不得毒化同 task_id 重试（S7）——设计缺口

- 落点：`tests/knowledge/test_indexing_run.py`
- 断言要点：
  1. task_id="one" 的 run 正常 `finish("completed")`；随后手工写入
     `.indexing-cancel.json`（模拟 `request_cancel` 的 `:442→:444` TOCTOU
     终态写入）。
  2. 断言终态 journal 经 `load_run` 读回时 `cancel_requested` 对终态无语义
     影响（现状 `:107-109` 无视 state 恒为 true —— 断言其不被
     `visible_run`/reindex 判定消费）。
  3. 以相同 task_id="one" 重新 `IndexingRun(...)` `_start`：断言首个
     `check()` 不抛 `IndexingCancelled`（现基线 `:350-354` 会立即取消 →
     失败；需 `_start` 清除或按 `requested_at`/state 失效化陈旧取消）。
  4. 对照组：存活 run 的有效取消仍被 `check()` 感知（防过度修复）。

## T4 `verify_sources` 对注入 key 容错（S8）——红

- 落点：`tests/knowledge/test_indexing_run.py`
- 断言要点：
  1. run 登记一个候选源；再调用
     `run.document(未登记路径, "completed")`（复现 `:395` setdefault 注入）。
  2. 断言 `verify_sources()` 不抛 `KeyError`（`indexing_run.py:404`）：
     期望注入文档按 `invalid_output`/unknown 处理或直接跳过并记 reason，
     而非让 `_publish_verified`（`pipeline.py:476`）在 meta 写入前崩掉。
  3. 断言崩溃注入下 journal 终态为 failed 且已解析文档状态不受牵连
     （防止修复时把无 hash 文档静默标 completed）。

## T5 meta 写后、usable_version 记录前崩溃 → 不强制全量重索引（S9）——设计缺口（集成层）

- 落点：新文件 `tests/services/rag/test_indexing_receipt_version.py`
- 断言要点：
  1. 造一个 ready 的 version-N（`resolve_storage_dir_for_rebuild` +
     `write_version_meta`，复用 `test_indexing_run.py:106-118` 手法）；
     journal 模拟 interrupted + `usable_version=null`。
  2. 断言 `latest_ready_provider_version(kb_dir, "llamaindex")` 命中该版本
     （`rag/service.py:116` 的兜底已存在 —— 本条锁定该兜底不被回归）。
  3. 断言 reindex 判定（`knowledge.py:4119-4130`）对
     "interrupted 但存在 ready 版本" 的 force_reindex 决策与
     `usable_version` 投影一致（现基线强制全量重跑 —— 期望改为增量续跑
     或至少在 journal 中回填实际 ready 版本号）。
  4. 断言 `finish("partial", version=...)` 与 `data["usable_version"]`
     （`pipeline.py:490`）两条记录路径对同一次 run 写出一致版本号。

## T6 MinerU 交换窗口崩溃后的孤儿可发现性（S11）——设计缺口

- 落点：新文件 `tests/services/parsing/engines/mineru/test_local_publish_window.py`
- 断言要点：
  1. monkeypatch `Path.rename`：第一次 rename（output→backup,
     `local.py:328`）后抛 `KeyboardInterrupt` 模拟窗口中断。
  2. 断言重试解析能成功发布（raw 重解析路径），且
     `.{name}.previous-{hex}` backup 目录对后续发布交换不可见（不被误当
     output）。
  3. 断言（期望新增行为）：成功发布后同前缀 backup/`.mineru-attempt-*`
     孤儿被清理，或至少提供可测试的发现函数；现基线无任何 GC → 失败。
  4. 对照组：进程内异常时 `:331-334` 回滚仍成立（现有行为回归保护）。

## T7 psutil 混合可用性下的活性判定（S3）——红（边界）

- 落点：`tests/knowledge/test_indexing_run.py`
- 断言要点：
  1. journal `process_started_at=None`（模拟 writer 侧 psutil 缺失）、
     锁被活进程持有：断言 `visible_run` 判活（现基线 `:140`
     `create_time() == None` 恒 False → 误判死 → 失败）。
  2. 死亡 pid + 锁文件存在但锁未被持有：断言投影 interrupted（回归保护）。
  3. pid 复用：journal pid 指向存活但 `create_time` 不同的进程 → 断言
     判死（锁定 `:139-143` 的复用防护）。

## T8 MinerU 子进程组终止（S12）——设计缺口（进程级，可选）

- 落点：`tests/services/parsing/engines/mineru/test_local_child_termination.py`
- 断言要点：
  1. 用真实短命子进程（`python -c "sleep..."`）替换 mineru cmd，模拟
     watchdog 超时路径：断言直接子进程退出（现基线已过，回归保护）。
  2. 期望新增：Popen 以 `start_new_session=True`/job object 启动，断言
     孙进程随进程组终止（现基线无此约束 → 失败；先补实现再补测）。

## T9 损坏 journal 管理恢复路径（S5）——设计缺口（需新增端点/命令）

- 落点：`tests/api/routers/test_indexing_journal_recovery.py`（新）
- 断言要点：
  1. journal 置为 `{broken`：断言索引/cancel 端点返回明确错误码而非 500
     裸异常（现基线 OSError 直穿 → 失败）。
  2. 期望新增管理操作：归档为 `.indexing-run.json.corrupt-<ts>` 后 KB 可
     重新 `_start`；断言归档文件存在且新 run 的
     `previous_task_id=null`（断链可解释）。
  3. 断言归档操作需写权限门禁（复用 `_writable_kb` 依赖，防只读 KB 被
     清理）。

## T10 atomic_write_json 断电窗口（S2）——绿（回归保护）

- 落点：`tests/services/test_file_io.py`
- 断言要点：
  1. monkeypatch `Path.replace` 抛 `PermissionError`×6：断言目标文件保持
     旧内容完整 JSON、临时文件被 `finally` 清理（`file_io.py:90-92`）。
  2. monkeypatch 抛 OSError（非 PermissionError）：断言异常上抛且目标
     未被部分覆写（journal 不撕裂回归保护）。

## T11 phase 写节流（S15）——设计缺口（性能）

- 落点：`tests/knowledge/test_indexing_run.py`
- 断言要点：
  1. monkeypatch 计数 `IndexingRun._save`；循环调用
     `phase(activity=...)` N=500 次（仅 activity 变化、phase/current 不变）。
  2. 期望断言 `_save` 次数远小于 N（如节流窗 ≥1s 内 ≤1 次或按字节阈值），
     同时 `last_progress_at` 语义不回退；现基线 N=N → 失败（先补节流
     实现再补测）。
  3. 对照组：phase/current 变化时必须立即落盘（checkpoint 语义不受节流
     影响）。

## 拆卡优先级建议

1. T1（高，等 #1919 落地后核对）、T4（中，防成果作废）、T2（中，可诊断性）
2. T3、T6（中）
3. T7、T9、T5
4. T8、T10、T11

# 宽泛 except 分型扫描报告（AGEN-370 · 接续 DT-22）

- **扫描对象**: `/Users/Shared/DeepTutor` worktree（只读）· `origin/main` @ `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`（v1.6.12，与 DT-22 附录 A 同一提交，行号零偏移）
- **扫描日期**: 2026-10-04（UTC）
- **扫描范围**: `deeptutor` / `deeptutor_cli` / `scripts` / `tests`（与 DT-22 同口径），AST 级识别 `except Exception` / `except BaseException`
- **产物**: `scan_broad_except.py`（扫描脚本）、`py_broad_excepts.json`（明细）、`appendix_a_baseline.json`（附录 A 基线）、`classification.json`（121 条三型归属）、`extract_appendix_a.py` / `dump_context.py`（复现工具）、`SHA256SUMS`
- **上游关联 PR**: #1700 / #1703 / #1704 / #1706（均未合并，见 §4）

## 1. 结论（PASS）

- 4 个目录共扫描 1767 个 Python 文件，`except Exception/BaseException` 共 **1477** 处（含非静默）；其中"处理体仅 pass/continue/…"的静默处理器 **121** 处。
- 与 DT-22 附录 A 的 **118** 条逐一按 `file:line` 对齐：**118/118 全部命中，零漂移**（DT-22 扫描基于同一提交）。
- 本扫描新增发现 **3** 条附录 A 漏网条目（元组类型中含 `Exception`，如 `(json.JSONDecodeError, Exception)`，DT-22 的类型名提取未识别），已一并分型，标记 `source=scan_extra`。
- 每条均有三型归属与理由（`classification.json` 字段 `category` / `reason`）。

## 2. 三型分布

| 分型 | 数量 | 占比 | 说明 |
| --- | --- | --- | --- |
| 应上抛（reraise） | 2 | 1.7% | 吞掉导致状态不可见/不可诊断，至少必须记录后上抛或落盘 |
| 可收窄（narrowable） | 13 | 10.7% | 异常面明确，收窄到具体类型即可，宽泛捕获会掩盖逻辑 bug |
| 尽力而为语义（best_effort） | 106 | 87.6% | 清理/通知/回退等有意吞掉；建议补 debug/warning 日志，不改语义 |

总体判断：**87.6% 的宽泛捕获是有意的尽力而为语义**，问题不在"吞"本身，而在"吞得无痕"——全部 121 处中仅 15 处需要改变控制流（上抛或收窄），其余补日志即可。

### 2.1 应上抛（2 处，均已有上游 PR）

| 位置 | 理由 | 关联 PR |
| --- | --- | --- |
| `deeptutor/runtime/launcher.py:1252` | mark_failed 失败被吞则更新任务永久 pending 且无任何痕迹；至少必须记录（PR #1704 已改为记录双错误） | #1704 |
| `deeptutor/runtime/update_worker.py:144` | 失败恢复路径（标记失败+触发重启）整体静默，自更新失败无诊断线索；PR #1704 已部分覆盖（store.load 失败留痕），外层仍静默 | #1704 |

### 2.2 可收窄（13 处）

| 位置 | 异常类型 | 归属理由 / 收窄建议 |
| --- | --- | --- |
| `deeptutor/api/routers/knowledge.py:4353` | `Exception` | 仅解析进度时间戳，datetime.fromisoformat 只会抛 ValueError；PR #1706 已收窄并记录 |
| `deeptutor/api/routers/knowledge.py:4402` | `Exception` | 同上，时间戳解析失败面只有 ValueError；PR #1706 已收窄并记录 |
| `deeptutor/services/memory/snapshot/adapters.py:51` | `Exception` | ts 已由 isinstance 限定为 str，fromisoformat 只抛 ValueError，收窄即可 |
| `deeptutor/services/storage/file_library.py:205` | `Exception` | 清理空父目录只会抛 OSError；宽泛捕获会掩盖循环内逻辑 bug（如路径判断写错） |
| `deeptutor/api/routers/reading.py:518` | `Exception` | URL 解析失败本就是 ValueError（noqa 注释亦说明）；收窄即可 |
| `deeptutor/api/routers/settings.py:518` | `Exception` | 设置文件损坏静默回退默认且无痕，用户配置无痕丢失；应收窄 (OSError, json.JSONDecodeError) 并 warning |
| `deeptutor/api/routers/settings.py:2247` | `Exception` | 导览缓存读取，收窄 (OSError, json.JSONDecodeError) + debug 即可 |
| `deeptutor/runtime/launcher.py:638` | `Exception` | marker 读取失败即全量重拷（安全但浪费）；收窄 (OSError, json.JSONDecodeError) + debug |
| `deeptutor/runtime/launcher.py:787` | `Exception` | 构建指纹 marker 同上 |
| `deeptutor/runtime/launcher.py:943` | `Exception` | dev lock 读取，收窄 (OSError, json.JSONDecodeError) 即可 |
| `deeptutor/services/memory/snapshot/adapters.py:56` | `Exception` | fromtimestamp 失败面为 (ValueError, OSError, OverflowError)，范围明确可收窄 |
| `deeptutor/agents/research/utils/citation_manager.py:433` | `(json.JSONDecodeError, Exception)` | (json.JSONDecodeError, Exception) 元组冗余；LLM 答案解析失败面为 (ValueError, TypeError, json.JSONDecodeError)，收窄并删冗余 |
| `deeptutor/knowledge/progress_tracker.py:105` | `(ImportError, Exception)` | (ImportError, Exception) 元组冗余；广播失败面为 ImportError + RuntimeError（内层已单独处理），收窄/简化即可 |

### 2.3 尽力而为语义（106 处，按主题归组）

| 主题 | 数量 | 代表位置 | 补日志建议 |
| --- | --- | --- | --- |
| WS 收尾清理（close/reset/错误帧） | 16 | `deeptutor/api/routers/knowledge.py:4480` | debug 即可，勿用 warning 刷屏 |
| 进度/遥测回调 | 6 | `deeptutor/api/routers/knowledge.py:3952` | debug/warning；回调属可选通知 |
| 单例/缓存重置 | 7 | `deeptutor/runtime/launcher.py:146` | warning（写入会落错目录，PR #1704 同款） |
| channel 停机/断连清理 | 12 | `deeptutor/partners/channels/matrix.py:529` | debug |
| 回退链（fallback 语义） | 10 | `deeptutor/services/rag/pipelines/graphrag/provider.py:119` | debug 记录走了哪条回退 |
| 文件/文档解析容错 | 8 | `deeptutor/co_writer/docx_converter.py:356` | debug + 跳过计数 |
| 可选模块/工具探测 | 4 | `deeptutor/api/utils/tool_options.py:97` | debug 记录被跳过对象 |
| 展示性计数/元数据 | 4 | `deeptutor/knowledge/manager.py:567` | warning（PR #1706 同款） |
| 其它单点清理/便利性 | 39 | `deeptutor/api/routers/question.py:131` | 逐条见 classification.json |

## 3. Top10（按失败后果排序）

| # | 位置 | 分型 | 一句话失败后果 | 修复建议 | 关联 PR |
| --- | --- | --- | --- | --- | --- |
| 1 | `deeptutor/runtime/update_worker.py:144` | 应上抛 | 自更新失败时 mark_failed 与触发重启均无痕，升级可能停滞且无诊断线索，用户侧表现为"更新卡住"。 | 复核并补齐 PR #1704：外层 mark_failed/重启失败也写入持久化日志（store.log_path），保留 return 1 语义。 | #1704 |
| 2 | `deeptutor/runtime/launcher.py:1252` | 应上抛 | handoff 失败无法落盘，更新任务永久 pending、无告警，重启后仍在旧版本。 | 复核 PR #1704（已记录双错误），确认日志写入 store.log_path 而非 stdout。 | #1704 |
| 3 | `deeptutor/knowledge/manager.py:2130` | 尽力而为语义 | mtime 记录静默失败会破坏增量同步判据，表现为每轮全量重扫或漏检变更。 | 复核 PR #1706 的 warning 方案；进一步可收窄 (OSError, ValueError)。 | #1706 |
| 4 | `deeptutor/knowledge/manager.py:567` | 尽力而为语义 | embedding 签名/索引版本不落库，UI 版本标识与实际索引脱节，排查索引问题失去依据。 | 复核 PR #1706 的 error 日志方案即可，语义保持 best-effort。 | #1706 |
| 5 | `deeptutor/api/routers/knowledge.py:3952` | 尽力而为语义 | ERROR 进度不落盘，前端进度条停在 running，用户误以为仍在重建。 | 复核 PR #1706 的 warning 方案；收窄到 (OSError, ValueError)。 | #1706 |
| 6 | `deeptutor/api/routers/settings.py:518` | 可收窄 | 设置文件损坏时静默重置默认，用户自定义 UI 配置无痕丢失且无从发现。 | 收窄 (OSError, json.JSONDecodeError)，并 warning 记录损坏路径与原因。 | — |
| 7 | `deeptutor/services/codex_auth/service.py:872` | 尽力而为语义 | revoke 失败无痕：服务器侧 token 仍有效而本地已清除，构成安全审计盲区。 | warning 日志注明"吊销失败，token 可能仍有效"并附异常摘要；不改变登出语义。 | — |
| 8 | `deeptutor/utils/document_images.py:557` | 尽力而为语义 | 损坏图片静默跳过，文档图文不完整且无任何计数，用户不知道少了哪些图。 | 收窄 (RuntimeError, ValueError)，累计 skipped 计数并在提取结果中返回/记日志。 | — |
| 9 | `deeptutor/services/rag/pipelines/graphrag/provider.py:119` | 尽力而为语义 | catalog 解析失败静默回退 legacy provider，可能用错模型且无日志，问题极难定位。 | 加 warning 记录回退原因；尽量收窄到配置/目录类异常，保留兜底语义。 | — |
| 10 | `deeptutor/services/storage/file_library.py:205` | 可收窄 | 空目录清理失败或循环内逻辑 bug 均无痕，文件库残留空目录且掩盖代码错误。 | 收窄 OSError + debug 日志；让非 OSError（逻辑 bug）自然暴露。 | — |

## 4. 上游 PR 交叉核对（去重）

开工前已核对上游：四个开放 PR 与本清单的关系如下（本报告不开新 PR，修复卡片应优先复核对应 PR 而非重复实现）：

| PR | 覆盖本清单条目 | 方式 | 审查结论 |
| --- | --- | --- | --- |
| #1704 runtime/cli 单例与自更新 | 8 处（idx [10, 11, 65, 66, 67, 99, 100, 101]；idx 11 为部分覆盖） | 保留宽泛捕获，补 logger.exception/warning；update_worker 为 store.load 失败新增落盘恢复日志 | 方向正确，与本清单 2 处"应上抛→至少记录"结论一致；建议补外层 mark_failed/重启失败的留痕后合并 |
| #1706 knowledge 进度/状态/同步 | 8 处（idx [0, 1, 2, 3, 4, 5, 8, 9]） | 保留宽泛捕获，按级别补日志（close→debug，reset→warning，进度→warning） | 分级得当，与 §2.3 建议一致；未收窄异常类型，可后续跟进 |
| #1703 embedding/图片进度 | 3 处（idx [12, 13, 16]） | 进度回调失败 warning + 测试 | 与本清单 best_effort 定性一致 |
| #1700 DOCX 表格行 | 1 处（idx [48]） | 失败行保留占位并 warning | 比静默跳过更好，已含测试 |

合计：**20 处已有上游 PR 覆盖**（含 1 处部分覆盖），剩余 101 处为潜在新修复卡片的范围；其中优先级最高的是 §2.2 的 13 处收窄项。

## 5. 新增发现（附录 A 之外）

DT-22 的异常类型名提取未识别元组中的 `Exception` 成员，本扫描补齐 3 条（均已分型，见 `classification.json` 尾部）：

- `deeptutor/agents/research/utils/citation_manager.py:433` — `(json.JSONDecodeError, Exception)` → 可收窄：(json.JSONDecodeError, Exception) 元组冗余；LLM 答案解析失败面为 (ValueError, TypeError, json.JSONDecodeError)，收窄并删冗余
- `deeptutor/api/routers/book.py:1514` — `(asyncio.CancelledError, Exception)` → 尽力而为语义：fanout 任务收尾，元组冗余可简化为 gather(return_exceptions=True) 惯用法
- `deeptutor/knowledge/progress_tracker.py:105` — `(ImportError, Exception)` → 可收窄：(ImportError, Exception) 元组冗余；广播失败面为 ImportError + RuntimeError（内层已单独处理），收窄/简化即可

## 6. 复现

```bash
cd <DeepTutor worktree @ ef2d9e5c>
python3 evidence/broad-except-scan-2026-10-04/scan_broad_except.py . --out /tmp/scan.json
python3 - <<'EOF'
import json
s = json.load(open('/tmp/scan.json'))
c = json.load(open('evidence/broad-except-scan-2026-10-04/appendix_a_baseline.json'))
keys = {(e['path'], e['line']) for e in s['entries']}
missing = [r for r in c['rows'] if (r['file'], r['line']) not in keys]
print('coverage:', len(c['rows']) - len(missing), '/', len(c['rows']))
EOF
sha256sum -c evidence/broad-except-scan-2026-10-04/SHA256SUMS
```

## 7. 验收对照

1. **覆盖附录 A 全部 118 条，每条有三型归属与理由** — ✅ 118/118 命中并分型（另加 3 条 scan_extra，共 121）。
2. **不修改任何产品代码，产物只进证据目录** — ✅ 仅新增 `evidence/broad-except-scan-2026-10-04/`，未触碰任何源码文件。

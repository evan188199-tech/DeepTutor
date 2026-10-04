# memory snapshot `_iso` 时间解析失败路径 — 测试与下游后果说明

- 卡片：AGEN-419（DT-22 HIGH，GLM 储备卡 `deeptour/test-memory-snapshot`）
- 分支：`agent/dt419-snapshot-iso-tests`（基于 origin/main @ `ef2d9e5c`，release v1.6.12）
- 目标：`deeptutor/services/memory/snapshot/adapters.py:46-58` 的 `_iso`
- 性质：**只补测试锁定现状，不改任何产品代码**

## 1. `_iso` 现状

```python
def _iso(ts: float | int | str | None) -> str:
    if isinstance(ts, str):
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return ts
        except Exception:
            pass
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except Exception:
            pass
    return ""
```

两处解析都被裸 `except Exception: pass` 吞掉，失败一律静默降级为 `""`。
实测（Python 3.13.13 / macOS）当前行为：

| 输入 | 输出 | 说明 |
| --- | --- | --- |
| `"2026-01-15T10:30:00"` | 原样返回 | 合法 ISO，**不归一化** |
| `"2026-01-15T10:30:00+00:00"` / `"+08:00"` | 原样返回 | 含偏移同理 |
| `"2026-01-15 10:30:00"` | 原样返回 | 空格分隔，3.11+ 可解析 |
| `"2026-01-15"` | 原样返回 | 仅日期 |
| `"2026-01-15T10:30:00Z"` | 原样返回（保留 `Z`） | Z 分支解析成功后返回**原始串**，非 `+00:00` 归一化形式 |
| `1737000000` / `1737000000.5` | `"2025-01-16T04:00:00+00:00"` 等 | 数字 → UTC ISO |
| `True` / `False` | `"1970-01-01T00:00:01+00:00"` 等 | `bool` 是 `int` 子类的隐性 quirk |
| `"not-a-date"` / `""` / `"not-a-dateZ"` | `""` | ValueError 被吞 |
| `"1737000000"`（数字字符串） | `""` | str 永远到不了数字分支 |
| `"2026-13-45T99:99:99"` | `""` | 形状合法、取值越界 |
| `None` | `""` | |
| `1e30` / `-1e30` / `inf` / `nan` | `""` | 异常类型平台相关（macOS：OverflowError / ValueError），全被吞 |

## 2. 测试集与结果

文件：`tests/services/memory/test_snapshot_adapters_iso.py`，**18 个用例**。

运行：

```bash
.venv/bin/python -m pytest tests/services/memory/test_snapshot_adapters_iso.py -v
# 18 passed in 0.36s  (Python 3.13.13, pytest 9.1.1)
```

结果：**18 PASS / 0 FAIL**；ruff check / format 通过；相邻套件
`test_snapshot_adapters.py + test_snapshot_probes.py + test_recall.py` 共 **25 passed**，无回归。

覆盖三类路径（对应验收 1）：

- 合法 ISO（4 例）：naive / 带偏移 / 空格分隔 / 仅日期 → 原样返回、不归一化
- Z 后缀（1 例）：解析成功但返回原始 `Z` 串；与同刻 `+00:00` 形式不等（混合格式共存的根源）
- 非法输入（8 例）：垃圾串 / 空串 / 垃圾+Z / 日历越界 / 数字字符串 / `None` / epoch 越界 / `nan`+`inf` → 全部静默 `""`
- 数字路径（3 例）：int / float / bool quirk
- 传播断言（2 例，见 §3）

## 3. 非法输入的下游后果（验收 2）

`""` 一旦进入 `Entity.ts` / `EntityStamp.ts`，按消费点分别产生以下后果：

### 3.1 `recall.recent` 静默剔除（保留/召回策略影响）

`deeptutor/services/memory/recall.py:172-174`：

```python
parsed = _parse_ts(stamp.ts)
if parsed is None or (cutoff is not None and parsed < cutoff):
    continue
```

`_parse_ts("")` 返回 `None` → 实体被**无声排除**出"最近活动"列表。内容还在、
快照里也有，但学习者的时间线里看不到它。已用测试
`test_recent_recall_drops_entities_with_unusable_stamps` 固化该行为。

### 3.2 L2 合并排序被钉在最前

`deeptutor/services/memory/consolidator/modes/update.py:151-154`：

```python
all_entities = sorted(
    snap.read_snapshot(surface),
    key=lambda e: (e.ts or "", e.id),
)
```

词法排序下 `""` 小于一切非空串：坏时间戳实体被**钉在 L2 处理序列最前**，
无论真实新旧。实体按此顺序拼接、切块进入有限 budget，坏戳实体因此挤占
chunk 边界，改变哪些内容进哪个块。实测演示：

```
L2 key 排序输入：('', 'zzz-late-real'), ('2026-01-15T10:30:00', 'aaa'), ('2026-12-01T00:00:00', 'bbb')
实际顺序       ：['zzz-late-real', 'aaa', 'bbb']   ← 坏戳实体排第一
```

### 3.3 混合格式词法排序 ≠ 时间排序

`_iso` 解析成功返回**原始串**，同一个实体池会同时存在
`Z`、`+00:00`、naive、空格分隔四种"合法"格式。两处词法排序
（`update.py:153`、`recall.py:127` `hits.sort(key=lambda hit: hit.ts, reverse=True)`）
的比较结果与真实时间顺序背离。实测演示（同一组时间戳）：

```
词法序（代码实际使用）：'' → 01-15T10:30:00 → 01-15T10:30:00+00:00 → 01-15T10:30:00Z
                        → 01-31T23:00:00+00:00 → 02-01T00:00:00+14:00
真实时序            ：01-15T10:30:00 → 01-15T10:30:00Z → 01-15T10:30:00+00:00
                        → 02-01T00:00:00+14:00(=01-31T10:00Z) → 01-31T23:00:00+00:00 → ''
```

最直观的背离：`2026-02-01T00:00:00+14:00`（真实时刻 01-31 10:00 UTC）在词法上
排在 `2026-01-31T23:00:00+00:00` **之后**，实际早了 13 小时；同一时刻的
`Z` 与 `+00:00` 两种写法也占据不同词法位置（"newest first" 列表会因此错序）。

### 3.4 `days_ago` 退化为 None

`recall.py:80-88`：`days_ago("")` 返回 `None`，hit 带着"未知年龄"下发，
"多少天前"这一召回权重对该实体失效（配合 §3.1 通常直接消失）。

### 3.5 附带隐患：naive/aware 混排无法按 datetime 比较

对含 naive 与带偏移两种格式的池做 `datetime` 级比较会直接
`TypeError: can't compare offset-naive and offset-aware datetimes`
（`recall._parse_ts` 已按 UTC 兜底 naive，但 `update.py:153`、`recall.py:127`
的排序根本不解析，走的是词法序，见 §3.3）。当前代码未触发该 TypeError，
属"未来任何改为按时间排序的实现"必须先处理的地雷。

## 4. 与上游 PR #1707 的关系

上游 [PR #1707](https://github.com/HKUDS/DeepTutor/pull/1707)（2026-10-04 开，
"fix: log silently swallowed failures in five services"）修改了**同一文件**，
但只覆盖 corrupt notebook / co-writer manifest / book manifest 的吞错路径，
**未触及 `_iso`**（diff 中无 `_iso` 相关改动）。本卡测试与其不冲突；若 #1707
合入，本测试集应继续通过，因为它断言的是 `_iso` 当前契约。

## 5. 修复方向（供后续修复卡参考，本卡未实施）

- `_iso` 失败分支至少补 `logger.warning`（与同文件 `read_entities` 的日志风格一致）；
- 解析成功时归一化返回 `datetime.fromisoformat(...).isoformat()`，消除 Z/偏移/naive 混格式池；
- 数字字符串（`"1737000000"`）是否回落数字分支，需结合写入端数据形状决策。

# scan: Python JSON 序列化边界静态清点（AGEN-979）

- 扫描对象：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release: v1.6.13）
- 扫描范围：`deeptutor/`、`deeptutor_cli/`、`scripts/`（排除 `tests/`、`test_*.py`、`conftest.py`），共 1041 个产品 Python 文件
- 方式：AST 静态扫描（stdlib-only），单作用域数据流（赋值 → json.dumps/json.dump 传播）；运行时小样本验证
- 去重说明：与 scan-broad-excepts（异常轴）、scan-error-messages（文案轴）、scan-ts-types（TS 类型轴）无重叠；扫描前已核对上游开放 PR/分支，无同轴既有工作

## 结论

共 **44 条**条目（31 个文件），分级分布：

| 分级 | 规则 | 条数 |
|---|---|---|
| low | J1 `default=str` 掩盖类型错误 | 32 |
| medium | J5 反射式/pydantic python-mode 载荷 | 12 |
| high | J2/J2b/J3/J4（NaN/Infinity、显式非序列化类型、allow_nan=True） | **0** |

datetime/NaN/显式非序列化类型三条轴在单作用域静态分析下**未发现命中**：抽样人工复核（model_history、memory routers、audit、migration、trace、consolidator runs 等）显示序列化边界普遍已用 `.isoformat()`/`str()` 归一，`allow_nan` 全库仅 4 处且均为 `False`（fail-fast）。这一干净结果与仓库已有的 datetime-naive / ts-datetime 扫描轴的后续治理一致。

## 规则集

| 规则 | 分级 | 含义 |
|---|---|---|
| J1 | low | `json.dumps(..., default=str)`：非序列化值被静默字符串化（datetime→"2026-…"、对象→"<…>"），掩盖类型漂移，产生 schema 不稳定载荷 |
| J2 | high | `float("nan"/"inf")`、`math.nan/inf` 流入 json 序列化且未传 `allow_nan=False` → 载荷出现 `NaN`/`Infinity` token，违反 RFC 8259，严格解析端报错 |
| J2b | medium | 同上但 `allow_nan=False`：运行时 `ValueError`（fail-fast，崩溃点明确） |
| J3 | high | datetime/Decimal/set/frozenset/bytes/Path/struct_time/UUID 流入序列化且无 `default=` → `TypeError` |
| J4 | medium | 显式 `allow_nan=True`：允许非法 JSON token 进入载荷 |
| J5 | medium | `json.dumps(x.model_dump())` 未传 `mode="json"`（pydantic python-mode 保留 datetime/UUID/Decimal/enum 对象）；或 `asdict()/vars()/__dict__` 反射式载荷无 `default=`（字段类型静态不可证） |

## 条目清单（44 条，file:line 锚点）

### J5 · medium · model_dump() python-mode（9 条）

math_animator 与 visualize 的 agent prompt 组装把 `model_dump()`（python-mode）直接交给 `json.dumps`；若模型含 datetime/enum 字段即 TypeError，当前能否触发取决于各模型字段类型（静态不可证，见运行时验证 #9/#10）：

- `deeptutor/agents/math_animator/agents/code_generator_agent.py:88`
- `deeptutor/agents/math_animator/agents/code_generator_agent.py:89`
- `deeptutor/agents/math_animator/agents/concept_design_agent.py:48`
- `deeptutor/agents/math_animator/agents/summary_agent.py:48`
- `deeptutor/agents/math_animator/agents/summary_agent.py:49`
- `deeptutor/agents/math_animator/agents/summary_agent.py:50`
- `deeptutor/agents/math_animator/agents/visual_review_agent.py:66`
- `deeptutor/agents/visualize/agents/code_generator_agent.py:58`
- `deeptutor/agents/visualize/agents/review_agent.py:54`

同仓库 `deeptutor/learning/storage.py`（229/676/1704）与 `deeptutor/services/mcp/`（config.py:142、user_config.py:210）已用 `model_dump(mode="json")`，可作为修复范式。

### J5 · medium · asdict()/vars() 反射载荷（3 条）

- `deeptutor/services/memory/snapshot/store.py:80` — `json.dumps(asdict(change))` 写 JSONL 变更日志，ChangeEntry 字段类型静态不可证
- `deeptutor/services/memory/trace.py:70` — `json.dumps(asdict(event))` surface-trace 写入（外层 try/except 吞掉失败 → 一行 trace 静默丢失）
- `deeptutor/services/rag/pipelines/llamaindex/storage.py:254` — `json.dumps(asdict(config))` 进 SHA256 缓存键计算，字段类型变化会直接崩缓存键

### J1 · low · default=str 掩盖（32 条）

按文件分组（file:line）：

- agents/loop/context_budget.py:327
- api/routers/co_writer.py:509、api/routers/co_writer.py:513、api/routers/co_writer.py:515
- api/routers/partners.py:1542
- api/routers/unified_ws.py:71
- api/utils/task_log_stream.py:22、api/utils/task_log_stream.py:159
- app/facade.py:281
- book/learning_overlay.py:33、book/storage.py:55
- capabilities/course_study/tools.py:145、capabilities/course_study/tools.py:189
- co_writer/storage.py:55
- deeptutor_cli/kb.py:175、deeptutor_cli/kb.py:208、deeptutor_cli/kb.py:411、deeptutor_cli/notebook.py:31、deeptutor_cli/notebook.py:50、deeptutor_cli/session_cmd.py:68
- knowledge/manager.py:1436
- logging/formatters.py:39
- reading/extensions.py:61
- runtime/agentic/tool_dispatch.py:380
- runtime/coordination/redis.py:325、runtime/coordination/redis.py:362、runtime/coordination/redis.py:421
- services/session/event_preview.py:123、services/session/event_preview.py:135、services/session/sqlite_store.py:46
- services/workspace/data_migration.py:748
- video_learning/marks.py:202

（除 CLI 展示路径 `deeptutor_cli/*` 与日志 formatter 外，其余均为 SSE/WS 外发载荷、持久化存储或 cache key 的序列化边界。`default=str` 在这些位置把类型错误转成静默字符串化，建议收敛为显式类型归一或 `mode="json"`。）

## 运行时验证（verify_samples.py）

- **锚点复核：44/44 全部通过**（每条 finding 的 file:line 均实含 json.dumps/json.dump 调用）
- **行为复现：10/10 通过**，覆盖全部规则族（不导入产品代码，仅构造最小同型值验证边界行为）：
  1. datetime → TypeError ✓
  2. Decimal → TypeError ✓
  3. UUID → TypeError ✓
  4. bytes → TypeError ✓
  5. `uuid4().hex`（str）正常序列化（假阳性防护）✓
  6. `float("nan")` → 载荷出现 `NaN` token（RFC 8259 非法）✓
  7. `allow_nan=False` → ValueError（fail-fast）✓
  8. `default=str` 静默字符串化 ✓
  9. pydantic `model_dump()`（python-mode）含 datetime 字段 → TypeError ✓
  10. `model_dump(mode="json")` → ISO 字符串，正常序列化 ✓

合计 54/54 PASS（`verify_output.txt`）。

## 复跑方式

```bash
# 静态扫描（确定性：同输入字节级一致，已验证两次运行 sha256 相同）
python3 evidence/json-serialization-20261007/scan_json_serialization.py deeptutor deeptutor_cli scripts > findings.json

# 运行时验证（锚点全量 + 行为复现）
python3 evidence/json-serialization-20261007/verify_samples.py . deeptutor deeptutor_cli scripts -- evidence/json-serialization-20261007/findings.json
```

## 局限

- 数据流为单作用域近似：跨函数边界（helper 返回含 datetime 的 dict 后由调用方 dumps）不可见，J2/J3 轴的"零命中"限于该口径；跨作用域卫语句（try/except 包裹的序列化）不计入风险分级。
- J5 属"静态不可证"类：命中点是否实际触发取决于运行时字段类型，修复成本低（统一 `mode="json"`），建议按防御性收敛处理。
- tests 目录未扫描（本卡口径为产品代码）。

## 未做

- 未修改任何产品代码；未开上游 PR。PR 草稿见完成评论，由人决定是否提交。

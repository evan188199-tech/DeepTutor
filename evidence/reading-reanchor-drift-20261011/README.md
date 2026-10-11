# 阅读 selector 再锚定 · 文档漂移健壮性评估（AGEN-1802）

评估对象：`ReadingStore` 结构化修订（revision upgrade）时的 annotation selector
再锚定路径，以及前端渲染时的 `resolveTextSelectors` 再锚定。基线为上游
HKUDS/DeepTutor `origin/main` @ `6cf793bd8`（release v1.6.14，含 #1376 对 #971
的合并现状）。

## 产物

| 文件 | 内容 |
| --- | --- |
| `run_backend.py` | 后端漂移 fixture（15 个场景，直连真实 `ReadingStore`，离线、临时目录、不启动服务） |
| `backend_results.json` | 后端逐场景观测结果（原始数据） |
| `backend-drift-matrix.md` | 漂移场景 × 行为矩阵与解读 |
| `run_frontend.mjs` | 前端漂移 fixture（11 个场景，直接 import 真实 `web/lib/reading-w3c-annotations.ts`） |
| `frontend_results.json` | 前端逐场景观测结果 |
| `frontend-drift-matrix.md` | 前端场景矩阵 |
| `gaps.md` | 缺口清单（每条含 `path:line` 与中性复现条件） |
| `SHA256SUMS` | 以上文件校验和 |

## 复现方式

```bash
# 后端（离线；仅写临时目录，不触碰仓库源码、不启动服务）
/Users/Shared/DeepTutor/.venv/bin/python run_backend.py --out backend_results.json

# 前端（Node >= 22.18 自带 type stripping；无 bundler / node_modules 依赖）
node run_frontend.mjs --out frontend_results.json
```

fixture 设计：每个场景从同一份 3 单元基础文档出发（标题段 + 正文两段 ×3 单元），
按场景注入一种漂移（标题改写 / 段落增删 / 词替换与词扩展 / 同单元重复 /
跨单元复制 / 句子跨单元搬移 / 整单元删除 / 旧版无 selector 行 / 上下文过期
两步漂移 / 大小写 / Unicode NFD），然后读取迁移后的 resolution、locator、
revision、position 有效性、partial-word 锚定、stored prefix/suffix 是否过期。

## 去重说明

- `test-reading-grounding`（AGEN-1297）覆盖 grounding 轴，与本卡 re-anchor
  漂移轴不重叠。
- 上游已覆盖的迁移行为（`tests/reading/test_ingestion.py:128,174,227,260,292`）：
  可靠 quote 迁移 resolved、按 material 分文件处理、quote 消失 unresolved、
  重复 quote ambiguous、旧修订审计保留。本 fixture 不重复断言这些基线，
  只在其上叠加漂移积累与边界场景。
- 卡面已注明 up-971 已由上游 #1376 合并修复，本卡只产证据，不拆修复卡。

## 结论摘要

基础健壮性成立：无漂移、空白重排、段落增删、句子跨单元搬移等场景下
resolved 迁移正确，quote 消失/重复分别落到 unresolved/ambiguous，不会画到
错误段落。发现 9 个缺口（G1–G9），最重要的是：词扩展导致词内半截锚定（G1）、
迁移后 context 永不刷新导致跨修订漂移积累成 ambiguous（G2）、跨单元场景
context 失效且无 locator 邻近先验（G3）、旧版无 selector 行被一刀切标
unresolved 且前端行为与之矛盾（G4/G9）。详见 `gaps.md`。

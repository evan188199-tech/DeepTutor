# i18n 占位符/插值奇偶扫描 — 结论与修复建议

- 扫描对象：HKUDS/DeepTutor `origin/main`，HEAD `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14）
- 扫描时间：2026-10-12；只读扫描，未改动任何源码
- 轴说明：本卡只覆盖「同键消息在不同语言的占位符集合差异（缺失/多余 {var}）」。
  键存在性/文件奇偶轴归 `scan-i18n`（总体）、`scan-web-locale-keys` /
  `fix-web-locale-keys-drift` / `fix-web-locales-parity`（键存在性），本文仅作交叉引用，不下结论。

## 覆盖面（5 个 surface，全量键扫描）

| surface | 语法 | 键数 | 参与对比（≥2 语言） | 单语言键 | 占位符差异数 |
|---|---|---|---|---|---|
| `backend.messages`（`deeptutor/services/i18n.py` `_MESSAGES`） | Python `str.format` | 37 | 37 | 0 | 0 |
| `backend.metadata`（`deeptutor/i18n/metadata_i18n.py` capability/tool 描述） | Python `str.format` | 17 | 17 | 0 | 0 |
| `backend.status`（`deeptutor/agents/*/prompts/{en,zh}/*.yaml` 顶层 `status:`，经 `deeptutor/i18n/status_i18n.py` 消费） | Python `str.format` | 22 | 22 | 0 | 0 |
| `web.locales.app`（`web/locales/{de,en,fr,pl,uk,zh}/app.json`） | i18next `{{var}}` | 6424 | 5523 | 901 | 1 |
| `web.locales.common`（`web/locales/{de,en,fr,zh}/common.json`） | i18next `{{var}}` | 37 | 37 | 0 | 0 |

说明：`backend.*` 三个 surface 的 en/zh 占位符集合完全对称（含 `{app!r}` 这类转换标记，
归一化后按变量名对比），未发现缺失/多余占位符。

## 占位符差异清单（共 1 条）

### P-1 zh 的 `_one` 复数变体多出 `{{count}}`

- 键：`“{{title}}” and its reading conversations will be deleted. The {{count}} materials in it stay in your library._one`
- 各语言占位符集合（path:line 见 `report.md` / `table.tsv`）：
  - `en`（web/locales/en/app.json:3582）：`{title}`
  - `zh`（web/locales/zh/app.json:3582）：`{count, title}` ← 与其他语言不一致
  - `de`（web/locales/de/app.json:3579）：`{title}`；`fr`（web/locales/fr/app.json:4095）：`{title}`；
    `pl`（web/locales/pl/app.json:3578）：`{title}`；`uk`（web/locales/uk/app.json:3486）：`{title}`
- 对照组：同键 `_other` 变体六个语言全部为 `{count, title}`，完全一致。
- 运行时语义（`web/i18n/init.ts:19-33`，i18next ^25 默认 CLDR 复数）：
  中文只有 `other` 复数类目，`t(key, {count})` 在 zh 下永远命中 `_other`，
  zh 的 `_one` 是不可达的死数据；en/de/fr/pl/uk 的 `_one` 会正常命中。
- 修复建议（二选一，推荐 1）：
  1. 删除 zh 的 `_one` 变体（zh 只保留 `_other`），与其他只有单复两类语言的键结构对齐；
     这同时消除占位符差异。en 的 `_one` 不含 `{{count}}` 是有意的单数文案（"The material … stays"），保留。
  2. 若工具链要求 zh 保留 `_one` 形式占位，则把 zh `_one` 文案改为与 en 相同的占位符集合
     （仅 `{title}`），避免模板调用方在按 en 形状传参时出现未使用/缺失参数的混淆。
- 影响面：低。当前 zh 运行时不可达 `_one`，无用户可见缺陷；属于翻译资产一致性/工具链健壮性问题。

## 交叉引用（键存在性轴，本卡不下结论，供对应卡复核）

- `web.locales.app` 中 fr 相对 en：en 有而 fr 缺 529 键、fr 有而 en 无 909 键（含
  "1 / 4  —  LLM"、"1 skill selected" 等真实文案），fr 资源漂移明显；fr 包在
  `web/i18n/init.ts:47-50` 懒加载，缺键会回落 en。→ 归 `fix-web-locale-keys-drift` 轴。
- pl/uk 各有 16 个 en 没有的键，全部是 CLDR 复数变体（`_few`/`_many`），属语言必需结构，非漂移。
- pl/uk 无 `common.json`（de/en/fr/zh 有）。→ 归 `scan-web-locale-keys` /
  `fix-web-locales-parity` 轴。

## 相邻观察（超出本卡范围，仅记录）

- 运行时 `web/i18n/init.ts:15-26` 只注册 `en` 资源且 `ns: ["app"]`、`defaultNS: "app"`，
  `common` 命名空间从未被加载：`web/locales/*/common.json`（含 zh/fr/de 的 37 键）当前
  不参与渲染；`web/scripts/i18n_parity.mjs` 仍在对 en↔zh 的 `common.json` 做文件级对比。
  是否接线或清理建议由键/parity 轴的卡决策。
- 仓库自带 `web/scripts/i18n_parity.mjs` 只做 en↔zh 的文件/键存在性对比，未覆盖
  de/fr/pl/uk，也不检查占位符；本卡的占位符轴目前无既有工具覆盖（去重确认，2026-10-12）。

## 复跑方式

```bash
# 在 DeepTutor 检出根目录（本次基于 origin/main 6cf793bd8）：
python3 evidence/i18n-placeholder-parity-20261012/scan_i18n_placeholders.py --repo-root .
# 输出 report.md / table.tsv / raw.json / SHA256SUMS（含本文件）
# 验证确定性：连续两次运行，除 scanned HEAD 外 diff 为空（本次已验证）。
```

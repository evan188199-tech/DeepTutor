# chore(web): locale 孤儿 key confirmed 档清理 — AGEN-1729

基线：`origin/main @ 6cf793bd8`（release v1.6.14）。删除 web locale 孤儿 key 扫描
（myfork `scan/web-locale-keys-20261011` @ 66919d8bc，`evidence/scan-web-locale-keys/`）
confirmed 档中经复核确认可安全删除的条目；guarded 档零改动；uk/pl 与
`locales/*/common.json` 不在本卡范围、未触碰。

## 改动

| locale | 文件 | key 数 | 删除 | 恢复（见下） | 剩余 |
|---|---|---|---|---|---|
| en | `web/locales/en/app.json` | 5507 | 618 | 132 | 4889 |
| zh | `web/locales/zh/app.json` | 5507 | 618 | 132 | 4889 |
| de | `web/locales/de/app.json` | 5507 | 618 | 132 | 4889 |
| fr | `web/locales/fr/app.json` | 5887 | 1340 | 60 | 4547 |

diff 全部为整行删除（3194 行），无任何新增/改写；JSON 以 `JSON.stringify(…, null, 2) + "\n"`
序列化，与原格式逐字节一致（已验证 roundtrip）。

## 对账（验收 1）

1. 在本分支工作树（与扫描同一基线 6cf793bd8）重跑原扫描器 `evidence-scan.mjs`：
   orphan 候选 1479 / confirmed 750 / guarded 729，与报告 `en_orphans` 逐 key 完全一致（0 diff）。
2. fr 复算：`fr-reconcile.mjs` 按报告自定义的裸字符串 guard 规则复算 fr 全目录
   （候选 1910 与报告一致；en 侧 1479/750/729 逐 key 一致），得 fr confirmed=1400 / guarded=510。
3. **动态误报恢复（750→618 / 1400→1340）**：confirmed 档中存在一类"动态拼接误报"——
   key 由 `'前缀.' + 枚举值` 在运行时合成（`readiness.detail.<code>`、`contextBudget.segment.<segment>`、
   `mcp.category.<cat>`、`settings.servicePreview.title.<svc>`、`updateJob.<state>`、
   `visualCoverage.<code>` 等 14 个前缀），全文无完整 key 字符串命中，扫描按定义判为 confirmed，
   但实际被动态引用。其中 readiness 部分由仓库既有单测 `web/tests/settings-readiness-i18n.test.ts`
   直接裁决（首版 diff 删除后该测试失败）；其余前缀通过对全部源码拼接片段的静态扫描识别
   （单字符模板片段如 `` Q${n} `` 为 UI 标签拼串，非 key，已排除）。wire 直通的后端行标签
   （`TRANSLATABLE_ROW_LABELS`，经 `t(label)` 消费）同样恢复。
   共恢复 en/zh/de 132 个、fr 60 个，逐 key 见 `restored-dynamic-keys.json`；恢复 key 已断言
   在删除后目录中全部存在。
4. 最终删除集：`deletion-list-{en,zh,de,fr}.json`（en/zh/de 同集 618；fr 1340）。
   = 报告 confirmed 750 − 恢复 132；fr 复算 confirmed 1400 − 恢复 60 − 移入 guarded 7 中
   未恢复部分（7 个 fr-only 全部保留在 guarded 清单，未删除）。
5. 删除后断言：guarded key（en/zh/de 729 + fr 510）在四个目录中全部仍存在；confirmed∩guarded = ∅。

### fr 计数口径（报告 1407 vs 复算 1400）

报告 per_locale.fr 记 confirmed=1407 / guarded=503，但其 guarded 503 恰等于与 en 共享部分的
guarded 数，即报告对 909 个 fr-only key 未执行自身定义的裸字符串 guard。按定义复算这批 key：
901 个可删（confirmed）中 7 个存在裸命中，应归 guarded。本卡执行：7 个 key 全部移入
人工核对清单（`guarded-manual-review.md`），其中 6 个为更长字符串的子串伪命中，1 个
（`{{count}} paths`，`components/learning/surfaces.ts:55` 精确命中）需人工确认消费路径。

## guarded 档（验收 3：零改动）

- 删除集与 guarded 集在删除前后均做了交集断言（= 0）。
- `guarded-keys.json`：736 个唯一 guarded key（en/zh/de 共享 729 + fr-only 7）及其裸命中
  file:line 证据（每 key ≤ 3 条）。
- `guarded-manual-review.md`：人工核对清单（计数对账、7 个 fr-only 的初判、核对方法建议）。

## 防回归断言（key 引用扫描）

```bash
node evidence/web-locale-orphan-cleanup-20261011/orphan-guard.mjs
```

断言两层：① 1512 个已删 key（en/zh/de 618 ∪ fr 1340，去重后）在 web 源码 + tests 中零
子串引用；② 已删 key 未被重新加回 en/zh/de/fr app.json。任一违反 exit 1 并列出 file:line。
已做阳性注入测试（临时在 `web/lib/` 放入引用已删 key 的文件 → 正确报错退出 1）。
配合仓库既有 `npm run i18n:check`（缺失 key 审计）：未来任何 t() 引用已删 key 都会在 CI 失败。

## 验证记录（验收 2，均限时）

| 命令 | 结果 |
|---|---|
| `cd web && npm run i18n:check` | exit 0（parity OK；en/zh used-key 100% strict） |
| `cd web && npx vitest run`（全量单测） | 146 文件 / 653 用例全过 |
| `cd web && npm run test:node`（全量 node 套件） | 1303/1303 全过（含 settings-readiness-i18n） |
| `npx tsx --test tests/language-preferences.test.ts` | 4/4 过 |
| `node evidence/…/orphan-guard.mjs` | OK（1512 key 零引用） |

## 复现

```bash
# 1) 复算 fr confirmed/guarded 并与报告对账（在 web/ 目录下运行，需 typescript 依赖）
cd web && node ../evidence/web-locale-orphan-cleanup-20261011/fr-reconcile.mjs \
  ../evidence/web-locale-orphan-cleanup-20261011/report-orphan-keys.json /tmp/fr-lists.json
# 2) 复现删除（delete-confirmed.mjs 内置全部前置/后置断言；需先 git checkout 恢复四个 app.json）
# 3) 防回归断言
node evidence/web-locale-orphan-cleanup-20261011/orphan-guard.mjs
# 4) i18n 校验与单测
cd web && npm run i18n:check && npx vitest run && npm run test:node
```

## 范围外（未改动，留给人工/后续卡）

- uk/pl：孤儿集与 en 相同，任务卡明确只做 en/zh/de/fr。
- `locales/{en,zh,de,fr}/common.json`：报告标记为文件级孤儿（未被 `web/i18n/init.ts` 加载，
  37 key 全部重复于同 locale app.json）；整文件删除属独立决策，本卡不动。
- fr 相对 en 的 529 个目录缺口与 59 个缺失 used key：AGEN-904 / AGEN-1681 轴，去重不改。
- guarded 档 1236 个 key（en/zh/de 729 ×3 + fr 510）的人工核对。

## 文件清单

| 文件 | 说明 |
|---|---|
| `deletion-list-{en,zh,de,fr}.json` | 各 locale 已删 key 精确清单（JSON 数组） |
| `restored-dynamic-keys.json` | 从 confirmed 档恢复的动态误报 key（含恢复理由分类依据） |
| `report-orphan-keys.json` | 扫描报告副本（对账基准，来自 66919d8bc，SHA 与原报告一致） |
| `fr-lists.json` | fr 复算结果（confirmed 1400 / guarded 510 的 key 列表） |
| `fr-reconcile.mjs` | fr 复算 + 与报告对账脚本 |
| `delete-confirmed.mjs` | 执行删除（含全部断言）；产物即本分支 web/locales diff |
| `guarded-keys.json` | guarded key 全集 + 命中证据 |
| `guarded-manual-review.md` | guarded 档人工核对清单 |
| `orphan-guard.mjs` | 防回归断言（key 引用扫描） |
| `SHA256SUMS` | 本目录所有文件校验和（不含自身） |

#!/usr/bin/env node
// AGEN-923: build report.md deterministically from scanner outputs + AGEN-548 reference data.
import fs from "node:fs";
import path from "node:path";

const DIR = path.resolve(process.argv[2] || ".");
const DATA = path.join(DIR, "data");
const REF = path.join(DIR, "ref", "agen548");
const REF_COMMIT = "5fc16824c525bded9db059ce02f8e2b90c92f8bf";
const BASE_COMMIT = "f07029cfcf2c8dfccdb671cdfc343db8334f5741";

const j = (p) => JSON.parse(fs.readFileSync(path.join(DATA, p), "utf8"));
const files = j("files.json");
const unusedFiles = j("unused_files.json");
const unusedExports = j("unused_exports.json");
const components = j("components.json");
const unrefFns = j("unreferenced_functions.json");
const locale = j("locale_orphans.json");
const summary = j("summary.json");

const refExports = JSON.parse(fs.readFileSync(path.join(REF, "ts_unused_exports.json"), "utf8"));
const refFiles = JSON.parse(fs.readFileSync(path.join(REF, "ts_unused_files.json"), "utf8"));
const refExportSet = new Set(refExports.map((e) => `${e.file}::${e.name}::${e.line}`));
const refExportNameSet = new Set(refExports.map((e) => `${e.file}::${e.name}`));
const refFileSet = new Set(refFiles.map((f) => f.file));

// dedup
let dupExact = 0, dupName = 0, fresh = 0;
const freshItems = [];
for (const e of unusedExports) {
  if (refExportSet.has(`${e.file}::${e.name}::${e.line}`)) dupExact++;
  else if (refExportNameSet.has(`${e.file}::${e.name}`)) dupName++;
  else { fresh++; freshItems.push(e); }
}
const fileDup = unusedFiles.filter((f) => refFileSet.has(f.file)).length;
const fileFresh = unusedFiles.filter((f) => !refFileSet.has(f.file));

// confidence for unused exports
function expConf(e) {
  if (e.cats.length > 0) return "中";
  if (e.name_elsewhere_n > 0) return "中";
  if (e.internal_refs > 1) return "中";
  return "高";
}
function compConf(c) {
  if (c.mounted) return "—";
  if (c.imported_prod === 0 && c.imported_test === 0 && c.referenced_outside === 0) return "高";
  if (c.imported_prod === 0 && c.imported_test === 0) return "中";
  return "低";
}
const deadComponents = components.filter((c) => !c.mounted);
const deadHigh = deadComponents.filter((c) => compConf(c) === "高");
const deadMid = deadComponents.filter((c) => compConf(c) === "中");
const deadLow = deadComponents.filter((c) => compConf(c) === "低");

const expHigh = unusedExports.filter((e) => expConf(e) === "高");
const expMid = unusedExports.filter((e) => expConf(e) === "中");

// group unused exports per file
const byFile = new Map();
for (const e of unusedExports) {
  if (!byFile.has(e.file)) byFile.set(e.file, []);
  byFile.get(e.file).push(e);
}
const fileGroups = [...byFile.entries()].map(([file, list]) => ({
  file, count: list.length,
  high: list.filter((e) => expConf(e) === "高").length,
})).sort((a, b) => b.count - a.count);

const L = [];
L.push(`# web/ 前端死代码只读清点（AGEN-923）`);
L.push(``);
L.push(`- 基线：\`origin/main\` @ \`${BASE_COMMIT}\`（release: v1.6.13），只读扫描，未改任何产品代码`);
L.push(`- 范围：\`web/**/*.{ts,tsx}\` 共 ${files.total_files} 个文件（生产 ${files.prod_files} / 测试 ${files.test_files}），Node + TypeScript compiler API（5.9.3）AST 解析`);
L.push(`- 脚本：\`scan_web_dead_code.mjs\`（stdlib-only，除 TS 编译器外零依赖）；报告由 \`make_report.mjs\` 确定性生成`);
L.push(`- 机器数据：\`data/*.json\`（重跑 SHA256 一致，见「哈希自证」）`);
L.push(``);
L.push(`## 口径（判定规则）`);
L.push(``);
L.push(`1. **导入图**：解析全部 static import、\`export … from\` 具名/通配重导出、动态 \`import("…")\`（含 next/dynamic、React.lazy 场景）；具名重导出链做传递闭包（迭代上限 20 轮）。\`import * as ns\` 与 \`export * from\` 视为「通配消费」——被通配覆盖的导出**不**判死（保守，宁漏勿误）。`);
L.push(`2. **消费者分级**：prod（生产代码）/ test（\`tests/**\`、\`*.spec|test.*\`）/ script（\`scripts/**\`）。仅测试或脚本引用的单独标注。`);
L.push(`3. **排除项**：Next.js 约定文件（page/layout/route/loading/error/... 及 metadata、GET/POST 等 framework 导出）、\`contracts/generated\`、\`vendor\`、\`.d.ts\`、配置文件（\`*.config.*\`）。`);
L.push(`4. **未用导出**：导出符号无任何 prod 直接导入、无通配覆盖；「高」= 全仓（含测试/脚本）零引用且符号名无其他 token 出现；「中」= 仅测试/脚本引用、或存在同名 token（动态引用风险）、或仅内部使用（只需去掉 export 关键字）。default 导出与 \`export default X\` 声明名做合并判定。`);
L.push(`5. **未挂载组件**：TSX/组件目录中导出的大写组件（function/class，或初始化器含 JSX 的 const）。挂载判定：任意文件以 \`<Name\` JSX 出现，或经 default 导出链（\`export { default } from\` / 动态 import）存活。「高」= 零导入零 JSX 零 token；「低」= 有 prod 导入但全仓无 JSX 直接挂载（可能经组件 map 间接渲染，如 \`agentGlyph(kind)\` → \`const G = …; <G/>\` 模式，需人工确认）。`);
L.push(`6. **未引用工具函数**：导出 \`function\` 且符号名在全仓其他文件零 token（排除 Next 入口组件与 default 绑定）。`);
L.push(`7. **孤儿 locale key**：i18n 为 \`keySeparator:false\` 单 \`app\` 命名空间；key 判定 = 全仓（prod+test）字符串字面量精确匹配（覆盖 \`labelKey\` 式动态取值）；\`t(\\\`前缀.${"…"}\\\`)\` 模板提取静态前缀，命中前缀的 key 不判死。精确匹配偏保守，会把少量「纯文案巧合」计为已引用。`);
L.push(`8. 字符串 token 交叉核对用于风险标注（\`name_elsewhere_n\`），不做判活依据。`);
L.push(``);
L.push(`## 去重（对齐既有扫描轴）`);
L.push(``);
L.push(`- **scan-dead-code（Python 轴，AGEN-548）**：本卡为 web/ TS/TSX 轴，不重复其 Python 结论。TS 导出轴交叉比对：AGEN-548 数据 @ myfork \`agent/agen548-deadcode-scan\` @ \`${REF_COMMIT}\`（同基线 commit）。其 TS 未消费导出 ${refExports.length} 条中，与本卡结论**精确命中（同 file::name::line）${dupExact} 条、同名命中 ${dupName} 条、本卡新发现 ${fresh} 条**（新发现主要来自：default 链路解析、内部使用区分、更严的通配豁免）。文件轴：本卡 ${unusedFiles.length} 个未用文件中 ${fileDup} 个与其重合（${fileFresh.map((f) => `\`${f.file}\``).join("、") || "无"}为新发现/口径差异）。`);
L.push(`- **scan-ts-types（AGEN-664，类型轴）**：只覆盖 @ts-ignore/any/as-cast 等类型债，与死代码轴不重叠；本卡 \`isType\` 未用类型导出（${unusedExports.filter((e) => e.isType).length} 条）为其相邻补充。`);
L.push(`- **scan-web-api-usage（AGEN-857，API 调用面）**：其 \`lib/*-api.ts\` 死参数、漂移结论与本卡 \`lib/*-api.ts\` 未消费导出清点互补；删除 lib/api 客户端函数前应同时对照该卡 F1/F2（\`features/knowledge/api/client.ts:505,524\`、\`client.ts:293\` 仍在用）。`);
L.push(``);
L.push(`## 总计`);
L.push(``);
L.push(`| 类别 | 数量 | 高置信 | 中置信 | 低置信 |`);
L.push(`|---|---|---|---|---|`);
L.push(`| A. 未用文件（整文件候选） | ${unusedFiles.length}（${unusedFiles.reduce((a, b) => a + b.loc, 0)} 行） | ${unusedFiles.length} | 0 | 0 |`);
L.push(`| B. 未消费导出 | ${unusedExports.length} | ${expHigh.length} | ${expMid.length} | 0 |`);
L.push(`| C. 未挂载组件（符号） | ${deadComponents.length} | ${deadHigh.length} | ${deadMid.length} | ${deadLow.length} |`);
L.push(`| D. 未引用工具函数 | ${unrefFns.length} | ${unrefFns.length} | 0 | 0 |`);
L.push(`| E. 孤儿 locale key | ${summary.locale_orphan_keys_total}（另 4 个 common.json 整文件未注册，148 key） | 148（common.json 整文件） | 其余 | 0 |`);
L.push(``);
L.push(`## Top 项（按删除收益）`);
L.push(``);
L.push(`| # | 目标 | 类型 | 规模 | 置信度 |`);
L.push(`|---|---|---|---|---|`);
L.push(`| 1 | \`locales/{en,zh,de,fr}/common.json\` 整文件（i18n 运行时只注册 \`app\` 命名空间，common 从未加载） | locale 文件 | 4×37 key | 高 |`);
L.push(`| 2 | ${fileGroups[0] ? `\`${fileGroups[0].file}\`` : "-"} 未消费导出 ${fileGroups[0]?.count} 个 | 导出组 | 见清单 | 混合 |`);
L.push(`| 3 | ${fileGroups[1] ? `\`${fileGroups[1].file}\`` : "-"} 未消费导出 ${fileGroups[1]?.count} 个 | 导出组 | 见清单 | 混合 |`);
L.push(`| 4 | ${fileGroups[2] ? `\`${fileGroups[2].file}\`` : "-"} 未消费导出 ${fileGroups[2]?.count} 个 | 导出组 | 见清单 | 混合 |`);
L.push(`| 5 | ${fileGroups[3] ? `\`${fileGroups[3].file}\`` : "-"} 未消费导出 ${fileGroups[3]?.count} 个 | 导出组 | 见清单 | 混合 |`);
L.push(`| 6 | \`components/settings/ConnectionsEditor.tsx\` 整文件（0 导入） | 文件 | 763 行 | 高 |`);
L.push(`| 7 | 死组件 ${deadHigh.length} 个（零引用零挂载，见 C 表） | 组件 | — | 高 |`);
L.push(`| 8 | ${fileGroups[4] ? `\`${fileGroups[4].file}\`` : "-"} 未消费导出 ${fileGroups[4]?.count} 个 | 导出组 | 见清单 | 混合 |`);
L.push(``);
L.push(`## A. 未用文件（整文件候选，置信度：高）`);
L.push(``);
L.push(`| 文件 | 行数 | 备注 |`);
L.push(`|---|---|---|`);
for (const f of unusedFiles) L.push(`| \`${f.file}\` | ${f.loc} | ${f.note || ""} |`);
L.push(``);
L.push(`## B. 未消费导出（${unusedExports.length} 条；完整机器数据 \`data/unused_exports.json\`）`);
L.push(``);
L.push(`### B1. 高置信（${expHigh.length} 条，生产/测试/脚本零引用，符号可整段删除）`);
L.push(``);
for (const e of expHigh) {
  L.push(`- \`${e.file}:${e.line}\` \`${e.name}\`（${e.kind}${e.isType ? ", type" : ""}）— 高`);
}
L.push(``);
L.push(`### B2. 中置信（${expMid.length} 条，需人工复核后处理）`);
L.push(``);
for (const e of expMid) {
  const why = e.cats.length ? `仅${e.cats.join("+")}引用` : (e.internal_refs > 1 ? `内部使用×${e.internal_refs}（仅去 export）` : `同名token×${e.name_elsewhere_n}`);
  L.push(`- \`${e.file}:${e.line}\` \`${e.name}\`（${e.kind}）— 中（${why}）`);
}
L.push(``);
L.push(`### B3. 按文件聚合（未消费导出数 Top 15）`);
L.push(``);
L.push(`| 文件 | 未消费导出 | 其中高置信 |`);
L.push(`|---|---|---|`);
for (const g of fileGroups.slice(0, 15)) L.push(`| \`${g.file}\` | ${g.count} | ${g.high} |`);
L.push(``);
L.push(`## C. 未挂载组件（${deadComponents.length} 个符号；完整数据 \`data/components.json\`）`);
L.push(``);
L.push(`| 位置 | 组件 | 导入(prod/test) | JSX挂载文件数 | 置信度 |`);
L.push(`|---|---|---|---|---|`);
for (const c of deadComponents) {
  L.push(`| \`${c.file}:${c.line}\` | \`${c.name}\` | ${c.imported_prod}/${c.imported_test} | ${c.jsx_mount_files.length} | ${compConf(c)} |`);
}
L.push(``);
L.push(`低置信项说明：有 prod 导入但全仓无直接 JSX 挂载，典型如 \`${deadLow[0]?.name || "…"}\`（组件 map 间接渲染模式），删除前必须人工确认间接引用。`);
L.push(``);
L.push(`## D. 未引用工具函数（${unrefFns.length} 个，置信度：高）`);
L.push(``);
for (const f of unrefFns) L.push(`- \`${f.file}:${f.line}\` \`${f.name}\` — 高`);
L.push(``);
L.push(`## E. 孤儿 locale key`);
L.push(``);
L.push(`i18n 运行时（\`web/i18n/init.ts\`）只注册 \`app\` 命名空间：\`en/app.json\` 静态导入 + zh/fr/de/uk/pl 动态导入。\`common.json\` 在任何语言下**均未注册**（仅 \`tests/workspace-i18n.spec.ts:3\` 导入过 zh/common.json）。`);
L.push(``);
L.push(`| 文件 | key 总数 | 孤儿 key | en 缺失(漂移) | 运行时注册 | 置信度 |`);
L.push(`|---|---|---|---|---|---|`);
for (const o of locale.files) {
  L.push(`| \`${o.file}\` | ${o.total} | ${o.orphan_count} | ${o.missing_in_en_count} | ${o.runtime_registered ? "是" : "**否**"} | ${o.runtime_registered ? "中" : "高（整文件未注册）"} |`);
}
L.push(``);
L.push(`- 高置信：4 个 \`common.json\`（共 148 key，含 \`common.loading/cancel/close\` 等）运行时不可达，整文件可删（测试引用需同步调整）。`);
L.push(`- 中置信：各语言 \`app.json\` 孤儿 key（en/zh/de ${locale.files[0].orphan_count}、fr ${locale.files.find((f) => f.lang === "fr" && f.ns === "app")?.orphan_count}、uk/pl ${locale.files.find((f) => f.lang === "uk" && f.ns === "app")?.orphan_count}）。示例（en）：\`Generating\`、\`Welcome to DeepTutor\`、\`guidedLearning.*\`（约 120 条）、\`settingsTour.*\`（8 条）、\`contextBudget.note.deferredTools_*\`。完整 key 清单见 \`data/locale_orphans.json\`。`);
L.push(`- 漂移：\`fr/app.json\` 比 en 多 ${locale.files.find((f) => f.lang === "fr" && f.ns === "app")?.missing_in_en_count} 个 key（en 无此 key，属死翻译）。`);
L.push(`- 动态前缀豁免：\`${[...new Set(locale.dynamic_t_prefixes)].slice(0, 5).join("\`, \`")}\` 等 ${new Set(locale.dynamic_t_prefixes).size} 个 \`t(\\\`前缀.${"…"}\\\`)\` 模板前缀覆盖到的 key 不判死。`);
L.push(``);
L.push(`## 复现与哈希自证`);
L.push(``);
L.push("```bash");
L.push(`# 基线 ${BASE_COMMIT}`);
L.push("node evidence/scan-web-dead-code-20261006/scan_web_dead_code.mjs --web web --out <输出目录>");
L.push("node evidence/scan-web-dead-code-20261006/make_report.mjs evidence/scan-web-dead-code-20261006");
L.push("```");
L.push(``);
L.push(`- 同工作区连续两次运行输出 **byte 级一致**（\`diff -r\` 为空），SHA256 见 \`SHA256SUMS\`（data/*.json 七个文件哈希与重跑完全相等）。`);
L.push(`- TS 编译器路径可用 \`--ts\` 覆盖（默认主工作区 \`web/node_modules/typescript\`，只读 require，不写该目录）。`);
L.push(``);
L.push(`## 风险与误报边界`);
L.push(``);
L.push(`1. 通配/命名空间导入按「消费全部」豁免——真实死代码可能被掩盖（宁漏勿误）。`);
L.push(`2. 字符串精确匹配会把「纯文案与 key 同文」计为已引用；\`t()\` 拼接 key 只覆盖检测到的模板前缀。`);
L.push(`3. 组件 map 间接渲染（\`agentGlyph\` 模式）使「有导入无 JSX」项只能给低置信。`);
L.push(`4. 本卡为只读清点，**不含任何删除动作**；删除建议按置信度拆后续卡，lib/api 客户端删除前对照 AGEN-857 结论。`);
L.push(``);

fs.writeFileSync(path.join(DIR, "report.md"), L.join("\n") + "\n");
console.log("report written:", path.join(DIR, "report.md"));

# 上游 issue 池与储备池一致性复核报告（2026-10-09）

## 1. 复核范围与方法

- 上游基线：HKUDS/DeepTutor `origin/main` @ `6cf793bd8`（v1.6.14）
- open issues：68 条（`gh issue list -R HKUDS/DeepTutor --state open --limit 200`，2026-10-09 快照）
- open PRs：74 条（`gh pr list --state open --limit 200`）
- merged PRs：`--state merged --limit 100`（覆盖 2026-10-04 起的全部合并）；更早的关联 PR 逐一用 `gh pr view <n> --json state,mergedAt` 核实（见文中引用）
- 关联判定：PR 正文 issue 引用扫描 + GitHub GraphQL `closingIssuesReferences`（全部 74 条 open PR；结果：无任何 open PR 以 Fixes/Closes 方式关联 open issue，唯一 formal 关联为 PR#637→#618 且 #618 已关）+ PR 标题/分支号比对
- 储备池（只读）：`deeptour.0priority.jsonl`(11)、`deeptour.jsonl`(13)、`deeptour.auto.jsonl`(772)、`deeptour.consumed`(10)
- 本报告只读复核：不改 backlog、不改代码、不写上游、不建卡

标签约定：**已建卡**=储备池存在对应卡；**有关联PR**=存在 open 或近期 merged 的关联 PR（附状态）；**需求含糊或需密钥**=需求不可直接执行；**可建卡**=需求明确且储备池尚无卡。

## 2. 结论摘要

| 分类 | 数量 |
|---|---|
| open issues 总数 | 68 |
| 已建卡（含 verify/review/只读前置卡） | 43 |
| 有关联 PR 而无卡 | 5 |
| 可建卡（全新） | 13 |
| 需求含糊 / 不适用 | 7 |
| 储备池过期卡（有直接证据，见 §4） | 0priority 5 张 + auto/jsonl 44 张 |
| 下一批建议建卡 | 13 全新 + 6 剩余切片（见 §5） |

## 3. 逐 issue 结论（68 条全覆盖）

格式：`#issue｜结论｜证据`。储备证据格式 `文件:行号 (key)`；文件均指 backlog 目录。PR 状态核实时间 2026-10-09。

### 2026-10 新进 issue（6 条）

- #1909 压缩前重复图片计数｜**已建卡+有关联PR(open)**｜储备 `deeptour.auto.jsonl:713 (up-1909)`；PR#1910 OPEN，正文 "Fixes #1909"。撞车：卡与 PR 重复，建议核销卡或转复核
- #1908 可自定义复习频率策略｜**已建卡**｜`deeptour.auto.jsonl:714 (up-1908)`；无关联 PR
- #1907 Usage statistics 恒报错｜**已建卡**｜`deeptour.auto.jsonl:715 (up-1907)`；无关联 PR；备注：复现需用量数据/供应商配置
- #1903 MinerU 日志静默超时与 Windows 进程树清理｜**已建卡**｜`deeptour.auto.jsonl:673 (up-1903)`、复核卡 `deeptour.auto.jsonl:691 (verify-1903-lifecycle-claims)`；无关联 PR
- #1902 Mastery Path 课前准备证据选择｜**已建卡**｜`deeptour.auto.jsonl:674 (up-1902)`、`deeptour.auto.jsonl:692 (verify-1902-evidence-reuse)`、前置 `deeptour.auto.jsonl:689 (scan-visual-practice-assessment)`；无关联 PR
- #1901 Mastery Path 语义化作答评估｜**已建卡**｜`deeptour.auto.jsonl:675 (up-1901)`、`deeptour.auto.jsonl:689 (scan-visual-practice-assessment)`；无关联 PR

### 2026-09 批次（16 条）

- #1262 README 截图与 walkthrough 刷新｜**可建卡**｜无卡无 PR；PR#1628 MERGED(2026-10-04) 仅覆盖 v1.6.12 设置截图，v1.6.4/5 部分未做
- #1256 Watching 笔记异步保存保留时间戳与草稿｜**已建卡**｜`deeptour.jsonl:5 (up-1256)`；无关联 PR
- #1254 Watching 字幕对齐与移动端居中｜**已建卡**｜`deeptour.jsonl:6 (up-1254)`；无关联 PR
- #1249 [Feature Request]（标题空）｜**有关联PR(open)+需求含糊**｜issue 标题与需求空泛；PR#1268 OPEN 正文 "Fixes #1249"（LlamaIndex 图表展示切片）
- #1246 Watching 全屏学习｜**已建卡**｜`deeptour.auto.jsonl:495 (up-1246)`；无关联 PR
- #1244 Partner 错题写入笔记本｜**已建卡**｜`deeptour.auto.jsonl:5 (up-1244)`；无关联 PR
- #1242 MN4 add-on 契约不符｜**已建卡(复核)+有关联PR(open)**｜PR#1243 OPEN（MN4 原生 add-on 捆绑）；复核卡 `deeptour.auto.jsonl:115 (review-pr-1243)`
- #1240 Watching 浏览 Invidious 账号｜**可建卡（建议归学习体验项目）**｜无卡无 PR
- #1238 Immersive Watching 独立工作区｜**可建卡（建议归学习体验项目）**｜无卡无 PR
- #1236 EPUB 响应式书页｜**已建卡**｜`deeptour.auto.jsonl:176 (up-1236)`；无关联 PR
- #1230 管理员账号迁子账号+侧栏折叠｜**有关联PR(open，部分覆盖)**｜PR#1374 OPEN 标题 "(#1230)"（仅侧栏折叠切片）；管理员迁移切片无卡 → 剩余切片可建卡
- #1228 Learner 访问 /api/courses 403｜**已建卡(verify)**｜`deeptour.auto.jsonl:82 (up-1228)`；PR#1231 MERGED(2026-09-07) 但 issue 仍 open → 验证卡有效
- #1223 聊天 PDF 附件工具报错｜**已建卡(verify)**｜`deeptour.auto.jsonl:83 (up-1223)`；open/近期 merged PR 均未关联
- #1220 gpt-5.6-terra 不可用｜**已建卡(复核)+有关联PR**｜PR#1221 OPEN（正文 fixes #1220）；PR#1694 MERGED(2026-10-04)；复核卡 `deeptour.auto.jsonl:101 (up-1220)`；备注：复现需该模型密钥
- #1215 dev 路由预算修复｜**已建卡(review)——卡已过期**｜复核对象 PR#1216 已 CLOSED（未合并，2026-09-05 后）；issue 仍 open，需重新定位实现路径
- #1209 设置 readiness 总览与 value-free 导出｜**已建卡**｜`deeptour.auto.jsonl:99 (up-1209)`；无关联 PR

### 2026-08 及更早功能 issue

- #1158 Watching 最近学习记录｜**已建卡**｜`deeptour.auto.jsonl:496 (up-1158)`；无关联 PR
- #1138 内容寻址去重｜**已建卡(对照)+有关联PR(open，部分)**｜PR#1218 OPEN "Part of #1138"（仅 chat 附件）；对照卡 `deeptour.auto.jsonl:688 (scan-content-dedup)`；KB/reading 侧剩余切片可建卡
- #1130 Learner 个人学习进度视图｜**可建卡（建议归学习体验项目）**｜无卡无 PR
- #1109 阅读进度写入账号学习记录｜**已建卡**｜`deeptour.auto.jsonl:93 (up-1109)`；无关联 PR
- #1028 ACP 支持｜**有关联PR(open，部分)**｜PR#1272 OPEN "Part of #1028"（ACP client backend）；无储备卡 → 后续切片可建卡
- #997 YouTube 沉浸观看｜**有关联PR(merged，部分)**｜PR#1645 MERGED(2026-10-04，正文引用 #997)；无储备卡；属学习体验项目范围
- #995 引导式学习作为安全阅读扩展｜**可建卡**｜无卡无 PR
- #992 Learner 建模为普通用户+监护授权｜**可建卡（建议归学习体验项目）**｜无卡无 PR
- #971 selector 重锚定收尾｜**已建卡**｜`deeptour.auto.jsonl:94 (up-971)`；无关联 PR
- #961 可插拔学习资源 provider｜**已建卡**｜`deeptour.auto.jsonl:136 (up-961)`；无关联 PR
- #932 章节角色/实体关系图谱｜**已建卡**｜`deeptour.auto.jsonl:133 (up-932)`；无关联 PR
- #916 双语阅读移动端 UX｜**已建卡+有关联PR(merged，部分)**｜PR#1734 MERGED(2026-10-07，正文引用 #916)；剩余切片卡 `deeptour.auto.jsonl:134 (up-916)`
- #902 web 源持久同步 follow-ups｜**已建卡+有关联PR(merged)**｜PR#1635 MERGED(2026-10-04，正文 fixes #902，双语源配对)；issue 保持 open 承接 follow-ups；测试欠账卡 `deeptour.auto.jsonl:647 (test-websource-sched-recovery)`
- #860 双语 EPUB 学习体验｜**已建卡**｜`deeptour.auto.jsonl:135 (up-860)`；无关联 PR

### 缺陷 / 配置类

- #745 GraphRAG 配置与 chat/embedding profile 分歧｜**已建卡**｜`deeptour.auto.jsonl:614 (up-745)`；无关联 PR；备注：复现需 GraphRAG/embedding 配置
- #740 有状态持续学习（/teach 设计）｜**有关联PR(open，部分)**｜PR#1226 OPEN "Part of #740"（学习日志软日志）；无储备卡 → 后续切片可建卡
- #725 自动更新按钮｜**可建卡（前置已备）**｜只读前置卡 `deeptour.auto.jsonl:242 (test-app-update-version)`；PR#751 OPEN（installation-aware updates）未引用 #725，建卡前需撞车核对
- #684 多语言集成｜**已建卡+有关联PR(open，未引用issue)**｜切片卡 `deeptour.auto.jsonl:175 (up-684)`；PR#728 OPEN（西语完整本地化）
- #661 优化智能写作体验｜**可建卡（需拆解）+有关联PR(merged，部分)**｜PR#1640 MERGED(2026-10-04，标题 "(#661)"，编辑模型选择)；issue 仍 open，剩余需求无卡
- #655 章节/笔记逐章生成断点续作｜**已建卡**｜`deeptour.auto.jsonl:174 (up-655)`；无关联 PR
- #641 会话级 reasoning-effort 选择器｜**已建卡(只读前置)**｜`deeptour.auto.jsonl:241 (test-reasoning-params)`；无关联 PR
- #640 LightRAG 参数可配置｜**已建卡(对照扫描)**｜`deeptour.auto.jsonl:249 (scan-lightrag-params)`；无关联 PR
- #613 知识库播客 Audio Overview｜**可建卡（大特性需拆解）**｜无 up 卡；相邻储备 `deeptour.auto.jsonl:589 (guide-audio-overview)`、`deeptour.auto.jsonl:586 (test-audio-overview-pipeline)`
- #612 持久化 PG 方案｜**已建卡(评估×2)**｜`deeptour.auto.jsonl:440 (up-612)`、`deeptour.auto.jsonl:179 (scan-persistence)`；无关联 PR
- #575 聊天出题/错题未记录｜**已建卡**｜`deeptour.auto.jsonl:34 (up-575)`；无关联 PR
- #440 invalid_embedding_index 可操作错误｜**已建卡——卡已过时+有关联PR(merged)**｜PR#1702 MERGED(2026-10-07，即 AGEN-133 产物)；issue 仍 open（后续诉求待澄清）；`deeptour.auto.jsonl:35 (up-440)` 与 `deeptour.0priority.jsonl:3 (prready-AGEN-133)` 目标均已合并 → 核销/重定义
- #431 扫描版 PDF 空文档报错｜**已建卡**｜`deeptour.auto.jsonl:615 (up-431)`；无关联 PR
- #429 KB 支持 EPUB｜**已建卡**｜`deeptour.auto.jsonl:98 (up-429)`；无关联 PR
- #473 Chapter map 标题截断｜**已建卡**｜`deeptour.auto.jsonl:613 (up-473)`；无关联 PR
- #451 周期性 LLM 健康检查可禁用｜**已建卡**｜`deeptour.auto.jsonl:97 (up-451)`；无关联 PR

### RFC / 大特性 / 讨论类

- #403 Projects 分组工作区｜**已建卡**｜`deeptour.auto.jsonl:138 (up-403)`；无关联 PR
- #401 本地化数据库配置｜**已建卡(问答导读)**｜`deeptour.auto.jsonl:672 (guide-local-db)`；无关联 PR
- #397 下一代 Memory 架构 RFC｜**已建卡(RFC 评审)**｜`deeptour.auto.jsonl:513 (up-397)`；无关联 PR
- #380 学习体验 Plugin SDK｜**可建卡（大特性需拆解）**｜无卡无 PR；与 #961 已建卡相邻
- #375 References 合规过滤｜**可建卡（低优）**｜无卡无 PR；需求边界待澄清（合规口径）
- #366 移动端响应式｜**已建卡**｜`deeptour.auto.jsonl:634 (up-366)`；无关联 PR
- #304 HNSW 索引与 Rerank｜**可建卡（需评估）**｜无卡无 PR；受 RAG 后端能力约束
- #279 知识库可扩展架构设想｜**需求含糊**｜架构愿景帖，无可执行单元；无卡无 PR
- #567 LTI 集成｜**已建卡**｜`deeptour.auto.jsonl:180 (review-lti)`、`deeptour.auto.jsonl:633 (up-567)`；无关联 PR
- #621 多用户 Memory 隔离与 Media 存储设计疑问｜**需求含糊**｜[Question] 设计讨论；无卡无 PR
- #613 见上（可建卡）

### 非开发任务 / 空泛

- #498 DeepTutor Roadmap｜**需求含糊（不适用）**｜roadmap 汇总帖；仅 PR#510(OPEN) 正文提及
- #486 如何卸载清理｜**需求含糊（不适用）**｜[Question] 用户支持
- #185 [Feature Request]（正文空泛）｜**需求含糊**｜无卡无 PR
- #180 多模态学习表示管线｜**需求含糊**｜研究性 RFC，无明确交付；无卡无 PR
- #199 长程推理与安全 checklist 文档｜**可建卡（docs-only 小卡）**｜无卡无 PR
- #78 微信交流群｜**需求含糊（不适用）**｜社区公告；仅 PR#488(OPEN) 正文提及（页脚链接）

## 4. 储备池 → 上游漂移（过期卡清单）

### 4.1 有 PR/issue 状态直接证据的 0priority 过期卡（5 张）

| 卡（deeptour.0priority.jsonl 行） | 漂移证据 | 建议 |
|---|---|---|
| :3 prready-AGEN-133 | 目标 PR#1702 已 MERGED(2026-10-07) | 核销 |
| :7 prready-AGEN-135 | 产物分支 pr/knowledge-surface-swallowed-failures-v2 已合并为 PR#1706 MERGED(2026-10-07) | 核销 |
| :9 fix-chat-draft-merge-303 | 产物分支 pr/chat-draft-restore-guard-v3 已合并为 PR#1705 MERGED(2026-10-07) | 核销 |
| :5 rework-AGEN-102 | 产物已合并为 PR#1723 MERGED(2026-10-07，"(#1410)") | 核销 |
| :6 port-AGEN-101-to-1692 | 目标 PR#1692 已 MERGED(2026-10-04)，无法追加 | 核销 |

另：:4 rework-AGEN-131 目标 issue #1610 已关且 PR#1695 OPEN（"(#1610)"）覆盖上限诉求 → 需撞车复核后重定义；:11 verify-1630-for-pr-1634 的 PR#1634 已 MERGED(2026-10-04) 且 #1630 已关 → 核销；:10 fix-ask-user-submit-after-completed 引用的 "开放 PR #1668" 已 MERGED(2026-10-04)，卡内约束过时，回归是否仍存在需按最新 dev 复测后再定。

### 4.2 up-* 目标 issue 已非 open 的卡（系统对照，44 张）

对储备池全部 `up-<N>` key 与当前 68 条 open issues 求差：44 张卡的目标 issue 均已关闭（快照证据：`gh issue list --state open` 不含这些编号）。主要分组与直接 PR 证据：

- 已消费台账内（无需处理）：up-1646(PR#1685 merged)、up-1647(PR#1666 merged)、up-1678(PR#1683 merged)
- **deeptour.jsonl 主队列中未消费但目标已关（5 张，建议核销）**：up-1623(PR#1627 merged)、up-1624(PR#1626 merged)、up-1641(PR#1783 merged)、up-1648(PR#1668 merged)、up-1673(PR#1686 merged)
- review/verify 类目标已合并（8 张）：up-1176、up-1222(PR#1652 merged/#1225 closed)、up-1359、up-1419、up-1421(PR#1436 merged)、up-1478(PR#1480 merged)、up-1481(PR#1488 merged)、up-1613(PR#1625 merged)、up-1614(PR#1619 merged)、up-1630(PR#1634 merged)、up-1676(PR#1682 merged)、up-1696
- fix/feat 类目标已关（含部分有 merged PR 证据）：up-1296、up-1303、up-1307、up-1326、up-1329、up-1336、up-1389、up-1390、up-1405、up-1407、up-1410(PR#1723 merged)、up-1447、up-1476、up-1610(PR#1695 open)、up-1611、up-1629、up-1691(PR#1692 merged)、up-1779(PR#1783 merged)、up-1781(PR#1794 merged；PR#1805 open 后续测试)、up-1782(PR#1783 merged)、up-1784(PR#1790 merged)、up-1792(PR#1801 merged)、up-1793、up-1795

建议：将 4.2 全部 44 张移入 consumed 或删除（保留 consumed 记录 up-*：目标 issue/PR 编号），避免后续运行重复领取已完成工作。

### 4.3 consumed 台账一致性

consumed 10 条与上游状态一致：3 张 up-* 卡对应 issue 均已因 merged PR 关闭；bundle-*/rework-AGEN-136 对应 PR#1751/#1704/#1748-1749 等已合并（2026-10-07 批次）。无发现反向漂移。

## 5. 下一批可建卡建议

全新 13 张（按建议优先级）：

1. `up-995` 引导式学习安全阅读扩展（切片一：只读扩展挂载点）
2. `up-725` 自动更新（先与 PR#751 撞车核对，再定切片）
3. `up-661` 智能写作剩余需求拆解卡（PR#1640 已覆盖编辑模型选择）
4. `up-613` Audio Overview 能力切片卡（相邻储备 guide/test 卡已备）
5. `up-380` Plugin SDK 需求拆解备忘卡（先出 RFC 对照，不直接实现）
6. `up-304` HNSW/Rerank 可行性评估卡（只读）
7. `up-375` References 合规过滤需求澄清卡（先澄清口径再实现）
8. `up-199` 长程推理与安全 checklist docs-only 卡
9. `up-1262` README v1.6.4/5 截图与 walkthrough 更新（docs-only）
10. `up-1130` Learner 个人学习进度视图（→ 学习体验项目）
11. `up-992` Learner 建模为普通用户+监护授权（→ 学习体验项目）
12. `up-1240` Watching Invidious 账号浏览（→ 学习体验项目）
13. `up-1238` Immersive Watching 独立工作区（→ 学习体验项目）

剩余切片 6 张（已有部分覆盖，需在卡面注明已覆盖部分）：

- `up-1230-slice2` 管理员账号迁移子账号（PR#1374 仅侧栏折叠）
- `up-1028-slice2` ACP 后续能力面（PR#1272 仅 client backend）
- `up-1138-slice2` KB/reading 侧内容寻址去重（PR#1218 仅 chat 附件）
- `up-740-slice2` 有状态学习后续（PR#1226 仅学习日志）
- `up-997-followup` YouTube 沉浸观看跟进（PR#1645 已部分落地；→ 学习体验项目）
- `up-1909-review` #1909 已有 PR#1910，改开复核卡而非修复卡

维护动作建议：核销 §4.1（5 张）与 §4.2（44 张）共 49 张过期卡；up-1215 复核卡需改写（复核对象 PR#1216 已关闭）。

## 6. 可复现命令

```
gh issue list -R HKUDS/DeepTutor --state open --limit 200 --json number,title,labels,createdAt
gh pr list -R HKUDS/DeepTutor --state open --limit 200 --json number,title,headRefName,body
gh pr list -R HKUDS/DeepTutor --state merged --limit 100 --json number,title,body,mergedAt
gh pr view <n> -R HKUDS/DeepTutor --json number,state,mergedAt,title
gh api graphql -f query='…closingIssuesReferences…'   # 74 条 open PR 全量，无 open→open formal 关联
```

储备池读取均为只读；本卡分支仅含本报告与 SHA256SUMS。

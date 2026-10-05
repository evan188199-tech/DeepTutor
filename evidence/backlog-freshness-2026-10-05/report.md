# 储备池 up-* 卡上游新鲜度复核报告（2026-10-05）

## 汇总

- 核对范围：backlog 三份 jsonl（`deeptour.0priority.jsonl` / `deeptour.auto.jsonl` / `deeptour.jsonl`）中全部 up-* 卡，共 **59 张**，100% 逐张核对。
- 数据源：api.github.com `repos/HKUDS/DeepTutor`（issues、pulls、issues/timeline），只读查询，缓存快照见 `analysis-snapshot.json`。
- 判定结果：**可用 30 张 / 需改派 3 张 / 已过时 26 张**。

| 文件 | up-* 卡数 | 可用 | 需改派 | 已过时 |
|---|---|---|---|---|
| `deeptour.0priority.jsonl` | 0（无 up-* 卡） | - | - | - |
| `deeptour.auto.jsonl` | 51 | 29 | 3 | 19 |
| `deeptour.jsonl` | 8 | 1 | 0 | 7 |

下一轮 harvest 建议剔除 **26 张已过时卡**；**3 张需改派**（改写卡面后保留）；**30 张可用**原样保留。

## 方法说明

- 每张卡解析标题/描述中的上游编号（含全角括号 `（#N）` 形式），主编号取标题尾部 `#N`。
- 对每个主编号拉取 issue 状态、timeline 交叉引用 PR；对每张关联/引用 PR 拉取合并状态与正文。
- 关键发现：DeepTutor 上游 PR 一律合入 `dev`，而仓库默认分支是 `main`，GitHub 不会自动关闭关联 issue —— 因此 **「issue 仍开放」不等于「未被修复」**。凡 PR 已合并且正文含 `Closes/Fixes #N`（或 PR 标题与卡面意图一致）即判「已过时」；仅在 issue 被显式关闭/重开等场景另行标注。
- 与 verify-reserve-rebase（分支可合入性）为两个正交维度，本报告不涉及分支合入性判定。
- 全程未修改 backlog 文件、未在上游发表任何评论。

## 已过时（26 张）

| 卡 | 位置 | 类型 | 上游 issue 状态 | 关联 PR（引用号·状态） | 原因 |
|---|---|---|---|---|---|
| `up-1691` | `deeptour.auto.jsonl:1` | fix | #1691 closed(completed) | #1692 merged | issue #1691 已关闭(completed)；修复 PR #1692 已合并(dev, 2026-10-04) |
| `up-1390` | `deeptour.auto.jsonl:3` | feat | #1390 open | #1394 merged | issue #1390 仍开放但 PR #1394 已合并(dev, 2026-09-23)，正文含 Closes #1390（PR 合入 dev≠默认分支，issue 未自动关闭） |
| `up-1336` | `deeptour.auto.jsonl:4` | feat | #1336 open | #1339 merged | issue #1336 仍开放但 PR #1339 已合并(dev, 2026-09-23)，正文含 Closes #1336 |
| `up-1244` | `deeptour.auto.jsonl:5` | feat | #1244 open | #1341 merged | issue #1244 仍开放但 PR #1341 已合并(dev, 2026-09-19)，标题即「record wrong questions (#1244)」，与卡面意图一致（正文无 closing 关键字，建议人工抽查覆盖度） |
| `up-1256` | `deeptour.auto.jsonl:6` | fix | #1256 open | #1257 closed、#1350 merged | issue #1256 仍开放但 PR #1350 已合并(dev, 2026-09-10)，正文含 Closes #1256 |
| `up-1254` | `deeptour.auto.jsonl:7` | fix | #1254 open | #1255 closed、#1351 merged | issue #1254 仍开放但 PR #1351 已合并(dev, 2026-09-10)，正文含 Closes #1254 |
| `up-1476` | `deeptour.auto.jsonl:8` | feat | #1476 open | #1477 merged | issue #1476 仍开放但首切片 PR #1477 已合并(dev, 2026-09-23)，正文含 Closes #1476；后续切片需基于新基线重立卡 |
| `up-1296` | `deeptour.auto.jsonl:9` | feat | #1296 open | #1302 closed、#1311 closed、#1317 merged | issue #1296 仍开放但 PR #1317 已合并(dev, 2026-09-23)，正文含 Closes #1296 |
| `up-1329` | `deeptour.auto.jsonl:10` | feat | #1329 open | #1330 merged | issue #1329 仍开放但 PR #1330 已合并(dev, 2026-09-23)，正文含 Closes #1329 |
| `up-1326` | `deeptour.auto.jsonl:11` | feat | #1326 open | #1372 merged | issue #1326 仍开放但 PR #1372 已合并(dev, 2026-09-23)，正文含 Closes #1326 |
| `up-1405` | `deeptour.auto.jsonl:12` | feat | #1405 open | #1408 merged | issue #1405 仍开放但 PR #1408 已合并(dev, 2026-09-23)，正文含 Closes #1405 |
| `up-1676` | `deeptour.auto.jsonl:73` | review | #1676 closed(completed) | #1682 merged | 复核对象 PR #1682 已合并(dev, 2026-10-04)，跟踪 issue #1676 已关闭(completed) |
| `up-1630` | `deeptour.auto.jsonl:74` | review | #1630 open | #1634 merged、#1745 open | 复核对象 PR #1634 已合并(dev, 2026-10-04)；如有后续可关注后继 PR #1745（开放，base=main） |
| `up-1614` | `deeptour.auto.jsonl:75` | review | #1614 closed(completed) | #1619 merged | 复核对象 PR #1619 已合并(dev, 2026-10-04)，跟踪 issue #1614 已关闭(completed) |
| `up-1613` | `deeptour.auto.jsonl:76` | review | #1613 closed(completed) | #1625 merged | 复核对象 PR #1625 已合并(dev, 2026-10-04)，跟踪 issue #1613 已关闭(completed) |
| `up-1222` | `deeptour.auto.jsonl:77` | review | #1222 open | #1225 closed、#1323 merged、#1239 closed、#19 closed、#1375 merged、#1652 merged | 比较复核前提已消失：#1652 已合并(dev, 2026-10-04)，#1225 已关闭未合并(2026-10-04)；跟踪 issue #1222 为长期跟踪、有意保持开放 |
| `up-1109` | `deeptour.auto.jsonl:93` | fix | #1109 open | #1110 closed、#1368 merged | issue #1109(提案) 仍开放但 PR #1368 已合并(dev, 2026-09-23)，正文含 Closes #1109 |
| `up-971` | `deeptour.auto.jsonl:94` | fix | #971 open | #972 merged、#974 merged、#1376 merged | issue #971(提案) 仍开放但收尾 PR #1376 已合并(dev, 2026-09-23)，正文含 Closes #971（另有 #972/#974 早前合并）；残余边界需重立卡 |
| `up-429` | `deeptour.auto.jsonl:98` | fix | #429 open | #842 closed、#843 merged | issue #429 仍开放但 PR #843 已合并(dev, 2026-08-16)，正文含 Closes #429 |
| `up-1678` | `deeptour.jsonl:1` | fix | #1678 closed(completed) | #1683 merged | issue #1678 已关闭(completed)；修复 PR #1683 已合并(dev, 2026-10-04)；consumed |
| `up-1647` | `deeptour.jsonl:2` | fix | #1647 closed(completed) | #1666 merged | issue #1647 已关闭(completed)；修复 PR #1666 已合并(dev, 2026-10-04)；consumed |
| `up-1646` | `deeptour.jsonl:3` | fix | #1646 closed(completed) | #1685 merged | issue #1646 已关闭(completed)；修复 PR #1685 已合并(dev, 2026-10-04)；consumed |
| `up-1624` | `deeptour.jsonl:4` | fix | #1624 closed(completed) | #1626 merged、#1642 closed | issue #1624 已关闭(completed)；修复 PR #1626 已合并(dev, 2026-10-04)（另一相关 PR #1642 已关闭未合并） |
| `up-1673` | `deeptour.jsonl:9` | fix | #1673 closed(completed) | #1686 merged | issue #1673 已关闭(completed)；修复 PR #1686 已合并(dev, 2026-10-04) |
| `up-1623` | `deeptour.jsonl:11` | fix | #1623 closed(completed) | #1627 merged | issue #1623 已关闭(completed)；修复 PR #1627 已合并(dev, 2026-10-04) |
| `up-1648` | `deeptour.jsonl:12` | fix | #1648 closed(completed) | #1668 merged | issue #1648 已关闭(completed)；修复 PR #1668 已合并(dev, 2026-10-04) |

## 需改派（3 张）

| 卡 | 位置 | 类型 | 上游 issue 状态 | 关联 PR（引用号·状态） | 改派方向 |
|---|---|---|---|---|---|
| `up-1215` | `deeptour.auto.jsonl:78` | review | #1215 open | #1214 closed、#1216 closed、#1219 open、#1185 closed、#1239 closed | 复核对象 PR #1216 已关闭未合并(2026-10-04)，跟踪 issue #1215 仍开放；存在后继 PR #1219（开放，base=dev）可改指 |
| `up-1389` | `deeptour.auto.jsonl:96` | fix | #1389 open(重开后仍开放) | #1398 merged、#1615 merged | 回收站主体已由 PR #1398(2026-09-13) 与 #1615(2026-10-04) 合并落地，但 issue #1389 关闭后又重开，仍有残留问题；卡面需按重开后范围改写 |
| `up-1419` | `deeptour.auto.jsonl:104` | review | #1419 open | #1420 closed | 复核对象 PR #1420 已关闭未合并(2026-10-04)，跟踪 issue #1419 仍开放；需重新定位草稿或放弃 |

## 可用（30 张）

| 卡 | 位置 | 类型 | 上游 issue 状态 | 关联 PR（引用号·状态） | 备注 |
|---|---|---|---|---|---|
| `up-1410` | `deeptour.auto.jsonl:2` | fix | #1410 open | #1723 open | issue #1410 仍开放，无已合并修复；交叉引用中出现的开放 PR #1723 仅在描述里提及 #1410，并非其实现 |
| `up-1610` | `deeptour.auto.jsonl:33` | fix | #1610 open | 无 | issue #1610 仍开放，无关联 PR，无合并修复 |
| `up-575` | `deeptour.auto.jsonl:34` | fix | #575 open | 无 | issue #575 仍开放，无关联 PR，无合并修复（注：myfork 已有分支 glm-reserve/up-575 在途） |
| `up-440` | `deeptour.auto.jsonl:35` | fix | #440 open | 无 | issue #440 仍开放，无关联 PR，无合并修复（注：myfork 已有分支 glm-reserve/up-440 在途） |
| `up-1481` | `deeptour.auto.jsonl:79` | verify | #1481 open | #1488 merged | 验证卡：修复 PR #1488 已合并(dev, 2026-09-23)，「是否真正闭环」的验证仍待执行；issue #1481 仍开放 |
| `up-1478` | `deeptour.auto.jsonl:80` | verify | #1478 open | #1480 merged | 验证卡：修复 PR #1480 已合并(dev, 2026-09-23)，验证仍待执行；issue #1478 仍开放 |
| `up-1359` | `deeptour.auto.jsonl:81` | verify | #1359 open | #1373 merged、#1363 closed、#1413 merged | 验证卡：修复链 PR #1373(2026-09-23)/#1413(2026-09-13) 已合并，验证仍待执行；issue #1359 仍开放 |
| `up-1228` | `deeptour.auto.jsonl:82` | verify | #1228 open | #1231 merged | 验证卡：修复 PR #1231 已合并(dev, 2026-09-07)，验证仍待执行；issue #1228 仍开放 |
| `up-1223` | `deeptour.auto.jsonl:83` | verify | #1223 open | #1266 merged、#1333 merged、#1443 merged | 验证卡：修复链 PR #1266/#1333/#1443 均已合并(dev)，验证仍待执行；issue #1223 仍开放 |
| `up-1421` | `deeptour.auto.jsonl:84` | verify | #1421 open | #1436 merged | 验证卡：修复 PR #1436 已合并(dev, 2026-09-13)，验证仍待执行；issue #1421 仍开放 |
| `up-1447` | `deeptour.auto.jsonl:95` | fix | #1447 open | #1237 closed、#1472 merged | issue #1447 仍开放；切片 PR #1472 已合并(2026-09-23)、#1237 已关闭未合并，剩余切片仍可执行 |
| `up-451` | `deeptour.auto.jsonl:97` | fix | #451 open | #1221 open、#458 closed、#460 closed、#560 closed、#1724 open | issue #451 仍开放；在途开放 PR #1221(base=dev) 与 #1724(我方分支, base=main)，开工前需协调避免重复 |
| `up-1209` | `deeptour.auto.jsonl:99` | fix | #1209 open | 无 | issue #1209(提案) 仍开放，无关联 PR，无合并修复 |
| `up-1303` | `deeptour.auto.jsonl:100` | fix | #1303 open | 无 | issue #1303(提案) 仍开放，无关联 PR，无合并修复 |
| `up-1220` | `deeptour.auto.jsonl:101` | review | #1220 open | #1221 open、#1694 merged、#1285 closed、#1401 merged | 复核卡：目标 PR #1221 仍开放；#1694 已合并(dev, 2026-10-04)，复核范围缩减至 #1221（#1694 可作对照） |
| `up-1176` | `deeptour.auto.jsonl:102` | review | #1176 open | #1270 open、#1179 closed、#1345 merged | 复核卡：目标 PR #1270 仍开放（另 #1345 已合并 2026-09-23 可作对照）；issue #1176 仍开放 |
| `up-1696` | `deeptour.auto.jsonl:103` | review | #1696 closed(completed) | #1698 open、#1697 closed | 复核卡：目标 PR #1698 仍开放（我方分支，base=dev）；issue #1696 已关闭(completed) |
| `up-932` | `deeptour.auto.jsonl:133` | fix | #932 open | #1061 closed | issue #932(提案) 仍开放；前次 PR #1061 已关闭未合并(2026-10-04)，可重新执行 |
| `up-916` | `deeptour.auto.jsonl:134` | fix | #916 open | #1464 merged | issue #916(提案) 仍开放；部分切片 PR #1464 已合并(2026-09-23)，剩余切片在途开放 PR #1734(我方分支) |
| `up-860` | `deeptour.auto.jsonl:135` | fix | #860 open | #979 closed | issue #860(提案) 仍开放，无关联 PR，无合并修复 |
| `up-961` | `deeptour.auto.jsonl:136` | fix | #961 open | #1309 closed | issue #961(提案) 仍开放，无关联 PR，无合并修复 |
| `up-1307` | `deeptour.auto.jsonl:137` | fix | #1307 open | #1309 closed | issue #1307(提案) 仍开放；前次 PR #1309 已关闭未合并(2026-10-04)，可重新执行 |
| `up-403` | `deeptour.auto.jsonl:138` | fix | #403 open | 无 | issue #403 仍开放，无关联 PR，无合并修复 |
| `up-1611` | `deeptour.auto.jsonl:173` | fix | #1611 open | 无 | issue #1611 仍开放，无关联 PR，无合并修复 |
| `up-655` | `deeptour.auto.jsonl:174` | fix | #655 open | 无 | issue #655 仍开放，无关联 PR，无合并修复（注：myfork 已有分支 glm-reserve/up-655 在途） |
| `up-684` | `deeptour.auto.jsonl:175` | fix | #684 open | 无 | issue #684 仍开放，无关联 PR，无合并修复 |
| `up-1236` | `deeptour.auto.jsonl:176` | fix | #1236 open | #1237 closed | issue #1236(提案) 仍开放；前次 PR #1237 已关闭未合并(2026-10-04)，可重新执行 |
| `up-1629` | `deeptour.auto.jsonl:177` | fix | #1629 open | 无 | issue #1629 仍开放，无关联 PR，无合并修复 |
| `up-1779` | `deeptour.auto.jsonl:213` | fix | #1779 open | 无 | issue #1779 仍开放（2026-10 新增），无关联 PR，无合并修复 |
| `up-1641` | `deeptour.jsonl:10` | fix | #1641 open | 无 | issue #1641 仍开放，无关联 PR，无合并修复 |

## 附注

- consumed 交叠：`up-1646` / `up-1647` / `up-1678` 已列入 `deeptour.consumed`，但仍残留在 `deeptour.jsonl` 第 1–3 行 —— 本次已判「已过时」，建议 harvest 时一并清除该残留行。
- `deeptour.0priority.jsonl`（11 行）不含任何 up-* 卡，全部为内部 fix/test/bundle 卡，不在本次核对范围。
- 可用卡中的在途提示：`up-451`（开放 PR #1221 / #1724）、`up-916`（开放 PR #1734）、`up-1410`（无在途实现 PR）、`up-575` / `up-440` / `up-655`（myfork 已有在途分支）—— 这些卡判定仍为可用，但开工前需与在途工作去重。
- 「需改派」3 张的上游 issue 本身仍有效（#1215 / #1419 / #1389），建议改写卡面指向新的对象（如 #1219 后继 PR、#1389 重开后的残留问题）而非直接剔除。

---
生成时间：2026-10-05 07:50 UTC；核对脚本随附于本目录 `scripts/`，API 原始响应缓存未入库（可按 snapshot 中的引用号重新拉取复核）。

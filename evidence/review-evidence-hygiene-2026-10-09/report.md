# 历史分支 evidence 报告卫生抽查（2026-10-09）

只读抽查 myfork 近期证据分支的 evidence/ 报告卫生。未检出任何历史分支与产品代码；主检出区未做 checkout/reset/clean，检查全部通过 `git show` / `git ls-tree` 直接读取对象完成，SHA256 均基于 git blob 内容复算。

## 抽查范围

按 myfork 分支提交时间取最近的 12 个含 evidence 报告的分支（2026-10-09 05:20 至 13:47 UTC-7），每支抽其 evidence 目录全部文件（12 份 report.md，共 24 个内容文件）：

| # | 分支 | 头提交 | evidence 目录 | 文件数 |
|---|------|--------|---------------|--------|
| 1 | myfork/scan/web-client-cache-20261009 | b0343f74b | web/evidence/web-client-cache-20261009 | 3 |
| 2 | myfork/dt-agen1272-data-dir-layout | fc2b0f23c | evidence/data-dir-layout-20261009 | 3 |
| 3 | myfork/scan/cron-registry-20261009 | a4149d1a8 | evidence/cron-registry-20261009 | 3 |
| 4 | myfork/scan/ws-message-contracts-20261009 | c49d667cb | web/evidence/ws-message-contracts-2026-10-09 | 3 |
| 5 | myfork/web-evidence/web-bundle-deps-20261009 | 0f0a0f41e | web/evidence/web-bundle-deps-20261009 | 3 |
| 6 | myfork/evidence/guide-file-io-path-durability-20261009 | d8278873e | evidence/guide-file-io-path-durability-20261009 | 1 |
| 7 | myfork/guide/suggestions-20261009 | 3c0047db8 | evidence/guide-suggestions-20261009 | 1 |
| 8 | myfork/guide/provider-registry-20261009 | 93c799286 | evidence/guide-provider-registry-20261009 | 2 |
| 9 | myfork/scan/web-storage-schema-20261009 | f6bfc41b4 | web/evidence/web-storage-schema-20261009 | 3 |
| 10 | myfork/evidence/coverage-gaps-intree-20261009 | 21764e06d | evidence/coverage-gaps-intree-20261009 | 6 |
| 11 | myfork/test/web-space-import-20261009 | 32b5fc3b9 | web/evidence/web-zero-deep-20261009 | 1 |
| 12 | myfork/scan/content-dedup-20261009 | 893d3ea02 | evidence/content-dedup-2026-10-09 | 2 |

## 检查方法

- SHA256SUMS：逐条复算分支树内对应 blob 的 SHA-256 并比对；同时检查目录内文件是否被 SUMS 全覆盖、有无列了不存在的路径。
- 密钥/token：对全部内容文件逐行匹配常见泄漏模式（私钥块、`sk-`/`ghp_`/`AKIA`/`xox`/`AIza` 类前缀、JWT、Bearer 头、通用 `api_key/secret/token/password=长串` 赋值、40+ 位长十六进制串）。
- 内部词：按卡片定义清单（内部任务卡编号模式、平台名、模型名、主机名、Tailscale 域、fork 账号名）逐行匹配；命中只记录位置，不摘录原文。
- 行锚点：从 report.md 提取 `路径:行号` 引用，逐一在对应分支树内解析目标文件并核对行号是否落在文件行数内。路径解析依次尝试原样、`deeptutor/`、`web/`、evidence 目录相对、唯一 basename 匹配。

## 发现分级清单

### 高危（2 项）

- **H1 内部任务卡编号泄漏（15 处，涉及 7 个分支）**：evidence 内容文件命中内部任务卡编号模式（大写前缀+连字符+数字），位置如下（仅位置，不摘录原文）：
  - myfork/scan/web-client-cache-20261009 @ b0343f74b — `web/evidence/web-client-cache-20261009/inventory.json:2`、`report.md:3`
  - myfork/dt-agen1272-data-dir-layout @ fc2b0f23c — `evidence/data-dir-layout-20261009/layout.json:4`
  - myfork/scan/cron-registry-20261009 @ a4149d1a8 — `evidence/cron-registry-20261009/jobs.json:4`
  - myfork/scan/ws-message-contracts-20261009 @ c49d667cb — `web/evidence/ws-message-contracts-2026-10-09/contracts.json:3`、`report.md:3`
  - myfork/evidence/coverage-gaps-intree-20261009 @ 21764e06d — `evidence/coverage-gaps-intree-20261009/report.md:1,5,10,12`、`aggregate.py:7`、`scan_coverage_gaps.py:2,9,20`
  - myfork/test/web-space-import-20261009 @ 32b5fc3b9 — `web/evidence/web-zero-deep-20261009/report.md:3`
  - 说明：其余清单内内部词（平台名、模型名、主机名、域名、账号名，含大小写变体）在全部抽样内容中 0 命中。因分支已推送、按卡不改历史分支，建议在 myfork 侧按需清理（重写或废弃这些历史证据分支），后续证据生成时对头部落卡 ID 做脱敏。
- **H2 死行锚点（1 处）**：myfork/dt-agen1272-data-dir-layout @ fc2b0f23c — `evidence/data-dir-layout-20261009/report.md:23` 的锚点指向 `multi_user/legacy_kids_learner_migration.py:99`，该路径在分支全树内不存在（全树无任何同名文件），锚点不可核。

### 中危（2 类）

- **M1 缺 SHA256SUMS（3 个目录）**：report-only 证据目录未附校验和，报告完整性不可复算：
  - myfork/evidence/guide-file-io-path-durability-20261009 @ d8278873e（evidence/guide-file-io-path-durability-20261009/）
  - myfork/guide/suggestions-20261009 @ 3c0047db8（evidence/guide-suggestions-20261009/）
  - myfork/test/web-space-import-20261009 @ 32b5fc3b9（web/evidence/web-zero-deep-20261009/）
- **M2 裸 basename 行锚点不可唯一解析（60 处，7 个分支）**：形如 `service.py:40` 的锚点在分支树内有 2–22 个同名候选，无法唯一核验。逐一核对后所有行号均与至少一个候选文件行数相容（未发现确定越界），但引用方式不可复核，属规范性风险。分布：cron-registry 22、content-dedup 15、provider-registry 10、ws-message-contracts 7、file-io guide 3、web-client-cache 2、suggestions 1。建议统一使用仓库根相对路径。

### 低危（1 项）+ 备注

- **L1 SUMS 路径约定不一致**：myfork/guide/provider-registry-20261009 @ 93c799286 的 SHA256SUMS 使用仓库根相对路径（其余 8 个目录均为目录相对路径）；哈希本身复算通过，仅约定不统一，工具按约定解析时会误判。
- 备注：coverage-gaps-intree 与 web-zero-deep 两份 report.md 不含任何 `路径:行` 锚点（0 处可核），可复核性弱，不单列为缺陷。

## 通过项

- **SHA256SUMS 可复算**：9/12 目录有 SUMS，共 18 条记录全部复算一致（0 mismatch），除 M1 外目录覆盖完整。
- **密钥/token**：全部 24 个内容文件、全部模式 0 命中。
- **行锚点总体**：共提取 398 个锚点，337 个唯一解析且行号有效；1 个死锚点（H2）、60 个裸 basename 不可唯一解析（M2）。

## 结论

FAIL（卫生发现非零：高危 2 项、中危 2 类、低危 1 项）。主要问题是历史证据分支的头部任务卡编号泄漏与 1 处死锚点；密钥类为零，SHA256 复算全部通过。按卡要求未改动任何历史分支，处置建议交由人工决定。

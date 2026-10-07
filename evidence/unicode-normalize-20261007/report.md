# AGEN-1002 Unicode 归一化一致性清点报告

- 扫描日期：2026-10-07
- 基线 commit：`f07029cfcf2c8dfccdb671cdfc343db8334f5741`（origin/main，"release: v1.6.13"）
- 工作副本：独立 worktree（`dt-agen1002-uni-wt`，分支 `scan/unicode-normalize-20261007`），主工作区零改动；本卡全程只读，未改任何产品代码
- 数据文件：`data.json`（全量清单与计数）；实证脚本：`verify_samples.py`（8 条抽样，全部按现行代码复核通过）

## 扫描方法

- rg 检索 `unicodedata.normalize` / `.casefold()` / `.lower()` / `strip()` / `sorted(...key=...)`（Python，含 `scripts/`）与 `toLowerCase()` / `localeCompare` / `.normalize(`（web/，不含 node_modules、不含 tests/）。
- 每个处理点回读上下文确认语义后归类：文件名读写 / 搜索匹配 / 去重键 / 排序比较。
- 8 条关键行为用 Python 对现行代码实证（NFC/NFD 输入对照），见 `verify_samples.py` 输出，全部与静态结论一致。

## 覆盖统计（census）

- `deeptutor/` 内 `.lower()` 调用 744 处；`.casefold()` 75 处（30 个文件），另有 `scripts/` 1 处 —— 两套折叠口径并存。
- `unicodedata.normalize` 仅 3 处：上传文件名 NFC（`deeptutor/utils/document_validator.py:97`）、KB 名 NFC（`deeptutor/knowledge/naming.py:20`）、习题检索 NFKC（`deeptutor/services/rag/pipelines/llamaindex/exercise_lookup.py:32`）。
- web 端 `toLowerCase()` 198 处、`localeCompare` 14 处、`String.normalize()` 0 处（前端完全不做 Unicode 归一）。
- 四类处理点清单合计 42 条（文件名 11 / 搜索 9 / 去重 12 / 排序 11），明细见 `data.json`。

## 总体结论

产品在**入口侧已有两道 NFC 防御**（上传文件名、KB 名），但**磁盘读回、manifest 键、目录段、搜索、去重、排序全部按"原样字节/仅 casefold"处理，没有 NFC 兜底**。在 macOS（NFD 分解环境）部署或经 Finder/AirDrop/外部解压把 NFD 文件放进 `raw/` 时，会出现同一视觉文件名 NFC/NFD 双份：列表双行、serve/delete 只命中其一、PageIndex manifest 键跨形式查找**静默失败**（`remove_document` 返回 False 不报错）。去重与排序在 `.lower()` / `.casefold()` / JS `toLowerCase()` 三套口径下对非 ASCII（典型 ß）结论不一致。

## 高风险清单（跨平台 macOS NFD 视角）

| 级别 | 风险 | 位置 |
| --- | --- | --- |
| H1 | KB `raw/` 内 NFC/NFD 混写：上传名被 NFC 化，但目录段 `_sanitize_path_segment` 只删坏字符不归一；serve/delete 按精确字节路径解析，NFC 请求名对 NFD 磁盘文件 404 | `deeptutor/api/routers/knowledge.py:379-383`、`deeptutor/api/routers/knowledge.py:3038-3055`、`deeptutor/utils/document_validator.py:97` |
| H2 | PageIndex manifest 键 = 磁盘文件名原文；`remove_document` 先全名后 basename 两次精确查找，跨形式未命中**静默返回 False**；重索引产生双条目 | `deeptutor/services/rag/pipelines/pageindex/pipeline.py:202`、`deeptutor/services/rag/pipelines/pageindex/pipeline.py:273`、`deeptutor/services/rag/pipelines/pageindex/storage.py:95-103` |
| H3 | 课程名 casefold 查重（无 NFC）：NFC/NFD 双胞胎课程名可并存 | `deeptutor/services/courses.py:324-325` |
| M1 | 搜索链路无 NFC：MCP 目录搜索、会话标题搜索、reading hints 回声检测在 NFD 查询下漏配 | `deeptutor/services/mcp/catalog/loader.py:114,141,168`、`deeptutor/services/session/pocketbase_store.py:679`、`deeptutor/services/reading_hints.py:335` |
| M2 | 前后端折叠/排序口径不一致：后端 `.lower()`（列表/设置/文件路由）与 `.casefold()`（课程/MCP 目录）并存，前端 `toLowerCase().localeCompare` 再叠加 locale 因素 → 同一数据两端顺序与去重结论可不同 | `deeptutor/api/routers/knowledge.py:3075`、`deeptutor/services/courses.py:331`、`web/components/knowledge/KbDocumentList.tsx:99,104` |
| L1 | KB 名 URL 参数精确集合匹配，无 NFC（API 深链/外部工具 404） | `deeptutor/api/routers/knowledge.py:893-898` |
| L2 | co_writer docx 下载名保留 NFD 原形式，落盘成 NFD 文件 | `deeptutor/api/routers/co_writer.py:736-744` |

## 四类处理点明细（每条附 path:line）

### A. 文件名读写（11 条）

| 位置 | 处理 | 风险 |
| --- | --- | --- |
| `deeptutor/utils/document_validator.py:97` | NFC（防御到位，S1 实证 NFD 输入落盘为 NFC） | ok |
| `deeptutor/knowledge/naming.py:20` | KB 名 NFC（防御到位） | ok |
| `deeptutor/api/routers/knowledge.py:379-383` | 目录段无归一（S2 实证 NFD 保留） | 高 |
| `deeptutor/api/routers/knowledge.py:3038-3055` | 精确字节路径解析 | 高 |
| `deeptutor/api/routers/knowledge.py:893-898` | URL 参数精确匹配 | 低 |
| `deeptutor/services/rag/pipelines/pageindex/pipeline.py:202` + `storage.py:95-103` | manifest 键原文写入 | 高 |
| `deeptutor/services/rag/pipelines/pageindex/pipeline.py:273` | 键两次精确查找，未命中静默 False（S7 实证） | 高 |
| `deeptutor/api/routers/co_writer.py:736-744` | 下载名原形式 | 低 |
| `deeptutor/services/web_source/crawler.py:131-167` | unquote+quote ASCII 化（防御到位） | ok |
| `deeptutor/services/partners/manager.py:177-197` | ASCII slug + CJK hash 兜底（防御到位） | ok |
| `deeptutor/api/utils/http_headers.py:12-22` | RFC 5987 filename*（防御到位） | ok |

另注：skill 有两套 slug 约定（`deeptutor/services/skill/hub.py:907-909` 允许 `._-`，`deeptutor/services/skill/service.py:714-716` 仅 `-`），非 ASCII 一律丢弃，仅注记不列险。

### B. 搜索匹配（9 条）

| 位置 | 处理 | 风险 |
| --- | --- | --- |
| `deeptutor/services/mcp/catalog/loader.py:114,141,168` | `strip().casefold()` contains，无 NFC | 中 |
| `deeptutor/services/session/pocketbase_store.py:679` | title casefold contains，无 NFC | 中 |
| `deeptutor/services/chat_hints.py:183-184` | `\w` 剔除+casefold；NFD 组合符被正则丢弃，键随形式变（S3 实证 cafépdf vs cafepdf） | 中 |
| `deeptutor/services/reading_hints.py:335` | 同上模式 | 中 |
| `deeptutor/reading/epub_bilingual.py:75,79` | casefold 集合比对 | 低 |
| `deeptutor/services/rag/eval/matching.py:45-50` | `.strip().lower()`（eval 内自洽，与线上 casefold 口径不同） | 低 |
| `deeptutor/services/rag/pipelines/llamaindex/exercise_lookup.py:32` | NFKC + 破折号翻译（防御到位） | ok |
| `deeptutor/api/routers/book.py:199` | casefold 相等 | 低 |
| `deeptutor/reading/references.py:142` | casefold contains | 低 |

### C. 去重键（12 条）

| 位置 | 处理 | 风险 |
| --- | --- | --- |
| `deeptutor/services/courses.py:324-325` | 课程名 casefold 查重（S4 实证跨形式失效） | 高 |
| `deeptutor/services/partners/commands.py:293,298,362,368` | 模型名 casefold 去重/匹配 | 中 |
| `deeptutor/services/partner_groups/manager.py:1538,1540` | 别名 casefold 键 | 中 |
| `deeptutor/services/partner_groups/manager.py:1630` | strip+@清理+CJK 标点+casefold | 低 |
| `deeptutor/services/suggestions.py:373-377,511-513` | label casefold seen-set | 低 |
| `deeptutor/services/memory/recall.py:131` | (surface, label.casefold()) 键 | 低 |
| `deeptutor/services/memory/store.py:37` | join(split()).casefold() 键 | 低 |
| `deeptutor/tools/question_bank.py:371` | 同上 | 低 |
| `deeptutor/reading/quiz.py:64` | 同上 | 低 |
| `deeptutor/reading/translation.py:51` | 同上 | 低 |
| `deeptutor/reading/vocabulary.py:61` | 同上 | 低 |
| `web/lib/chat-import/chatgpt.ts:130-137,202-205` | ASCII id Set 精确去重 | 低 |

### D. 排序比较（11 条）

| 位置 | 处理 | 风险 |
| --- | --- | --- |
| `deeptutor/api/routers/knowledge.py:3075` | `str(p).lower()` 排序（与 casefold 口径不一致；S8 实证 NFC/NFD 同名非邻） | 中 |
| `deeptutor/api/routers/settings.py:635,648,695,708,720,732,837` | label `.lower()` | 低 |
| `deeptutor/services/rag/file_routing.py:395` | `str(path).lower()` | 低 |
| `deeptutor/services/courses.py:331` | `name.casefold()`（S5 实证 ß 与 lower 排序不同） | 中 |
| `deeptutor/services/courses_state.py:304,338,380,384` | casefold | 低 |
| `deeptutor/services/mcp/catalog/loader.py:86` | casefold | 低 |
| `scripts/export_discord_history.py:496` | casefold | 低 |
| `web/components/knowledge/KbDocumentList.tsx:99,104` | `toLowerCase().localeCompare` | 中 |
| `web/components/reading/library/ReadingLibrary.tsx:140` | `localeCompare(b.title, i18n.language)` | 低 |
| `web/components/partners/PartnerChannels.tsx:220` | `localeCompare` | 低 |
| `web/components/knowledge/KbDocumentsSection.tsx:69` | `localeCompare` | 低 |

## strip / 大小写折叠的非 ASCII 行为差异

1. **BOM**：Python `.strip()` 不去除 U+FEFF（S6 实证保留）；ECMAScript `.trim()` 按规范去除（White_Space 含 ZWNBSP）。跨语言 trim/strip 语义不一致，粘贴文本比较可残留 BOM。
2. **两套折叠并存**：后端 `.lower()` 744 处 vs `.casefold()` 75 处。`ß`：`.lower()`→`ß`，`.casefold()`→`ss`（S5 实证），同一数据经两处折叠去重/排序结论不同（`Straße`/`Strasse` 在 casefold 下相邻、在 lower 下不相邻）。
3. **前后端折叠不同**：JS `'ß'.toLowerCase()==='ß'`，与 Python `casefold()` 相反；前端 198 处 `toLowerCase()` 与后端两套口径叠加。
4. **localeCompare**：web 14 处顺序依赖宿主/界面 locale，与后端 Python 排序互不一致。
5. **正则 `\w` 与 NFD**：Python `\w` 不匹配组合符号（Mn 类），NFD 文本经 `[^\w…]+` 剔除后丢音符，与 NFC 结果发散（S3 实证）。

## 抽样实证（8/8 通过）

`python3 evidence/unicode-normalize-20261007/verify_samples.py`，要点：

- S1 上传文件名 NFD→NFC（防御成立）；S2 目录段 NFD 保留（缺口成立）
- S3 回声检测键 NFC/NFD 发散；S4 casefold 查重不匹配双胞胎
- S5 ß 折叠与排序口径差异；S6 Python strip 保留 U+FEFF
- S7 manifest 跨形式键查找未命中（直接与 basename 均未命中）
- S8 NFC/NFD 同名按码点排序非邻排列

## 修复方向建议（不在本卡执行）

1. 最小改动：在 `_sanitize_path_segment`、`_resolve_kb_raw_file_or_404`、PageIndex `upsert_doc`/`remove_document` 键处理处统一 `unicodedata.normalize("NFC", ...)`（与上传/KB 名入口对齐）。
2. 中期：收敛折叠口径——Python 比较键统一 `strip+casefold+NFC`，前端统一一个 helper（`normalize('NFC').toLowerCase()` 或引入 Intl.Collator）。
3. 明确 `localeCompare` 是否需要固定 locale，保证前后端列表顺序一致。

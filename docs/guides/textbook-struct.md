# 教材结构化子系统导读（textbook_struct 解析管线与章节数据模型）

- 基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 相对仓库根，行号随演进漂移，以符号名为准。
- 范围：`deeptutor/textbook_struct/**` 及其输入（MinerU layout.json）与潜在消费方（book 章节树、reading 大纲）。
- 去重：guide-book（book 引擎与 blocks 生成）、guide-reading（阅读面与素材库）、guide-parsing（MinerU 解析引擎运维）各自成卡；本文只在对接点触及它们，不展开内部。
- 上游在途：2026-10-06 复查无直接改动 `textbook_struct` 的开放 PR（#1608/#1734 只动 book/reading 前端体验）。

## 0. 一句话定位

从 MinerU 的 `layout.json` **确定性**重建教材章节树（零 LLM），产出带半开页区间的 `Chapter` 列表。当前是孤立就绪件：包内声明不 import deeptutor（`deeptutor/textbook_struct/__init__.py:6`），全仓库检索只有包自身与 `tests/textbook_struct/test_page_headers.py:13-15` 引用它——**所有消费链路都还没接**。

演进脉络（`git log -- deeptutor/textbook_struct`）：footer 路径 v0.1（0b6d5be58）→ 页眉内嵌章节号归一化（4a01a8cff）→ 暴露 header rebuild + 保留末章页区间（c32351631）→ 共享边界页（ad958a5cd）→ 跨章重名节保留（98529ad0c）。

## 1. 模块地图

| 角色 | 文件 | 关键符号 / 说明 |
| --- | --- | --- |
| 包出口 | `deeptutor/textbook_struct/__init__.py:9-20` | 导出 `Chapter/rebuild/rebuild_from_headers/rebuild_from_headers_level/verify_offset/COLUMN_BLACKLIST`；`detect_frames` 未导出，只能深导入 |
| title 块路径（v0.1） | `deeptutor/textbook_struct/chapter_rebuild.py:82` | `rebuild(layout, top_band=120.0, merge_gap=40.0)`；先同行合并再四重过滤（`chapter_rebuild.py:92,:94,:96,:98,:100`） |
| 页眉页脚路径（v0.2） | `deeptutor/textbook_struct/page_headers.py:76` | `rebuild_from_headers(layout)`：footer verbatim + header 归一化双通道（`page_headers.py:65,:67-70`），meta 带印刷页码（`:97`） |
| 层级感知重建 | `deeptutor/textbook_struct/chapter_rebuild.py:213` | `rebuild_from_headers_level(layout, unit="课")`：仅 unit 级页眉变化开新章，父级元组去重（`:242-247`） |
| 框题/栏目探测 | `deeptutor/textbook_struct/chapter_rebuild.py:146` | `detect_frames(...)`：页中 title 块按字高带分 frames/extras（`:149-150`），返回 `(frames, extras)` |
| 印刷页码校验 | `deeptutor/textbook_struct/chapter_rebuild.py:260` | `verify_offset(chapters)`：物理页−印刷页偏移一致性（`:266-273`） |
| 数据模型 | `deeptutor/textbook_struct/chapter_rebuild.py:29-38` | `Chapter` dataclass：title/page_idx/bbox/end_page_idx/level(预留)/meta |
| 词表黑名单（layer 0） | `deeptutor/textbook_struct/column_blacklist.py:9-41` | `COLUMN_BLACKLIST` 25 个栏目名；封闭词表有意不做模糊匹配（docstring `:4-7`） |
| 页眉归一化 | `deeptutor/textbook_struct/page_headers.py:33-46` | `HEADER_CHAPTER_RE` + `normalize_header_chapter`："集合第1章"→"第1章 集合" |

## 2. 输入与数据流

### 2.1 输入：MinerU layout.json（不是 content_list）

输入形状：`layout["pdf_info"]`，每页一个 dict（`page_idx/para_blocks/preproc_blocks/discarded_blocks/page_size`），块带 `type/bbox/lines[].spans[].content`（`chapter_rebuild.py:9-11` 模块 docstring）。真实样例：`tests/fixtures/lightrag_bridge/mineru-v2-current/layout.json`（顶层 `pdf_info/_backend/_version_name`，单页含 preproc/para/discarded 三个块容器）。

**关键差异**：生产解析链路的 IR 只交付 `*.md + *_content_list.json + images`（`services/parsing/types.py:36-45`；`services/parsing/cache.py:162-183` 的 `load_ir` 只读这两类）；layout.json 属于"其余产物"，云端分片路径仅以 `partNN_` 前缀落盘保留（`services/parsing/engines/mineru/cloud.py:324-332`）。要接 textbook_struct 必须经 `ParsedDocument.workdir`（`types.py:45`）直接读 layout 文件——IR 层今天不转发它。

### 2.2 title 块路径 `rebuild`（v0.1）

`chapter_rebuild.py:82-110`：每页取 `type=="title"` 的 para_blocks（`:91`）→ `merge_adjacent` 按 y0 排序，纵向间距 <40 且 x 有重叠的相邻标题块合并（bbox 并集 + 文本拼接，`:47-73`）→ 四重过滤：黑名单（`:94`）→ `CHAPTER_RE`"^第X课/章/节/单元"（`:22,:96`）→ 去空格后 ≥4 字（`MIN_TITLE_CHARS :26`，判定 `:98`）→ bbox.y0 < top_band 页顶带（`:100`）→ `_dedupe_keep_last` 同名章保留后出现的正文命中、丢弃目录页假阳性（`:113-123`）→ `assign_page_ranges` 半开区间 `[page_idx, end_page_idx)`（`:126-135`）。

### 2.3 页眉页脚路径 `rebuild_from_headers`（v0.2，推荐）

MinerU 把页眉页脚丢进 `discarded_blocks`，对 K12 教材那是金矿（`page_headers.py:3-5` docstring）。`page_facts` 双通道采集（`:49-73`）：footer 块逐字匹配 `CHAPTER_RE`（`:65`）；header 块章节号内嵌时经 `normalize_header_chapter` 归一成"第N章 章名"（`:33-36,:67-70`）；`page_number` 块给印刷页码（`:71-72`）。`rebuild_from_headers` 每个新标题全书首次出现即章起点（`:76-100`），`meta.printed_page` 记起始页印刷页码（`:97`），bbox 恒为空列表（`:96`），层内按标题 seen 集合去重（`:84,:89-91`）。

### 2.4 层级感知 `rebuild_from_headers_level`

两级页眉（"第X章/第Y节"轮换）下，另一级的变化不得开新章，否则裂出伪章（`chapter_rebuild.py:214-218` docstring）。只认 `UNIT_RE_MAP[unit]`（`:198-203`），同步跟踪 `PARENT_UNITS` 父级标题（`:205-210`），(父级…, 本级) 元组与上次相同则跳过（`:242-247`）——这修复了跨章"第1节"重名被 seen 去重吞掉的问题（commit 98529ad0c；回归测试 `tests/textbook_struct/test_page_headers.py:133-144`）。

### 2.5 质量自检 `verify_offset`

章界检测正确 ⇔ 全书"物理页(1-based) − 印刷页"偏移唯一（`chapter_rebuild.py:261-265` docstring）。返回 `{offsets, consistent, ok}`：无任何 printed_page 时 `ok=False`（`:272`）；offsets 多于一个值即有章界误检（`:269-273`）。

## 3. 与 book / reading 的对接点

现状：**零对接**（检索依据见 §0）。潜在接法：

- **book 章节树**：今天书脊由 LLM 提议——`BookEngine._run_ideation`（`book/engine.py:552`）→ `SpineAgent.process` 流式 JSON（`book/agents/spine_agent.py:52`），JSON 解析不出章节时兜底造一个 Overview 章（`spine_agent.py:88-96`；另一产出方 `SpineSynthesizer` 在 `book/agents/spine_synthesizer.py:83`）。目标模型是 `Spine.chapters`（`book/models.py:342`），元素即 `book/models.py:229-241` 的 `Chapter`。教材场景接法：textbook_struct 的 `Chapter` 列表映射成 book `Chapter`（title 同名；页锚点进 `SourceAnchor`，`book/models.py:218-227`；页区间驱动 page_ids），替换或强约束 SpineAgent 的提议；`detect_frames` 的 frames 对应 `BlockType.SECTION`（`book/models.py:75`）的节级粒度。
- **reading 面**：素材大纲 `OutlineEntry`（`reading/models.py:126`）今天由 `reading/ingestion.py` 按 media 章节/时钟生成（如 `reading/ingestion.py:323,:392,:573`），与 textbook_struct 无关。PDF 教材接入点：用 rebuild 系输出的页区间喂 `OutlineEntry`/`MaterialManifest`（`reading/models.py:207`）做章节大纲与阅读定位；`meta.printed_page` 支撑"印刷页 vs 物理页"双基准显示——显示层选基准是既定设计（`page_headers.py:79-81` docstring：the fix is data, not guesswork）。
- **question/切片链路**：content_list 的 `page_idx` 已被 question 提取与 slicer 消费（`services/parsing/types.py:30` docstring；`tests/services/parsing/test_mineru_slicer.py`；跨分片页号还原在 `services/parsing/engines/mineru/cloud.py:335-348`）。注意 content_list 的 page_idx 与 layout.json 的 para_blocks 是两种表示，不要混用。

## 4. 扩展点

1. 新版式栏目名 → 追加 `COLUMN_BLACKLIST`（`column_blacklist.py:6,9`），保持封闭词表。
2. 新出版社页眉形态 → `HEADER_CHAPTER_RE`/`normalize_header_chapter`（`page_headers.py:33-46`）。
3. 新层级记号（讲/篇等）→ `UNIT_RE_MAP` + `PARENT_UNITS`（`chapter_rebuild.py:198-210`）。
4. 节级结构 → `detect_frames`（`chapter_rebuild.py:146-193`）；当前未进包导出（`__init__.py:13-20`）。
5. 只有 content_list、无 layout.json 的场景 → 需新写适配层，今天不存在。

## 5. 已知坑

1. **layout.json 不在 IR 里**（§2.1，`services/parsing/cache.py:162-183`）——最大的对接坑；分片云端解析时文件还被改名 `partNN_<name>`（`services/parsing/engines/mineru/cloud.py:332`），按原名 glob 会落空。
2. `assign_page_ranges` 原地排序并修改入参列表（`chapter_rebuild.py:128-130`），调用方持有的列表顺序会被改。
3. 同页两章共享同一 `end_page_idx`（`chapter_rebuild.py:130-132`；测试 `test_page_headers.py:147-152`）——按页跳转没问题，按"章末页"切资源会重复计页。
4. `detect_frames` 字高带是针对特定排版实测的魔数（帧题 ~22-24 / 探究 ~27，注释 `chapter_rebuild.py:139-141`，默认参数 `:149-150`），换字体/扫描质量即漂移；`PUBLISHER_NOISE`（`:143`）同样按教材手工维护。
5. `HEADER_CHAPTER_RE` 的 pre/post 各限 20/30 字符（`page_headers.py:34-35`），超长内嵌章名直接不匹配 → 静默漏章。
6. `rebuild_from_headers`（非 level 版）按标题 seen 去重（`page_headers.py:84,:89-91`）：跨章重名的节会被吞，必须用 level 版（§2.4）。
7. `_dedupe_keep_last` 假设目录页在正文前（`chapter_rebuild.py:113-123`，后出现者胜）；目录在书末的异常排版会反选。
8. 页眉路径 `Chapter.bbox` 恒为 `[]`（`page_headers.py:96`），下游不能假设 bbox 非空；`meta.printed_page` 可能为 None（`page_headers.py:97`；`chapter_rebuild.py:254`）。
9. `verify_offset` 依赖 printed_page 数字块（`page_headers.py:71-72`）；封面/插页无页码时该章 offset 缺失，"无数据"与"真错位"在返回值里不可区分（`chapter_rebuild.py:269-273`）。
10. page_headers ↔ chapter_rebuild 的循环依赖靠函数内 import 解开（`chapter_rebuild.py:220-222`）；把 `page_facts` 提到模块顶部会炸。

## 6. 测试空白清单（可拆卡条目）

现状：仅 `tests/textbook_struct/test_page_headers.py`（152 行，11 用例，0.39s 全绿），集中在页眉路径（normalize `:40-61`、page_facts `:67-78`、level 重建 `:101-130`、节号重启 `:133-144`、同页区间 `:147-152`）。

零测试（按拆卡价值排序）：

1. `rebuild` 四重过滤端到端（黑名单/正则/页顶带/最小长度各一反例 + 合并 + 目录去重 + 页区间）——`chapter_rebuild.py:82-135`，v0.1 主路径完全裸奔。
2. `merge_adjacent` 合并与不合并边界（gap 恰好 40、x 不重叠、跨页不合）——`chapter_rebuild.py:47-73`。
3. `detect_frames` 高度带分桶 + 首课前过滤 + 课题残片过滤——`chapter_rebuild.py:146-193`。
4. `rebuild_from_headers` footer-only 路径（现有测试只打 level 版与 page_facts）——`page_headers.py:76-100`。
5. `layout_page_count` 稀疏 page_idx（仅被 level 路径间接覆盖，`test_page_headers.py:107-109`）——`chapter_rebuild.py:76-79`。
6. `verify_offset` 不一致 / 空 offsets 分支（现测试只断言 ok 路径，`test_page_headers.py:112-117`）——`chapter_rebuild.py:260-273`。

弱测试：

7. `normalize_header_chapter` 的 20/30 字符截断边界（`page_headers.py:34-35`）——现测试最长只到 60 字符 prose 拒绝（`test_page_headers.py:56-61`）。
8. 对接契约测试为零：无任何"layout.json → book Spine / reading Outline"用例；接通消费链路前先补契约测试（可复用 `tests/fixtures/lightrag_bridge/mineru-v2-current/layout.json` 起步）。

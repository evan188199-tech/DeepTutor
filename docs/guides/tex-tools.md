# TeX 工具族导读（tex_downloader / tex_chunker）

- 基线：origin/main @ `6cf793bd8`（v1.6.14）。
- 范围：`deeptutor/tools/tex_downloader.py`（下载、解包、主文件定位与残留清理）+ `deeptutor/tools/tex_chunker.py`（LaTeX 分块与边界保持）+ 二者拼出的"下载→分块→入库"数据流。
- 所有锚点形如 `path:line`，相对仓库根。本文只读源码不改代码；与 test-tex-tools（AGEN-439/465，测试轴）、fix-tex-downloader-residue（AGEN-868，残留修复轴）不重复。

## 1. 两个模块在干什么

```
arxiv URL ──► TexDownloader.download_arxiv_source() ──► TexDownloadResult(success, tex_path, tex_content)
                                                          │
              deeptutor/tools/tex_downloader.py:57        ▼
                                          TexChunker.split_tex_into_chunks(tex_content) ──► list[str]
                                          deeptutor/tools/tex_chunker.py:90                │
                                                                                           ▼
                                                    RAG/KB 入库接缝（现状：无产品调用方，见 §5）
```

两者经 `deeptutor/tools/__init__.py:13-15` 惰性导出（`TexChunker`/`TexDownloader`/`read_tex_file`），这是全仓唯一的接线点：**main 上没有任何产品代码调用它们**，当前只被 `tests/tools/test_tex_tools.py`（44 例）消费。理解为"工具层预留的 arXiv 论文入库前处理对"最准确。

## 2. tex_downloader.py：下载、解包与主 tex 定位

公开面 2 个类 + 1 个模块函数：

- `TexDownloadResult`（`deeptutor/tools/tex_downloader.py:28`）：纯结果对象，`success/tex_path/tex_content/error` 四字段，失败时 `error` 承载人读文案（"Unable to extract ArXiv ID" / "Download failed: …" / "Processing failed: …" / "Main tex file not found"）。
- `TexDownloader(workspace_dir)`（`deeptutor/tools/tex_downloader.py:44`）：构造时 `mkdir(parents=True, exist_ok=True)`（`:55`），workspace 既是下载缓存区也是临时目录父目录。
- `download_arxiv_source(arxiv_url, arxiv_id=None)`（`deeptutor/tools/tex_downloader.py:57`）：唯一主入口，七步流水：
  1. 补 ID：`_extract_arxiv_id`（`:134`）正则 `arxiv\.org/(?:abs|pdf)/(\d+\.\d+)`，提不出直接 fail-fast（`:75`）；只认新版数字 ID，不认旧式 `cs/0301012` 与 `e-print/raw` 形态 URL。
  2. 下载：`https://arxiv.org/e-print/{id}`，requests 同步 30s 超时（`:79-84`），无重试、无断点续传。
  3. 落盘临时区：`tempfile.mkdtemp(dir=workspace)`（`:87`），包写成 `{arxiv_id}_source`（`:90-92`）。
  4. 判型解包：`_is_tar_file`（`:141`，tarfile 试开）→ `_extract_tar`（`:157`）；否则 `_is_zip_file`（`:149`）→ `_extract_zip`（`:177`）；都不是则当单文件 tex 直接拷入（`:102-104`）。
  5. 定位主 tex：`_find_main_tex`（`:182`）四级优先：`main.tex/paper.tex/manuscript.tex` 同名优先（`:198-201`）→ 含 `\documentclass` 的首个（`:204-211`，读失败 warn 跳过）→ 最大体积兜底（`:214`）。找不到→提前返回失败（`:110`）。
  6. 固化：拷到 `{workspace}/paper_{arxiv_id}/main.tex`（`:116-120`），目录已存在则复用（`mkdir(exist_ok=True)`）。
  7. 清理：`rmtree(temp_dir)`（`:123`）——**只在成功路径执行**，见 §5-1。
- `read_tex_file(tex_path)`（`deeptutor/tools/tex_downloader.py:225`）：模块级便捷读取，utf-8 + errors="ignore"；`_read_tex_file`（`:217`）同实现但失败包装成 Exception（`:222`）。

**缓存语义**：没有真正的缓存层。`paper_{arxiv_id}/main.tex` 是唯一持久产物，但每次调用都会无条件重新下载覆盖，没有 if-exists 短路；"缓存"仅体现在失败后旧 `main.tex` 仍在盘上可读。

## 3. tex_chunker.py：分块策略与边界保持

公开面 1 个类（私有方法承担全部策略）：

- `TexChunker(model=None)`（`deeptutor/tools/tex_chunker.py:21`）：tokenizer 三级回退——显式 model → 缺省时读 `resolve_llm_runtime_config().model`（`:31-35`，异常吞掉置 None）→ 任何 `tiktoken.encoding_for_model` 失败退 `cl100k_base`（`:37-45`）。离线/未知模型永不炸构造。
- `estimate_tokens(text)`（`deeptutor/tools/tex_chunker.py:47`）：先 `_clean_text` 再编码计数；编码异常退 `len(text)//4` 粗估并 print 警告（`:62-65`）。
- `split_tex_into_chunks(tex_content, max_tokens=8000, overlap=500)`（`deeptutor/tools/tex_chunker.py:90`）：总量不超限直接原样单块返回（`:112-113`，不清洗不重排）；超限才进入"section 切分 → 装箱合并 → 超长 section 降级"三级策略。

私有策略层（边界语义都在这）：

- `_split_by_sections`（`deeptutor/tools/tex_chunker.py:166`）：捕获式正则 `(\\(?:sub)*section\{[^}]*\})` 把 marker 和后随正文重组为段（`:190-195`）；preamble 非空则插到最前（`:198-199`）。**两个边界坑**：`[^}]*` 不支持标题内嵌 `{}`（嵌套即截断）；正则不感知环境，verbatim/注释里的 `\section` 同样会被误切。全文无 marker 时退化为段落切分且 `max_tokens=10000, overlap=0`（`:186`）——这次降级会丢 overlap 语义。
- `_split_by_paragraphs`（`deeptutor/tools/tex_chunker.py:203`）：`\n\n+` 切段装箱；单段仍超限时再按 `[.!?]\s+` 切句硬装（`:233-243`）。段落级重开块时才补 overlap（`:254-257`），句子级硬切不补。
- `_get_overlap_text`（`deeptutor/tools/tex_chunker.py:268`）：对上一块整块编码后取尾部 `overlap_tokens` 再解码（`:280-287`）；上一块不足 overlap 时整块返回。token 级拼接保证 overlap 预算准，但 decode 可能落在 token 边界产生轻微乱码字符。
- `_clean_text`（`deeptutor/tools/tex_chunker.py:67`）：连续空白 ≥101 次折叠为 10 次（`:77`）；单行 >10000 字符截断加 `...[truncated]`（`:83-85`）。防 token 爆炸，但截断可能吞掉超长数学行内容。

**装箱语义**：section/paragraph 两级都是"能塞就塞满，塞不下就落盘重开"；重开时才取前块尾部做 overlap（`split_tex_into_chunks` 内 `:150-157`），顺延合并不加 overlap。超大 section 先 flush 当前块再独立降级切分（`:131-140`）。

## 4. 端到端数据流：下载 → 分块 → 入库

预期链路（工具层设计意图）：

```
1. result = TexDownloader(workspace).download_arxiv_source("https://arxiv.org/abs/1706.03762")
   # 失败：result.success=False + result.error；成功：result.tex_content 为主 tex 全文
   #                                   result.tex_path = {ws}/paper_1706.03762/main.tex
2. chunks = TexChunker(model).split_tex_into_chunks(result.tex_content, max_tokens=8000, overlap=500)
   # list[str]，块间 overlap≈500 tokens
3. 入库：chunks 交给 KB 摄取面 —— 现成接缝是
   RAGService.add_documents(kb_name, file_paths)  deeptutor/services/rag/service.py:72
   （file_paths 走各 pipeline 自带解析/分块，deeptutor/services/rag/pipelines/base.py:24）
```

**现状校准**：第 3 步没有现成接线——`add_documents` 收文件路径且各 pipeline 自带分块，直接喂 chunks 需要落盘临时文件或走自定义 embedding 管道；而第 1、2 步当前也无产品调用方。复现该数据流的最短路径是 `tex_downloader.py:240` 的 `__main__` 示例（真实网络）+ `tex_chunker.py:294` 的 `__main__` 示例（纯本地）。把两个 `__main__` 串起来（下载成功 → chunker 消费 `tex_content`）即可验证 1→2 段（downloader 段需真实网络，chunker 段纯本地）：`tests/tools/test_tex_tools.py` 的 happy path 用例已在 mock 层面固定了这段契约（tar/zip/单文件三种形态落盘，`tests/tools/test_tex_tools.py:116-176`）。

## 5. 已知薄弱点（供修复/补测卡引用）

1. **失败路径临时目录残留（main 未修，最高优先）**：`tex_downloader.py:87` mkdtemp 后仅成功路径 `:123` 清理；"Main tex file not found" 提前返回（`:110`）与两个 except（`:129-132`）都直接 return，每次失败下载在 workspace 遗留含源码包的 `tmp*` 目录。修复已备未进 main：myfork 分支 `fix/tex-downloader-failure-residue-20261006`（AGEN-868，清理移入 finally + 4 个回归测试）。
2. **tar 解包未传 `filter=`**：`_extract_tar`（`tex_downloader.py:175`）用手写 `safe_members` 防 TarSlip 但未传 `filter`，Python 3.12+ 触发 DeprecationWarning；本机 venv 3.13.13 下 `-W error::DeprecationWarning` 复跑 `tests/tools/test_tex_tools.py` → **5 failed, 39 passed**（正常模式 44 passed）。建议改 `tar.extractall(..., filter="data")` 可同时替代手写防护。zip 侧 `_extract_zip`（`:177-180`）无对称防护（依赖 zipfile 自身净化），防御不对称。
3. **覆盖缺口**：44 例整体较全（最大文件兜底、编码回退、清洗边界、退化单句超限均有），仍缺——失败路径"无 tmp* 残留"断言（修复卡 AGEN-868 分支新增的 4 例，main 无）；`_split_by_sections` preamble 保留无显式断言；`_read_tex_file` 读失败抛错路径（`tex_downloader.py:221-222`）；`_extract_zip` 恶意条目行为；超长 section 降级为段落/句子切分时的 overlap 行为（现有降级用例均 `overlap=0`）。
4. **无产品调用方**：两个类仅 `tools/__init__.py:13-15` 惰性导出（§1），入库接缝未实现（§4）；若后续接 RAG 链路，注意 chunker 输出是纯文本块、而 `add_documents` 期望文件路径。
5. **杂项**：模块 docstring "Based on: TODO.md specification"（`tex_chunker.py:11`、`tex_downloader.py:11`）指向不存在的文件；chunker 用 `print` 直出进度（`:64/:84/:115/:163`）而非 logger；下载无重试/限速，arXiv 对高频抓取有限流。

## 6. 验证

```bash
# 用例数与通过状态（本基线实测）
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/tools/test_tex_tools.py -q -p no:cacheprovider
# → 44 passed（19.3s）
# DeprecationWarning 前向兼容探针（§5-2 证据）
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/tools/test_tex_tools.py -q -p no:cacheprovider -W error::DeprecationWarning
# → 5 failed, 39 passed
```

相关卡：测试轴 test-tex-tools（AGEN-439/465，上游 PR #1748 已合并）；残留修复轴 fix-tex-downloader-residue（AGEN-868，待进 main）。工具面全景另见 `docs/guides/tools-surface.md:117-118`（本文是其 tex 两行的展开）；解析引擎侧（docling/mineru 等）见 parsing 域导读，不在本文范围。

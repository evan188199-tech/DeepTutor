# scan: 测试 skip/xfail 清点与信号遮蔽评估（AGEN-1705）

- 基线：`origin/main` @ `6cf793bd8`（release v1.6.14），只读扫描，未改任何测试或代码。
- 范围：`testpaths` 全集 = `tests/`（803 个 py 文件）+ `deeptutor/learning/tests/`（0 处跳过）。
- 手段：正则全量清点 7 类跳过语法 + 逐点 `git blame --porcelain` 出处 + 封闭 `def test_` 作用域判定 + 函数体断言检测；CI 事实取自 `.github/workflows/tests.yml` 与 `requirements/*`、`pyproject.toml` extras。
- 明细：`skip-inventory.csv`（188 行，每行一个跳过点，100% 有 reason 与 commit 出处）；校验和见 `SHA256SUMS`。

## 一、总量与结构

| 指标 | 数值 |
|---|---|
| 跳过点总数 | 188（importorskip 152、pytest.skip 25、mark.skipif 11） |
| `pytest.mark.xfail` / `pytest.xfail` | **0** |
| `expectedFailure` / `@unittest.skip*` | **0** |
| 无条件 `@pytest.mark.skip` | **0** |
| conftest `collect_ignore` / CLI 级 deselect / `-k` 过滤 | **0**（CI 为 `pytest -q tests deeptutor/learning/tests`，无过滤） |
| 被遮蔽对象为占位测试（无断言/无 raises 的空壳） | **0** —— 188 处全部守卫真测试 |
| 引入时间 | 全部 2026-04-06 ~ 2026-10-07（套件年轻，无陈年遗留） |
| 引入者 Top | Bingxi Zhao (Frank) 100、zhujia 17、Lan-zk 17、evan188199-tech 13、XZH 8 |

CI 事实（python-tests job，ubuntu-latest，Python 3.11–3.14）：只装 `requirements/server.txt + partners.txt`；`lightrag-hku` 与 `graphrag` 仅在 3.12 leg 安装；Redis 服务可用且注入 `DEEPTUTOR_TEST_REDIS_URL`；runner 预装 ffmpeg。

## 二、三态清单

### A. 可恢复（CI 全 leg 遮蔽真测试，恢复无需改测试代码）— 48 处跳过点，遮蔽约 239 个测试函数

机制：`pytest.importorskip` 守卫的可选依赖属于 `cli` / `parse-pymupdf4llm` / `math-animator` extras，但 CI python-tests 不安装它们 → 守卫在 CI 永远命中。

| 守卫依赖 | 模块级整文件跳过（测试数） | 函数级跳过（测试数） |
|---|---|---|
| pymupdf/fitz/pymupdf4llm | reading: capability 46、engine 67、page_render 6、pdf_media 3、router 44；parsing: mineru_normalization 10 | document_extractor 1、document_images 2、visual_assets 2、parsing/engines 2 |
| llama_index / faiss | llamaindex_faiss_vector_store 15 | document_loader 16、image_description 4、image_caption_cache 1 |
| anthropic | llm/anthropic_provider_fixes 17 | — |
| qrcode | — | partners/channel_onboarding 1 |
| pptx | — | reading/engine 内 1（已被模块级遮蔽包含） |
| LlamaIndex（try/except 运行时守卫） | — | tools/rag_tool 2 |
| math_animator | — | book/cross_module_call_contracts 2 |

合计：模块级 208 + 函数级 31 ≈ **239 个真测试从未在任何 CI leg 执行**。

恢复建议（按成本排序）：
1. python-tests job 追加 `pip install -e ".[cli]"`（或 `pip install -r requirements/cli.txt`）——一次性恢复 pymupdf/llamaindex/faiss/anthropic/qrcode/pptx 全部 237 个测试；
2. 追加 `pip install -e ".[math-animator]"` —— 恢复 math_animator 2 个契约测试；
3. 若担心总时长，先恢复 anthropic（17，纯 mock 不触网）与 llamaindex 两簇，pymupdf 簇放独立 leg。

### B. 待修复（需先补依赖声明或凭据基础设施）— 2 处

| 位置 | 问题 | 恢复建议 |
|---|---|---|
| `tests/reading/test_extension_router.py:265` | `importorskip("uvloop")`，但 uvloop 未出现在任何 requirements/extras —— 连本地标准安装都不含，该测试在任何受管环境都不会跑 | 先在 extras（如 dev）声明 uvloop，再由 CI 恢复 |
| `tests/services/rag/test_pipeline_integration.py:424` | 真 RAG provider 集成测试，需 `RAG_INTEGRATION_TESTS=1` + 真实 LLM/embedding 凭据，CI 永不满足 | 建夜间/手动 workflow，注入 secrets 后设该环境变量运行；勿并入普通 PR 门禁 |

### C. 可删除 — 0 处

未发现任何占位/空壳测试被 skip 掩护；也没有"测试体为 pass、仅靠 skip 维持存在"的候选。所有跳过守卫的都是有断言的真测试，删除任何一项都会损失覆盖，故此态为空。

## 三、未遮蔽（CI 不触发，属防御性/平台守卫，保留）— 138 处

- 依赖已由 server.txt/partners.txt 提供，守卫恒假：fastapi（约 26 点）、lark_oapi（约 23）、telegram（2）、croniter（3）、bcrypt（1）、loguru（1）、psutil（1）、json-repair（2）、项目内模块 notebook_router（1）。
- 平台/环境守卫，ubuntu CI 恒不触发：POSIX `os.name=="nt"` skipif（7）、symlink 不可用（约 12）、Linux-only /proc、内存后端探测（4）、pty/termios IUTF8（2）、ffmpeg 预装（1）、Redis 已配置（4）。
- graphrag/litellm/lightrag/pandas/pyarrow（33 点，约 23 个测试）：仅在 3.11/3.13/3.14 leg 跳过，3.12 专项 leg 已覆盖 —— 属有意的版本钉死，非信号损失。

## 四、对 CI 信号的真实遮蔽面评估

1. CI 表面绿 ≠ 全量通过：约 239 个真测试（主要压在 **reading 解析轴（166）、anthropic provider（17）、LlamaIndex 文档装载（20+）、FAISS 向量库（15）、MinerU 归一化（10）**）在所有 CI leg 静默 skip，回归只能靠本地 dev 安装环境发现。
2. 风险集中点：pymupdf 簇（PDF 渲染/抽取/媒体）是产品核心路径，却是 CI 最大盲区；一旦上游 PyMuPDF/llama-index 破坏 API，CI 不会先红。
3. 好消息：无 xfail/无条件 skip，无占位测试，无 CLI 级过滤 —— 不存在"假绿"机制；守卫写法规范（importorskip 带 reason 或自释模块名）。
4. 与「verify-recent-merges-tests（合并后回归轴）」去重：该卡关注合并后的回归验证；本卡只清点 skip/xfail 遮蔽面，不重叠。

## 五、复现

```bash
cd /Users/Shared/DeepTutor/dt-agen1705-skipscan-wt   # origin/main @ 6cf793bd8 worktree
rg -n '@pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail|importorskip)\(|expectedFailure|@(unittest\.)?skip' tests deeptutor/learning/tests
git blame -L <line>,<line> -- tests/<file>            # 逐点出处，见 CSV commit/date 列
sha256sum -c evidence/scan-test-skips/SHA256SUMS
```

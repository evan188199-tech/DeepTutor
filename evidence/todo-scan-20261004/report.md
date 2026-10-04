# AGEN-576 origin/main TODO/FIXME/HACK/XXX 与被注释测试全量扫描报告

- 扫描日期：2026-10-04
- 基线 commit：`f07029cfcf2c8dfccdb671cdfc343db8334f5741`（origin/main, "release: v1.6.13"）
- 工作副本：独立 worktree（`dt-agen576-scan-wt`，分支 `scan/todo-fixme-20261004`），主工作区未做任何改动，未改任何代码。

## 扫描方法

- 工具：ripgrep，大小写不敏感、整词匹配 `TODO` / `FIXME` / `HACK` / `XXX`，先限代码文件（`.py`/`.ts`/`.tsx`/`.js`/`.jsx`/`.mjs`），再扩展到全部 tracked 文件复核。
- 被注释掉的测试：正则匹配 Python `^\s*#\s*(def test_|@pytest|pytest\.|assert)`、`^\s*#\s*(def|async def|from|import|assert|await|return)`，以及 JS/TS `^\s*(//|/\*|\*)\s*(it|test|describe)\s*\(`、`//\s+(expect|assert)\s*\(`、`{/* it/test/describe(`、`xit(/xdescribe(`。
- 每条命中均逐条人工复核上下文，剔除字符串字面量、产品状态值、自然语言误报。

## 覆盖统计（git ls-files，基线 commit）

- tracked 文件总数：3599；其中 `.py` 1818、`.tsx` 638、`.ts` 599、`.yaml/.yml` 169、`.md` 153、`.mjs/.js/.cjs` 19、`.css` 4。
- 覆盖目录：`deeptutor/`、`deeptutor_cli/`、`tests/`（backend 全部）与 `web/`（frontend 全部）；不含未跟踪/构建产物（worktree 干净，无 node_modules）。

## 结论

- **真实 TODO/FIXME/HACK/XXX 任务标记：1 处**（`.pre-commit-config.yaml:111`，为有意保留的长期路线注记，不建议拆卡）。
- **被注释掉的测试：0 处**（backend 与 frontend 均未发现）。
- **可拆为补测/修复卡的线索：0 条。** 该基线不存在因注释残留产生的补测/修复需求。

## 按模块聚类条目（path:line + 评估 + 建议卡型）

### backend · 构建配置

| 位置 | 评估 | 建议卡型 |
| --- | --- | --- |
| `.pre-commit-config.yaml:111` | 唯一真实 TODO：mypy 因渐进式类型收养而放宽，标注“随类型补齐逐步收紧”；属长期路线注记而非缺陷 | 不建议建卡；若要做可挂低优 chore 卡（分目录启用 mypy 严格模式），收益低 |

### backend · tools

| 位置 | 评估 | 建议卡型 |
| --- | --- | --- |
| `deeptutor/tools/tex_downloader.py:11` | docstring “Based on: TODO.md specification” 引用的 `TODO.md` 已不在仓库 tracked 文件中，属过时文档引用 | 低优 docs 清理卡（可选，删除两处过时引用即可） |
| `deeptutor/tools/tex_chunker.py:11` | 同上，同一模板 docstring 的过时引用 | 同上，与上一条合并为一张卡 |

### backend · services

| 位置 | 评估 | 建议卡型 |
| --- | --- | --- |
| `deeptutor/services/search/source_filter.py:74` | `XXX` 为成人内容 URL 屏蔽正则中的字面量，功能本意 | 无需建卡 |
| `deeptutor/services/search/source_filter.py:75` | 同上（`.xxx` 顶级域过滤） | 无需建卡 |
| `deeptutor/services/task_board.py:17` | `'todo'` 为任务板产品状态枚举值 | 无需建卡 |
| `deeptutor/services/task_board.py:79` | 同上（DB CHECK 约束） | 无需建卡 |
| `deeptutor/services/task_board.py:104` | 同上（建卡默认状态） | 无需建卡 |
| `deeptutor/services/subagent/codex.py:294` | `todo_list` 为子代理事件类型名（产品功能） | 无需建卡 |

### backend · tests

| 位置 | 评估 | 建议卡型 |
| --- | --- | --- |
| `tests/multi_user/test_task_board.py:109` | 断言任务板 `'todo'` 状态值 | 无需建卡 |
| `tests/services/embedding/test_multimodal_request.py:77,117,147,153` | `base64,XXX` 为测试占位数据 | 无需建卡 |
| `tests/services/llm/test_llm_live.py:8` | `sk-xxx` 为用法示例占位 key | 无需建卡 |

### frontend · web

| 位置 | 评估 | 建议卡型 |
| --- | --- | --- |
| `web/app/(workspace)/kanban/page.tsx:28` | 看板列 `'todo'` 产品状态 | 无需建卡 |
| `web/tests/task-board.spec.tsx:33` | 同上（测试夹具） | 无需建卡 |
| `web/lib/task-board-api.ts:3` | `TaskStatus` 类型含 `'todo'` | 无需建卡 |
| `web/contracts/generated/api.ts:15238,15857` | 生成代码中的 `'todo'` 状态字面量 | 无需建卡 |
| `web/components/chat/home/ContextReferenceTree.tsx:31` | 注释散文 “reads as a todo checkbox”（形容 UI 隐喻） | 无需建卡 |

### docs / assets

| 位置 | 评估 | 建议卡型 |
| --- | --- | --- |
| `assets/README/README_ES.md:52,345,387,556`、`assets/README/README_PT.md:47,378` | 西/葡语 “todo”（=全部）自然语言误报 | 无需建卡 |
| `assets/releases/past_releases/ver1-1-0-beta.md:8` | 历史发布说明中的 `session=xxx` 占位示例 | 无需建卡 |

## 被注释掉的测试明细

- Python（`deeptutor/`、`deeptutor_cli/`、`tests/`）：无命中。宽松正则（含注释掉的 `def/from/import/assert/await/return`）命中的 27 行均为英文行文注释（如 “# from the persisted answer …”），非代码残留。
- JS/TSX（`web/`）：无命中。`// it(`、`{/* describe(`、`xit(`/`xdescribe(` 等模式均为 0。

## 复现命令

```
rg -n -w -i -e 'TODO' -e 'FIXME' -e 'HACK' -e 'XXX' <repo> \
  --glob '*.{py,ts,tsx,js,jsx,mjs,sh,css,html,yaml,yml,toml}'
rg -n '^\s*#\s*(def\s+test_|@pytest|pytest\.|assert\b)' <repo> --glob '*.py'
rg -n '^\s*(//|\*|/\*)\s*(it|test|describe)\s*\(|^\s*//\s*(expect|assert)\s*\(' <repo>/web
```

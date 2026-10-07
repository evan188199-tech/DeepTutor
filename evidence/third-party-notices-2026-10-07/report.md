# THIRD_PARTY_NOTICES 与实际依赖许可核对报告（2026-10-07）

## 范围与方法

- 基线：`origin/main @ f07029cfc`（release: v1.6.13）。核对在专用只读 worktree（`dt-agen1028-notices-wt`，分支 `dt-agen1028-notices`）完成，未改动任何已跟踪文件。
- Python 直接依赖 86 项：`pyproject.toml` `[project].dependencies` + `[project.optional-dependencies]` 全部 extras（codebuddy / partners / parse-* / matrix / matrix-e2e / math-animator / graphrag / rag-lightrag / rag-rerank / dev）。`requirements/` 目录为其镜像，未发现 git+URL 或直链依赖。
- Web 直接依赖 48 项：`web/package.json` dependencies 27 项 + devDependencies 21 项。
- 许可证元数据全部本地解析，未联网、未下载任何包：
  - Python：仓库 `.venv`（python3.13，605 个已安装发行版）的 `*.dist-info/METADATA`，解析优先级 **License-Expression > 短 License 字段（≤100 字符标识）> License Classifiers > License 全文**；
  - npm：`web/package-lock.json`（lockfileVersion 3）每包 `license` 字段，并用主工作区 `node_modules` 抽查 NOTICE 文件（只读）。
- 「需署名」判据（按本卡定义）：**强 copyleft**（GPL/AGPL/LGPL 系）或 **带 NOTICE 文件**。弱 copyleft（MPL 系）一并列出供参考。无本地许可证字段的记「未知」。
- 传递依赖：Python 沿已安装包的 requires 图从 86 项直接依赖 BFS 得到闭包 210 项、抽查 59 项；npm 遍历 lock 图共 979 项、抽查 60 项。抽样规则：全部非宽松许可项优先 + 按字母序补充宽松项。
- 版本漂移（scan-deps-drift）与产物卫生（scan-tracked-artifacts）不在本卡范围。

## notices 现状

`THIRD_PARTY_NOTICES.md` 仅 3 条：CSSwitch、Hermes Agent、thinking-orbs——均为代码改编/内嵌署名，**不含任何 pip/npm 包条目**。

## A. 已列入但已移除

**无（0 条）。** 3 条署名对象均仍存在：

| notices 条目 | 对应代码（仍存在） |
|---|---|
| CSSwitch（MIT） | `deeptutor/services/codex_auth/`（Codex OAuth） |
| Hermes Agent（MIT） | `deeptutor/services/partners/`（通道 onboarding、QR/设备码流程） |
| thinking-orbs（MIT） | `web/vendor/thinking-orbs/`（内嵌源码 + LICENSE） |

## B. 未列入 notices 的需署名直接依赖（6 条）

| # | 包 | 生态 | 声明位置 | 许可证 | 许可证来源依据 | 类型 |
|---|---|---|---|---|---|---|
| B1 | pymupdf | python | dependencies | AGPL-3.0 或 Artifex 商业双许可 | `.venv` 1.28.2 METADATA License 字段 "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License" | 强 copyleft |
| B2 | pyte | python | dependencies | LGPL-3.0 | `.venv` 0.8.2 METADATA Classifiers "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)" | 强 copyleft |
| B3 | python-telegram-bot | python | extra: partners | LGPL-3.0-only | `.venv` 22.8 METADATA License-Expression "LGPL-3.0-only" | 强 copyleft |
| B4 | dashscope | python | dependencies | Apache-2.0（带 NOTICE） | `.venv` 1.27.1 METADATA License 字段 "Apache 2.0"；License-File 含 `NOTICE` | 带 NOTICE |
| B5 | requests | python | dependencies | Apache-2.0（带 NOTICE） | `.venv` 2.34.2 METADATA License 字段 "Apache-2.0"；License-File 含 `NOTICE` | 带 NOTICE |
| B6 | qq-botpy | python | extra: partners | License 字段 "Tencent"（自定义），同包 Classifiers 标 MIT | `.venv` 1.2.1 METADATA | 自定义许可，待人工确认 |

说明：
- B1（PyMuPDF/AGPL）为本表最重要条目：以 AGPL 分发会触发强 copyleft 义务，或需商业授权；建议在 notices 或文档中至少说明所选授权路线。
- B4/B5 依据 Apache-2.0 第 4(d) 条：再分发时若上游含 NOTICE 文件需保留其内容归属。
- B6 的 QQ 开放平台 SDK 许可字段与 classifier 不一致，需人工到上游确认后决定署名方式。

## C. 传递依赖抽查命中（59+60 条抽查中 8 条，其中 1 条待确认）

| # | 包 | 生态/引入链 | 许可证 | 许可证来源依据 | 类型 |
|---|---|---|---|---|---|
| C1 | @img/sharp-libvips-*（darwin/linux/linuxmusl 共 10 个平台变体） | npm transitive（sharp 平台二进制） | LGPL-3.0-or-later | `web/package-lock.json` license 字段 | 强 copyleft（按目标平台随构建分发时触发） |
| C2 | @img/sharp-win32-*、@img/sharp-wasm32（4 个变体，Apache-2.0 AND LGPL-3.0-or-later [AND MIT]） | npm transitive（sharp 平台二进制） | 含 LGPL-3.0-or-later 分支 | `web/package-lock.json` license 字段 | 强 copyleft（同上） |
| C3 | pycairo | python transitive（manim → pycairo） | LGPL-2.1-only OR MPL-1.1 | `.venv` 1.29.1 METADATA License 字段 | 强/弱 copyleft |
| C4 | bidict | python transitive | MPL-2.0 | `.venv` 0.23.1 METADATA License 字段 "MPL 2.0" | 弱 copyleft |
| C5 | certifi | python transitive | MPL-2.0 | `.venv` 2026.7.22 METADATA License 字段 "MPL-2.0" | 弱 copyleft |
| C6 | orjson | python transitive | MPL-2.0 AND (Apache-2.0 OR MIT) | `.venv` 3.11.9 METADATA License-Expression | 弱 copyleft |
| C7 | tqdm | python transitive | MPL-2.0 AND MIT | `.venv` 4.70.0 METADATA License-Expression | 弱 copyleft |
| C8 | python-dateutil | python transitive | 字段仅 "Dual License"；Classifiers: BSD + Apache | `.venv` 2.9.0.post0 METADATA | 字段含糊待确认（上游实为 BSD-3/Apache-2.0 双宽松许可） |

## D. 未知清单（直接依赖 11 条，均为 Python 可选 extras）

`codebuddy-agent-sdk`、`docling`、`docling-slim`、`lightrag-hku`、`liteparse`、`matrix-nio`、`mistune`、`nh3`、`pymupdf4llm`、`redis`、`sentence-transformers`

- 原因：`.venv` 未安装这些 extras 对应发行版，本机 pip 缓存为空，本卡禁止联网取回，故按规则记「未知」。
- npm 直接依赖 48 项 lock 内均有 license 字段，**0 未知**；两侧传递依赖抽查 **0 未知**。

## E. 参考（不构成本卡判据下的差异）

- Apache-2.0 且无 NOTICE 的直接依赖（保留 LICENSE 即可，无需署名条目）：aiohttp、bandit、bcrypt、msgpack、openai、perplexityai、pytest-asyncio、python-multipart、python-socks、tenacity、websocket-client、zulip；npm 侧 docx-preview、pdfjs-dist、@playwright/test、typescript。npm 48 项直接依赖均未检出 NOTICE 文件。
- `edge-tts`（LGPLv3）存在于 `.venv` 但不在 86 项直接依赖的 requires 闭包内，代码亦未 import、requirements 未声明——属未声明依赖问题，不在本卡范围（版本漂移/依赖卫生轴另行处理）。
- MIT/BSD/ISC/PSF/CC0 等宽松许可直接依赖：python 57 项、npm 44 项，无署名义务，明细见 `deps_licenses.csv`。

## 计数汇总（供完成评论）

- 新增（需署名、未列入 notices）：直接依赖 6 条（B1–B6，其中 B6 待确认）＋传递抽查 8 条（C1–C8，其中 C8 待确认）
- 移除（已列入但已移除）：0 条
- 未知：直接依赖 11 条（Python extras）；npm 直接依赖 0；传递抽查 0

## 复核方式

- 差异全表机器可读版：`deps_licenses.csv`（253 行：python 86 + npm 48 + npm-transitive 60 + python-transitive 59，另 1 行表头）。
- 本目录 `SHA256SUMS` 覆盖本报告与 CSV。

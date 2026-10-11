# chore-deps-prune-unused：B 类声明未用依赖逐条处置结论（AGEN-1739，只读分诊 + 草稿）

- 基线：origin/main `6cf793bd8`（v1.6.14）。输入：myfork/scan/python-deps-drift-20261011 §02（B 类）。
- 结论概览：**B1/B2/B3/B5/B7/B9 建议移除**（最小 diff 草稿 `remove-draft.diff`，−19 行，未改任何声明文件）；**B4/B8 注记保留**（消费链在自有代码之外，删除破坏功能或丢失锚点）。
- 去重边界：B6 perplexityai 归 `fix-deps-perplexity-import`（分支 `myfork/fix/deps-perplexity-import-20261011`，改 pyproject:54 一带，与本草稿不同行）；A 类补声明归 `chore-deps-transitive-declare`；发现轴归 `scan-python-deps-drift`。上游 HKUDS/DeepTutor 无同主题开放 PR/issue（gh 检索 2026-10-11）。

## 1. 逐条结论（B1–B9，不含 B6）

| # | 包 | 声明面（origin/main 行号） | 结论 | 兼容论证 |
|---|---|---|---|---|
| B1 | nest_asyncio | core pyproject:29；requirements/cli.txt:31；packaging/deeptutor-cli/pyproject.toml:23 | 移除 | 全代码 0 import（graphrag 引擎注释提的 `nest_asyncio2` 是另一发行包，engine.py:115）；llama-index-core 硬依赖 `nest-asyncio<2,>=1.5.8`，而 llama-index 在所有安装面均为硬依赖（pyproject:56/:120、packaging:48），移除后包仍在场 |
| B2 | tenacity | core pyproject:30；cli.txt:32；packaging:24 | 移除 | 0 import；llama-index-core 硬依赖 `tenacity!=8.4.0,<10,>=8.2.0`、dashscope 亦硬依赖，两者均为全安装面硬依赖；原下界 `>=8.0.0` 宽于传递约束，移除无约束损失 |
| B3 | prompt_toolkit | core pyproject:38；cli.txt:72；packaging:32 | 移除 | 0 import，终端抓取用 pyte（pyproject:39 注释自证）；dashscope 硬依赖 `prompt-toolkit>=3.0` 且 dashscope 全安装面在场（pyproject:53/:115、packaging:45） |
| B4 | pdfplumber | core pyproject:75；cli extra pyproject:137；cli.txt:61；packaging:65；Dockerfile.runner:70 | **注记保留** | 自身 0 import，但 builtin pdf skill（deeptutor/skills/builtin/pdf/SKILL.md:17,31）指示模型在 exec 沙箱运行 `import pdfplumber`；本地沙箱后端（Bwrap/受限子进程，backends.py:139/:286）以宿主 env 的 `python3` 执行（exec_tool.py:107-125）→ 本声明即本地模式 skill 承诺的兑现；Docker 侧 runner 镜像独立安装并注明与 SKILL.md 同步（Dockerfile.runner:55-71）；test_packaging_metadata.py:197 在全部安装面断言其存在。解析层（services/parsing/engines/）确无 pdfplumber 引擎，消费面纯属 skill——按任务要求复核后结论：不动 |
| B5 | oauth-cli-kit | core pyproject:55；cli extra pyproject:117；cli.txt:23（含 py>=3.11 marker）；packaging:47 | 移除 | 0 import 且三处测试护栏固化"不再使用"：test_openai_codex_oauth_provider.py:297（源码不含 oauth_cli_kit）、test_provider_cli.py:78（命令表不含）、test_github_copilot_auth.py:120（毒化 oauth_cli_kit.storage 断言永不实例化）；Codex/GitHub Copilot OAuth 已原生重写（deeptutor/services/codex_auth、github_copilot_storage） |
| B7 | python-socks[asyncio] | partners pyproject:193；partners.txt:27 | 移除 | 0 import 且 partners 闭包内无消费者：telegram 代理走 PTB[socks]→httpx[socks]→**socksio**（与本品无关）；唯一反向引用来自 websocket-client 的 optional extra（默认不装、且 B9 一并移除）；系 bulk 提交 162a3f9dc 无说明加入 |
| B8 | socksio | partners pyproject:194；partners.txt:28 | **注记保留** | 0 直接 import，属"框架消费型"（与 02 报告 python-multipart 注记同型）：telegram 频道 `proxy` 为 socks5:// 时（telegram.py:259,347-364）由 httpx 运行时加载；当前经 PTB[socks]（pyproject:184）→httpx[socks]→`socksio==1.*` 传递满足，直接 pin 保留功能锚点并防 extra 链被误删。若维护者倾向纯传递亦可移除（传递链已在声明面显式化），风险等价 |
| B9 | websocket-client | partners pyproject:195；partners.txt:29 | 移除 | 0 import；各通道实际用异步库：napcat→websockets.asyncio（napcat.py:24-25）、slack→slack_sdk socket_mode.websockets（slack.py:11）、mochat→socketio.AsyncClient（mochat.py:442）；python-socketio/engineio/slack-sdk 仅 client/optional extra 下引用本包；且 dashscope 硬依赖 websocket-client（core 面），移除后仍随装，partners 面零运行变化 |

## 2. 复现命令（在 6cf793bd8 干净检出上执行，全部只读）

```bash
# (1) import 面扫描：8 个模块名均 0 命中（websocket 为 websocket-client 根模块名，\b 排除 websockets）
for m in nest_asyncio tenacity prompt_toolkit pdfplumber oauth_cli_kit python_socks socksio websocket; do
  rg -n "(^|[^A-Za-z0-9_.])(import|from)[[:space:]]+${m}\b" deeptutor deeptutor_cli deeptutor_web tests examples scripts docs; done
# pdfplumber 仅 deeptutor/skills/builtin/pdf/SKILL.md:31,44,232 文档样例命中（skill 生成代码消费面，见 B4）
# (2) 声明面定位
rg -n "nest.asyncio|tenacity|prompt.toolkit|pdfplumber|oauth.cli.kit|python.socks|socksio|websocket.client" pyproject.toml requirements/ packaging/ Dockerfile.runner
# (3) 传递依赖元数据（.venv 只读实测：llama-index-core 0.14.19 / dashscope 1.27.1 / graphrag-llm 3.1.1 / PTB 22.8 / httpx 0.28.1）
python -c "from importlib.metadata import requires as r; [print(n, [x for x in r(n) if any(t in x.lower() for t in ('nest','tenacity','socks','websocket','prompt'))]) for n in ('llama-index-core','dashscope','graphrag-llm','python-telegram-bot','httpx')]"
# (4) 草稿可应用性（干净检出上）
git apply --check evidence/chore-deps-prune-unused/remove-draft.diff
```

## 3. 传递约束对比（.venv 实测 2026-10-11）

| 包 | DeepTutor 声明 | 传递供给（硬依赖，全安装面在场） |
|---|---|---|
| nest-asyncio | `>=1.5.8` 无上界 | llama-index-core：`<2,>=1.5.8` |
| tenacity | `>=8.0.0` 无上界 | llama-index-core：`!=8.4.0,<10,>=8.2.0`；dashscope：无界 |
| prompt-toolkit | `>=3.0.36` | dashscope：`>=3.0` |
| websocket-client | `>=1.9.0,<2`（仅 partners） | dashscope：无界（core 面，恒在场） |

## 4. 移除草稿（remove-draft.diff，仅草稿、未落盘）

- 4 文件 −19 行：pyproject.toml −7、requirements/cli.txt −6（含 "Async helpers" 空节头一并删除）、requirements/partners.txt −2、packaging/deeptutor-cli/pyproject.toml −4；pdfplumber/socksio 行未动。
- 已验证：`git apply --check` 通过；应用后两个 pyproject TOML 解析正常、cli extra 与 partners extra 逐项核对无误；test_packaging_metadata.py 参数表（packaging/loguru/json-repair/pyte/pdfplumber/reportlab）不含被删项，无需测试改动；B5 三处护栏测试保留原样。
- 注记保留项注释建议（供人采纳）：B4 置 pyproject:75 处 — `# No direct import: the builtin pdf skill (deeptutor/skills/builtin/pdf) runs \`import pdfplumber\` in the exec sandbox; local sandbox backends resolve that against this install. Keep in sync with Dockerfile.runner.`；B8 置 pyproject:194 处 — `# No direct import: httpx loads socksio at runtime for socks5:// proxies (Telegram channel \`proxy\`), via python-telegram-bot[socks].`

## 5. 协调点与残余风险

- 与 fix-deps-perplexity-import（改 pyproject:54 perplexityai 行）不同行，仅行邻接；与 chore-deps-transitive-declare（core 列表加行）互不重叠，后合方 rebase 即可。
- wheel 元数据变化：deeptutor/deeptutor-cli Requires-Dist 减 4 项（B1/B2/B3/B5），运行面不变（均经 llama-index-core/dashscope 传递在场）；partners 减 python-socks/websocket-client，telegram socks5 代理不受影响（socksio 保留 + PTB[socks] 链）。
- 残余风险：上游 llama-index 若未来撤掉 nest-asyncio/tenacity 硬依赖，包将从安装面消失——届时 DeepTutor 自身仍 0 import，无破坏；dashscope 同理（B3/B9）。requirements/cli.txt 的 `oauth-cli-kit; python_version >= "3.11"` marker 随行删除，packaging requires-python `>=3.11` 不受影响。

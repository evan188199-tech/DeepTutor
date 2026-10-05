# Capability prompts en/zh 对齐清点（capability prompts en/zh alignment audit）

- 日期：2026-10-05
- 审计对象：HKUDS/DeepTutor @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（origin/main，release v1.6.13）
- 性质：只读清点，未改动任何产品代码
- 基线来源：`tests/capabilities/test_status_i18n_consistency.py`（visualize status 包的三条 parity 检查），本卡将其口径推广到 capability prompt 文件层

## 1. 范围与去重

- **本卡范围**：`deeptutor/capabilities/**/prompts/{en,zh}/`（12 个 capability 本地目录 + 1 个共享目录 `deeptutor/capabilities/prompts/`，后者承载 audio_overview 的 prompt 包），共 26 个文件。
- **去重**：web 层 UI 文案（`deeptutor_web/`、`web/`）归 scan-i18n 卡；目录结构导读归 guide-capabilities 卡。本卡不重复覆盖。
- 无 prompts 目录的 capability：`subagent`（内置默认指令，无语言文件）、`watching`（复用宿主回路，无自有 prompt 文件）、`audio_overview`（prompt 包在共享目录，已覆盖）。

## 2. 复现口径（reproducible）

```bash
git checkout <f07029cfcf2c8dfccdb671cdfc343db8334f5741>
python3 evidence/capability-prompts-20261005/audit_capability_prompts.py \
    --repo . --commit f07029cfcf2c8dfccdb671cdfc343db8334f5741 \
    --out evidence/capability-prompts-20261005
```

脚本依赖仅 stdlib + PyYAML；输出 `findings.json` 与 `SHA256SUMS`（本目录）。检查维度：

| 代号 | 检查 | 分级规则 |
|---|---|---|
| E1 | en/zh 文件集合 parity | 缺文件 P1 |
| Y1 | YAML 键树 parity（嵌套路径，双向） | 缺 zh P1 / 仅 zh P2 |
| Y2 | YAML 值类型漂移（str vs mapping） | P2 |
| Y3 | YAML 空串值（单侧） | P2 |
| PH | `{placeholder}` 占位符 parity（YAML 逐键 + md 逐文件） | 仅 en 有 P1 / 仅 zh 有 P2 |
| M1 | md 标题结构漂移（数量/层级序列，不比译文文字） | P2 |
| M2 | md 列表项/围栏块数量漂移 | 列表 P3 / 围栏 P2 |
| M3 | md 字符长度比 zh/en 出界 [0.2, 4.0] | P3（信息性） |
| L1 | 加载器期望文件缺失 | resources.md 类 P1 / PromptManager 类 P2（整包回退 en） |
| C1 | 代码引用键路径在 en/zh yaml 缺失 | 有 default= 兜底 P2，无则 P1 |
| C2 | yaml 键从未被代码引用（死文案启发式） | P3 |

C1/C2 识别的代码引用模式：`_t("a.b")`、`_t(f"session.{kind}")` 前缀派发、`prompt_text(prompts, ("a","b"))`、`pack.get("x")`、`get_prompt(p, "sec", "field")`、`StatusI18n` 的 `i18n.t("key")` → `status.key`；mastery 作为 loop-pipeline 包还并入共享装配器 `deeptutor/agents/loop/prompt_blocks.py` 的键，并按 `deep_merge(agentic_chat, mastery_loop)` 的生效包校验（`PromptManager` + `pipeline._load_prompt_pack` 语义）。

## 3. 逐 capability 对照表

加载器依据（代码引用）：`resources.files(__package__).joinpath("prompts", lang, …)` 型 —— solve `loop.py:79`、ask_questions `loop.py:49`、ima `capability.py:88`、marginnote4 `capability.py:76`、obsidian `capability.py:78`、setup `capability.py:104`、partner_authoring `capability.py:38`（system.md/heuristic.md）、partner_group `capability.py:51,59-61`（system.md/invoke_other.md）、course_study `capability.py:65`、explore_context `capability.py:56`、reading `capability.py:84`；PromptManager 型 —— mastery `loop.py:543`、tools.py:586（module="mastery" → `capabilities/mastery/prompts/<lang>/mastery_loop.yaml`，zh→cn→en 回退）、audio_overview `capability.py:61`（module="capabilities" → 共享目录）。

| capability | 目录 | en 文件 | zh 文件 | yaml 键数 en=zh | 加载器 | 结论 |
|---|---|---|---|---|---|---|
| ask_questions | `deeptutor/capabilities/ask_questions/prompts/` | system.md | system.md | — | resources md（lang 二值 zh/en） | 通过 |
| course_study | `deeptutor/capabilities/course_study/prompts/` | course_study.yaml | course_study.yaml | 3=3 | resources yaml（异常→空包+warn） | 通过 |
| explore_context | `deeptutor/capabilities/explore_context/prompts/` | explore_context.yaml | explore_context.yaml | 10=10 | resources yaml | **1 项 P2**（§4） |
| ima | `deeptutor/capabilities/ima/prompts/` | system.md | system.md | — | resources md | 通过 |
| marginnote4 | `deeptutor/capabilities/marginnote4/prompts/` | system.md | system.md | — | resources md | 通过 |
| mastery | `deeptutor/capabilities/mastery/prompts/` | mastery_loop.yaml | mastery_loop.yaml | 12=12 | PromptManager（zh→cn→en 整包回退） | **1 项 P3**（§4） |
| obsidian | `deeptutor/capabilities/obsidian/prompts/` | system.md | system.md | — | resources md | 通过 |
| partner_authoring | `deeptutor/capabilities/partner_authoring/prompts/` | system.md, heuristic.md | system.md, heuristic.md | — | resources md | 通过 |
| partner_group | `deeptutor/capabilities/partner_group/prompts/` | system.md, invoke_other.md | system.md, invoke_other.md | — | resources md | 通过 |
| reading | `deeptutor/capabilities/reading/prompts/` | reading.yaml | reading.yaml | 5=5 | resources yaml | 通过 |
| setup | `deeptutor/capabilities/setup/prompts/` | system.md | system.md | — | resources md | 通过 |
| solve | `deeptutor/capabilities/solve/prompts/` | system.md | system.md | — | resources md | 通过 |
| audio_overview（共享目录） | `deeptutor/capabilities/prompts/` | audio_overview.yaml | audio_overview.yaml | 5=5 | PromptManager | 通过 |

md 字符长度比（zh/en，信息性，均在正常汉化密度区间）：solve 0.38、setup 0.39、ask_questions 0.34、ima 0.40、marginnote4 0.45、obsidian 0.52、partner_authoring system 0.36 / heuristic 0.42、partner_group system 0.39 / invoke_other 0.36。全部 md 的标题数量与层级、列表项数、围栏块数、占位符集合 en/zh 完全一致。

## 4. 发现清单（风险分级）

| 级别 | 类型 | 路径 | 说明 |
|---|---|---|---|
| P2 | C1 | `deeptutor/capabilities/explore_context/prompts/{en,zh}/explore_context.yaml` | `explorer.py:296` 以 `self._t("labels.tool_call", default="Tool call")` 引用 `labels.tool_call`，但该 yaml（en、zh 皆无 `labels` 段）不提供此键：zh 用户在上下文调查的工具调用状态标签处静默看到英文 "Tool call"。与 `test_status_i18n_consistency.py` 防的同型漂移（yaml 滞后于代码）。修法：en/zh 各补 `labels: {tool_call: …}`，或删掉该 lookup 直接用常量。 |
| P3 | C1 | `deeptutor/capabilities/mastery/prompts/mastery_loop.yaml` | `loop.py:236` 的 `_prompt_text(prompts, ("mastery", "system"))` 是宿主包覆盖钩子：`agentic_chat.yaml` 与 `mastery_loop.yaml` 均无顶层 `mastery` 键（已逐一核对），lookup 恒空并总是回退 `_load_playbook(language)`（en/zh 均正常）。运行无害，但属于永不生效的死钩子，易误导后续改动；建议删除或补文档。 |

未发现的问题（同样是结论）：无缺失语言文件（E1=0）；5 个 YAML 包键树 en/zh 完全一致、无类型漂移、无空串值（Y1/Y2/Y3=0）；全部 `{placeholder}`（question/mode/manifest/user_message/unit/unit_count/tool_call_limit/summary/sources/course_id/annotations/vault_name/library_name/kb_names）en/zh 成对且均被代码消费（`str.format` 或 `.replace`）（PH=0）；加载器期望文件全部存在（L1=0）。

## 5. 可拆卡建议

1. **fix-capability-i18n-labels（小卡）**：为 explore_context 补 `labels.tool_call` 的 en/zh 文案（或在 `explorer.py:296` 改为带 zh 分支的 default），并顺手把 `test_status_i18n_consistency.py` 的三检查参数化到 explore_context 包（其 status 段已是同布局）。
2. **chore-mastery-dead-hook（微卡）**：删除 mastery `loop.py:236` 的 dormant 覆盖钩子（或在 `protocol.py` 文档中写明 `system_block(prompts=…)` 的覆盖语义），避免下一个能力复制这个永不生效的模式。
3. **test-capability-prompts-parity（测试卡）**：把本卡脚本的 E1/Y1/Y2/Y3/PH 五个纯 parity 检查参数化成 pytest（放到 `tests/capabilities/`，口径与本脚本一致），把"yaml 滞后于代码"的回归防线从 visualize 扩到全部 capability 包；C1/C2 因需解析加载语义，建议维持 evidence 脚本形态人工复核。

## 6. 证据完整性

- `SHA256SUMS`：26 个被审计 prompt 文件的 SHA-256（审计对象锚点）。
- `findings.json`：机器可读结果（含 per-file md 长度比、全部 findings），SHA-256 `0bd40bbd418e726592433b5a649b06db27b1e15de44bd4fa80d0a7a778708a2b`。
- `audit_capability_prompts.py`：审计脚本（仅读仓库，仅写本目录），SHA-256 `52558af483027b295c1244a7ed48912c4b309ded58cc55576df731371dbadfc7`。

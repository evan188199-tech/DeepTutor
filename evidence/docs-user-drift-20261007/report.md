# docs-for-user 文档漂移扫描报告（docs user drift scan）

- 日期：2026-10-07
- 基线：`origin/main` @ `f07029cfc`（release: v1.6.13），权威版本号 `deeptutor/__version__.py` = `1.6.13`（`pyproject.toml:303` 动态读取）
- 范围：`docs-for-user/` 全部 12 个 `.md` + 根目录 7 个 `.md`（AGENTS / CODE_OF_CONDUCT / CONTRIBUTING / Communication / README / SKILL / THIRD_PARTY_NOTICES），共 19 个文件
- 方法：脚本扫描全部 markdown 内联/引用式链接（含同页与跨文件锚点、GitHub slug 规则）、HTML `src/href`（含 percent-decoding 复核）、反引号路径类引用（逐条人工裁定，剔除运行时路径与 UI 路由）、版本号字符串（对照权威版本；README 发布历史区块视为历史记录）。全部结论经人工逐条复核。
- 对照输入：issue 所附 guide-scope 基线备注（`evidence/guide-scope-20261007/` 在本地与全部 git 历史中均未找到，按卡面描述作为文字基线使用；其两条注记已在下文逐一验证）。

## 结论汇总

- 需修复：6 项（1 断链锚点、2 缺失文件引用、1 私有路径残留、2 版本声明过期，其中 1 项为可选）
- 已由上游开放 PR 覆盖：2 项（AGENTS.md 两条路径，PR #1155）
- 验证为无漂移：9 项（逐项见下）
- 本报告只记录结论与修复方向，未改动任何代码或文档。

## A. 断链（链接 / 锚点）

| # | 位置 | 漂移类型 | 发现 | 结论 | 修复方向（不实施） |
|---|------|----------|------|------|--------------------|
| A1 | `CONTRIBUTING.md:15` | 断链-锚点 | TOC 链接 `[Maintainers](#maintainers)`，但正文标题为 `## Maintainer`（:26，slug `maintainer`） | 确认断链 | 把 TOC 链接改为 `#maintainer`（或把标题改为复数保持一致） |
| A2 | `README.md:41` | 断链-锚点（候选） | `#%EF%B8%8F-deeptutor-cli--agent-native-interface` 含 URL 编码的变体选择符（U+FE0F） | 无漂移：对应标题 `## ⌨️ DeepTutor CLI — Agent-Native Interface`（README.md:937）存在，该形式是 GitHub 生成的合法锚点 | 无需处理 |

其余 156 条内部链接（含 `./docs-for-user/REASONING_SAFETY_CHECKLIST.md` 等）与 13 条 HTML 图片引用（percent-decoding 后逐一存在）全部解析成功，无断链。

## B. 被引用文件存在性

| # | 位置 | 漂移类型 | 发现 | 结论 | 修复方向（不实施） |
|---|------|----------|------|------|--------------------|
| B1 | `AGENTS.md:84` | 缺失文件引用 | `deeptutor/capabilities/_shared.py` 不存在；`deeptutor/capabilities/` 下无 `_shared.py` | 确认漂移 | 已被上游开放 PR #1155 覆盖（改为 `deeptutor/agents/_shared/capability_result.py`，该文件存在），跟随其合并即可 |
| B2 | `AGENTS.md:131` | 缺失文件引用 | `deeptutor/app.py` 不存在；`DeepTutorApp` 现位于 `deeptutor/app/facade.py:60` | 确认漂移 | 已被上游 PR #1155 覆盖（改为 `deeptutor/app/facade.py`），跟随其合并即可 |
| B3 | `AGENTS.md:124` | 缺失文件引用（候选） | `registry.py`、`models.py`（`deeptutor/services/subagent/` 语境） | 无漂移：两文件均存在于 `deeptutor/services/subagent/` | 无需处理 |
| B4 | `README.md:708` | 缺失文件引用（候选） | 反引号提及 `SOUL.md` | 无漂移：partner 工作区运行时生成的文件，非仓库文件 | 无需处理 |
| B5 | `THIRD_PARTY_NOTICES.md:79` | 缺失文件引用（候选） | `packages/thinking-orbs` | 无漂移：第三方上游项目（Jakubantalik/Libraries）内的路径，属来源出处说明 | 无需处理 |
| B6 | `docs-for-user/workspace-isolation-implementation.md:88` | 私有路径残留 | 出现作者本机绝对路径 `/Users/frank/HKUDS/DeepTutor-backups/workspace-isolation-20260919-023534/` | 确认漂移：读者环境永不存在的机器专属路径 | 改写为中性描述（如"本地全量备份经 SHA-256 与 tar 清单校验"），删除绝对路径 |
| B7 | 根目录旧文档 | 移除/迁移后残留引用 | `DEVELOPMENT_WORKFLOW.md`、`LOCAL_FEATURES.md`、`UI_SCREENSHOT_REFRESH.md` 在 origin/main 已不存在；CONTAINERIZATION / KNOWLEDGE_MIGRATION / READING_EXTENSIONS / REASONING_SAFETY_CHECKLIST 已移入 `docs-for-user/` | 与 guide-scope 基线注记一致；全仓（md/py/yml/json/toml）grep 无任何指向旧根路径的残留引用，README 的 `./docs-for-user/…` 链接可解析 | 无需处理（基线验证通过） |

## C. 版本声明漂移

| # | 位置 | 漂移类型 | 发现 | 结论 | 修复方向（不实施） |
|---|------|----------|------|------|--------------------|
| C1 | `README.md:222` | 版本声明 | "✨ **v1.6.13 is live.**" 及 `README.md:51` 最新发布条目 v1.6.13 | 无漂移：与权威版本 `deeptutor/__version__.py` 一致 | 无需处理 |
| C2 | `README.md:661` | 过期版本声明 | "The overview is current for v1.6.5. The surface screenshots below remain v1.4.6 references while a versioned refresh is in progress."；产品已到 v1.6.13，且追踪用的 `UI_SCREENSHOT_REFRESH.md` 已从仓库移除 | 确认过期：现势性声明落后 8 个 minor 版本，且"in progress"对应的追踪文档已不存在 | 刷新截图，或改写状态注记（去掉"current for v1.6.5/in progress"措辞，改为"示意用法"类中性描述） |
| C3 | `docs-for-user/KNOWLEDGE_MIGRATION.md:4` | 过期版本声明 | "It matches the v1.6.0 Knowledge Center."，产品现为 v1.6.13 | 确认过期（现势性声明钉在 v1.6.0） | 对照当前 Knowledge Center 版面复核后更新版本戳，或改写为历史基线表述 |
| C4 | `CITATION.cff` | 版本声明缺失 | 仅有 `cff-version: 1.2.0`（规范版本），无产品 `version:` / `date-released` 字段 | 轻微漂移（可选修复）：引用元数据不随发布更新 | 增加 `version: 1.6.13` 与 `date-released`，并入发布流程同步 |
| C5 | `README.md:397` | 版本声明（候选） | ghcr 标签示例 `:1.6.3` | 无漂移：明示为示例（"for example"），非现势声明 | 无需处理 |

## 口径说明（scope notes）

- README 发布历史区块（约 :40–:218 的 v0.2.0–v1.6.13 条目）按历史记录处理，不作为现势声明；全部为 GitHub releases 外链。
- 反引号路径类引用中，`/app/data`、`data/user/settings/*.json`、`/api/*`、`/ws/*`、`/watching`、`/quit` 等 UI 路由与运行时路径为运行期产物说明，不属于仓库文件引用，未计入漂移；疑似仓库路径的候选已全部逐条裁定（见 B 节）。
- 外部 URL（img.shields.io、github.com 等）不做网络可达性验证，不在本次三类漂移范围内。
- 扫描基线为 fetch 后的 `origin/main`（f07029cfc）；`/Users/Shared/DeepTutor` 主工作区保持只读，未 checkout/reset/clean，未触碰未提交内容。

## 复现

```bash
cd /Users/Shared/DeepTutor
git fetch origin main
git worktree add -b scan/docs-user-drift-20261007 <wt-path> origin/main
# 链接/引用/版本三层扫描 + 人工逐条复核（脚本与过程记录见运行工作区，结论以本报告为准）
```

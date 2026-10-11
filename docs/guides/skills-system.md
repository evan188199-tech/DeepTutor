# DeepTutor 技能体系导读（`services/skill` 与 builtin 技能面）

- 基线：origin/main @ `6cf793bd8`（v1.6.14）。
- 范围：`deeptutor/services/skill/`（`service` / `runtime` / `taxonomy` / `hub` / `credentials`）+ `deeptutor/skills/builtin/` 内容面，以及"技能如何被加载、被模型看见、被 `read_skill` 拉取"的完整链路。
- 锚点形如 `path:line`，相对仓库根。
- 去重声明：router/frontmatter/taxonomy/builtin 的测试工作只在 §8 引用既有分支与文件，不在本文展开。

## 1. 这一层是什么

技能（skill）= 一个自包含的能力包：`SKILL.md`（YAML frontmatter + markdown 剧本）加可选 `references/`。它**从不整篇注入系统提示**——提示里只有一行一条的清单（manifest），模型判断任务匹配后再用 `read_skill` 工具按需拉全文（渐进披露）；唯一例外是 frontmatter 标了 `always: true` 的技能，全文急切注入（`deeptutor/services/skill/service.py:8`-14）。

四个角色文件：

| 文件 | 职责 | 一句话链路 |
|---|---|---|
| `service.py` | SKILL.md 包的 CRUD + 解析 + 可用性门禁 + manifest 渲染 | 双层（user 遮蔽 builtin），见 §2 |
| `runtime.py` | 一条唯一的解析顺序：多来源合成运行时技能表与 manifest | 见 §3 |
| `taxonomy.py` | EduHub 发布用分类常量（track + facets），镜像 web 表单 | 只服务发布/更新，见 §4 |
| `hub.py` | 外部技能仓（eduhub/clawhub/自定义命令仓）的导入与发布 | verify→fetch→install，见 §6 |
| `credentials.py` | hub 发布令牌的本地存储（0600） | 见 §5 |

内容面：`deeptutor/skills/builtin/`（`deeptutor/services/skill/service.py:72` `BUILTIN_SKILLS_ROOT`）现含 5 个包：`docx` / `pdf` / `pptx` / `xlsx` / `skill-creator`，每个只有一份 `SKILL.md`。产品 chat 与伙伴（partner）工作区共用这**同一套** builtin（`deeptutor/services/skill/service.py:69`-71）。行为/语气预设（teacher、peer…）不是技能，走 `deeptutor/services/persona`（`deeptutor/services/skill/service.py:44`-46）。

## 2. 技能包形态与 frontmatter

frontmatter 契约（`deeptutor/services/skill/service.py:27`-38）：

```yaml
---
name: my-skill            # 必须匹配 ^[a-z0-9][a-z0-9-]{0,63}$（service.py:64）
description: 一句话摘要    # manifest 里模型唯一可见的"何时用我"信号
tags: [style]             # 可选；仅用户侧组织，不参与运行时匹配
always: false             # 可选；true = 全文急切注入（家规类）
requires:                 # 可选；可用性门禁（service.py:370-394 逐项检查）
  bins: [git]             #   PATH 上必须有该 CLI
  env: [GITHUB_TOKEN]     #   环境变量必须已设置
  sandbox: shell          #   执行沙箱必须具备该能力（service.py:205-216，fail-closed）
---
```

- 内置包实例：office 三件套 + xlsx 都声明 `requires: sandbox: shell`（如 `deeptutor/skills/builtin/docx/SKILL.md:11`-12），缺沙箱时它们在 manifest 中标为 unavailable 而不是消失（`deeptutor/services/skill/service.py:1010`-1012）。
- user 层还可带两个旁车文件：`.tags.json`（用户管理的标签词表，`deeptutor/services/skill/service.py:40`-42、`284`-346）与 `.hub-lock.json`（导入来源账本，`deeptutor/services/skill/service.py:78`-81、`806`-851）。
- 目录名即 slug：`_load_info` 用 `skill_dir.name` 当技能名（`deeptutor/services/skill/service.py:404`），所以**改目录名 = 改技能名**；frontmatter 里的 `name:` 只在导入/重写时被对齐到 slug（`deeptutor/services/skill/service.py:613`、`755`）。

## 3. 加载链路：从磁盘到系统提示

每轮构建提示时走这条链（product chat）：

```
磁盘（每层一个 SkillService）
  workspace 绑定   runtime.py:17-21   （builtin_root=None，纯工作区层）
  账号层           runtime.py:32-33   （get_skill_service()，partner 走独立根 service.py:1037-1050）
  admin 授予层     runtime.py:34-41   （仅非管理员且 grant 列了该技能，skill_access.py:13-20）
  builtin          runtime.py:43-44   （永远最后，保证可被同名遮蔽）
        │  runtime_skills() runtime.py:47-61：按名字先到先得 resolved.setdefault(name, service)
        │  并应用工作区资源选择（current_resources().skills，runtime.py:51-57）
        ▼
  skill_manifest() runtime.py:64-75
        ├─ always 且可用的技能 → load_for_context() 全文块（service.py:513-543）
        └─ 其余 → render_skills_manifest() service.py:997-1023
              "## Skills" 一行一条：`- **name** — description (unavailable: …)`
        ▼
  executor 每轮调用 deeptutor/services/session/turns/executor.py:604-606
        → UnifiedContext.skills_manifest（deeptutor/core/context.py:114-117、144）
        ▼
  prompt_blocks 把它挂成 "skills" 块 deeptutor/agents/loop/prompt_blocks.py:178-179
```

伙伴回合平行存在一条：`_build_skills_manifest()`（`deeptutor/services/partners/runtime.py:874`-892）——绑定了工作区的伙伴直接复用 `skill_manifest()`；否则退回"自身账号层 + always 块"。伙伴把 builtin 复制进工作区属于"钉住快照"，不是覆盖产品内置（`deeptutor/services/partners/workspace.py:224`-252）。

注意两条链的差异：`SkillService.list_skills()`（`deeptutor/services/skill/service.py:412`-435）只是**单服务内** user>builtin 的合并；运行时真正可见的是 `runtime_skills()`（`deeptutor/services/skill/runtime.py:47`）合成的四层表，中间还插了 admin 授予层和工作区选择。看"用户能看到哪些技能"时永远看后者。

## 4. 匹配与排序：没有打分器

运行时**没有**基于 tag/taxonomy 的匹配或相关性打分：

- 模型侧"匹配"完全靠 manifest 里的 `description` 自行判断——清单文案直接要求"任务匹配某技能就先 `read_skill`"（`deeptutor/services/skill/service.py:1017`-1022）。
- 顺序是确定性的三段叠加：目录字典序扫描（`deeptutor/services/skill/service.py:417`、`427`）→ 层级先到先得（workspace > account > admin > builtin，`deeptutor/services/skill/runtime.py:60`）→ manifest 去重保留首次出现（`deeptutor/services/skill/service.py:1002`-1009）。改顺序只能改层级来源，不存在 score 字段。
- `taxonomy.py` 与以上全部无关：它是 EduHub 发布/更新的分类常量——必选 `track`（`deeptutor/services/skill/taxonomy.py:51`-56）、可选 `language/stages/forms/audiences/domains`（`deeptutor/services/skill/taxonomy.py:60`-97、两级 domains 树 `deeptutor/services/skill/taxonomy.py:111`-255），取值逐一镜像 eduhub web 的 `src/data/taxonomy.ts`（`deeptutor/services/skill/taxonomy.py:5`-16）。CLI 发布时按固定顺序走交互打标：track→language→domains→stages→forms→audiences→tags（`deeptutor_cli/skill_prompts.py:148`-`207`，选择器 `deeptutor_cli/skill_prompts.py:55` / `deeptutor_cli/skill_prompts.py:78` / `deeptutor_cli/skill_prompts.py:102`）。

## 5. 凭据边界

三类凭据/端点配置，边界清晰：

1. **`settings/skill_hub_auth.json`** —— hub 发布令牌，秘密。`store_token` 经 `write_secret_text` 落盘 0600（`deeptutor/services/skill/credentials.py:64`-81）；读取 `deeptutor/services/skill/credentials.py:49` / 身份快照 `deeptutor/services/skill/credentials.py:58`；登出 `deeptutor/services/skill/credentials.py:84`。
2. **`settings/skill_hubs.json`** —— hub 端点配置，可分享，不含秘密（`deeptutor/services/skill/hub.py:34`-41；内置 eduhub/clawhub 兜底 `deeptutor/services/skill/hub.py:69`-80，`get_hub_provider:700`-720 允许用户配置覆盖内置）。
3. **令牌解析顺序**（发布/更新时）：`--token` → `$DEEPTUTOR_HUB_TOKEN` / `$EDUHUB_TOKEN` → 本地 store（`deeptutor_cli/skill.py:26`-36 与 `deeptutor/services/skill/credentials.py:5`-11 一致）。`deeptutor skill login` 浏览器 OAuth 拿到的令牌就存进 store（`deeptutor_cli/skill.py:187`-242，state 校验见 `tests/services/skill/test_skill_login.py:43`）。

边界要点：**运行时技能消费链完全无凭据**——`skill_manifest()` / `read_skill` 不碰 hub、不读令牌；hub 令牌只在 `publish` / `update` / `list-my-skills` 这三个写向/账号面出现（`deeptutor/services/skill/hub.py:504`、`540`-565）。`skill install` 走 hub 公开只读 API，同样无令牌，但 hub 判 `suspicious` 时拒绝安装，除非显式 `--allow-unverified`（`deeptutor/services/skill/hub.py:746`-751）。

## 6. hub 导入与发布管线

导入（外部仓 → 本地 user 层），一条流水线（`deeptutor/services/skill/hub.py:726`-776）：

```
parse_hub_ref("<hub>:[<owner>/]<slug>[@version]") hub.py:82-87、164-181（无前缀默认 eduhub）
  → verify：hub 安全裁决，suspicious 即中止（hub.py:745-751）
  → fetch：下载 zip → 防守式解包（zip-slip/炸弹守卫 hub.py:91-94、205-248；
      定位 SKILL.md 根 hub.py:251-262；命令型仓 CommandProvider hub.py:600-660）
  → install_tree（service.py:631-712）：
      frontmatter 适配：slug 强制对齐、扁平 bins/env 折进 requires、
        always: 无条件剥离——导入技能绝不急切注入（service.py:735-741、755-764）
      支撑文件：后缀白名单 + 单文件 1MB/总量 20MB/500 个上限 + 符号链接直接中止
        （service.py:86-102、766-804）；staging 目录原子换入（service.py:690-702）
      来源记账 .hub-lock.json（hub.py:754-762）；来源 hub 打成 tag（hub.py:769-771）
```

发布（本地目录 → hub）：`deeptutor skill publish` 先本地预检 `preflight_skill_dir`（`deeptutor/services/skill/hub.py:833`-888，含危险二进制黑名单 `deeptutor/services/skill/hub.py:812`-830），交互补全分类（§4），`publish_to_hub`（`deeptutor/services/skill/hub.py:973`-1039）把 frontmatter 元数据直通上传（白名单键 `deeptutor/services/skill/hub.py:894`-904），交互态确认表见 `deeptutor_cli/skill.py:40`-71。`update` 命令负责列我的技能/回退 dist-tag/发新版本（`deeptutor_cli/skill.py:381`-537）。

API/CLI/UI 三个操作面共享同一服务层：REST 路由 `/api/skills`（挂载 `deeptutor/api/main.py:734`；CRUD+tags+hub catalog/detail/install 见 `deeptutor/api/routers/skills.py:85`-305，非管理员越权读有 403 门 `deeptutor/multi_user/skill_access.py:63`-74）；CLI 组 `deeptutor skill|skills …`（注册 `deeptutor_cli/main.py:55`-56）；UI 页面 `web/app/(utility)/space/skills/page.tsx`。

## 7. 工具暴露链：`read_skill` 何时存在

`read_skill` 是条件自动挂载工具，链路每一环都能让它消失：

```
skills_manifest 非空                        executor.py:606
  → has_skills=True                         deeptutor/agents/loop/pipeline.py:755
  → 条件挂载表 read_skill ← has_skills      deeptutor/agents/_shared/tool_composition.py:59、159
  → 模型可见 read_skill schema              deeptutor/tools/builtin_specs.py:61（懒加载目录）
  → ReadSkillTool.execute                   deeptutor/tools/builtin/__init__.py:1714-1805
       visible = runtime_skills()           （同 §3 的四层表，__init__.py:1764-1767）
       service.read_skill_file(name, file)  service.py:452-476：
         绝对路径/.. 段拒绝；resolve 后必须仍在技能目录内（service.py:466-470）
         超 100k 字符截断（service.py:76、474-475）
       技能命中但文件不存在 → 列出该技能实际文件（上限 40 个，__init__.py:386、1771-1787）
       名字不在可见表 → 报错并列出全部可用名（__init__.py:1796-1805）
```

两个推论：清单为空（无任何可见技能）的回合 `read_skill` 根本不挂载；清单里标 unavailable 的技能**仍会**出现在 manifest 并可被 `read_skill`——门禁只改 manifest 文案，不阻断读取（`deeptutor/services/skill/service.py:1010`-1012、`deeptutor/services/skill/runtime.py:51`-57 无可用性过滤）。

## 8. 新增内置技能 checklist

按顺序过一遍（对应代码锚点见括号）：

1. 建目录 `deeptutor/skills/builtin/<slug>/SKILL.md`；slug 匹配 `^[a-z0-9][a-z0-9-]{0,63}$`，目录名即对外技能名（`deeptutor/services/skill/service.py:64`、`deeptutor/services/skill/service.py:404`）。
2. frontmatter 必写 `description`——它是模型选不选你的唯一信号（`deeptutor/services/skill/service.py:405`；渲染时缺失会退回技能名 `deeptutor/services/skill/service.py:1013`）。写清"何时用/何时不用"（参照 `deeptutor/skills/builtin/pdf/SKILL.md:2`-5）。
3. 不写 `always: true`，除非确属每轮必须生效的家规（`deeptutor/services/skill/service.py:13`-14）；外部导入路径会强制剥离该键（`deeptutor/services/skill/service.py:755`-764），别让 builtin 与导入行为不一致。
4. 依赖外部 CLI/环境变量/沙箱的，写 `requires:` 门禁而不是在正文假设环境存在（`deeptutor/services/skill/service.py:370`-394）； office 类一律 `sandbox: shell`。
5. 大材料放 `references/`，正文保持精读友好；`read_skill` 有 100k 截断与文件列表上限，别指望单文件塞下一切（`deeptutor/services/skill/service.py:474`-475、`deeptutor/tools/builtin/__init__.py:1777`-1780）。
6. 起名避开常见用户技能名：同名 user 技能会**静默遮蔽** builtin（`deeptutor/services/skill/service.py:248`-258）。
7. 记住 builtin 运行时只读（写操作抛 `SkillReadOnlyError`，`deeptutor/services/skill/service.py:547`-553），改内容走仓库 PR。
8. 测试只引用不重复：frontmatter 契约 `myfork/agen1084-skill-frontmatter-tests`（`tests/services/skill/test_skill_frontmatter_contract.py`）；builtin 注册面 `myfork/test/skills-builtin-registry-20261007`（`tests/services/test_skills_builtin_registry.py`）；taxonomy 取值 `myfork/test/skill-taxonomy-20261005`（`tests/services/skill/test_taxonomy.py`）；skills API 路由契约 `myfork/test/skills-router-20261009`（`tests/api/test_skills_router.py`）。主树既有覆盖：`tests/services/skill/test_skill_service_v2.py`（双层遮蔽/manifest/门禁）、`test_skill_hub.py`（导入适配）、`test_skill_publish_flow.py`（预检/直通字段）。
9. 跑一遍现有服务测试确认无回归：`timeout 900 python -m pytest -q -p no:cacheprovider tests/services/skill`。

## 9. 三处易误读

1. **`taxonomy.py` 不参与运行时匹配**：它只是 EduHub 发布/更新的表单常量；模型选技能只看 manifest 的 `description`，排序是"层级先到先得 + 首次出现去重"，没有任何打分器（§4）。
2. **可见性 ≠ `list_skills()`**：UI/API 列表、运行时 manifest、伙伴工作区各走各的合成链——运行时四层顺序 workspace > account > admin(仅授予) > builtin，而 `list_skills()` 只有 user>builtin 两层（§3 结尾）。
3. **`requires` 门禁不阻断 `read_skill`**：缺 bins/env/sandbox 的技能在 manifest 里标 `(unavailable: …)` 但仍在清单、仍可被读取；真正被门禁拦下的是"模型不该尝试执行它"，不是"模型不该读它"（§7 结尾）。

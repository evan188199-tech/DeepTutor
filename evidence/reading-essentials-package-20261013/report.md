# 扫描报告：packages/deeptutor-reading-essentials 包内容与消费关系

- 扫描日期：2026-10-13
- 基线：origin/main `6cf793bd8`（release v1.6.14），只读新 worktree；live checkout `/Users/Shared/DeepTutor`（local `main` `2a4c4c5f1`）仅只读查看，未做任何修改。
- 产物：本报告 + `snapshots/`（已删除源码与残留构建物的逐字节快照）+ `SHA256SUMS`。
- 本分支仅新增 `evidence/`，未改动任何代码。

## 1. 结论摘要

1. 该包**从未进入上游**（origin/main、origin/dev 的全树 grep 均为 0 命中）；它只存在于本地 `main` 历史，2026-08-23 引入、2026-08-30 被删除（§6 时间线）。
2. 功能已被**吸收进 core**：上游与本地 main 的根 `pyproject.toml` 现在直接注册同名 entry-point 组的 5 个扩展（§5.1）。
3. live checkout 只剩 **8 个被 git 忽略的构建残留文件**（版本 0.1.0，比删除前最后一次提交的 0.2.0 源码还旧两代），**未安装**进 `.venv`，当前**消费者为零**（§4）。
4. 残留源码相对现行 API 已失效：`ReadingContext` 已删除 `unit_text`/`age_band` 字段，包代码 6 处引用将抛 `AttributeError`；两个依赖模块已不存在（§5.2–5.3）。
5. 治理建议：删除残留目录即可，无上游行动必要（§7）。

## 2. 内容清单

### 2.1 现存于 live checkout 的文件（全部为 git 忽略的构建残留）

`/Users/Shared/DeepTutor/packages/deeptutor-reading-essentials/` 下共 8 个文件（逐条含大小/时间见 `snapshots/residue-file-inventory.txt`）：

| # | 文件 | 性质 |
|---|------|------|
| 1 | `build/lib/deeptutor_reading_essentials/__init__.py`（247 行） | v0.1.0 构建副本（2026-08-23 10:12） |
| 2 | `deeptutor_reading_essentials.egg-info/PKG-INFO` | 元数据，`Version: 0.1.0` |
| 3 | `deeptutor_reading_essentials.egg-info/SOURCES.txt` | 构建清单 |
| 4 | `deeptutor_reading_essentials.egg-info/dependency_links.txt` | 空占位 |
| 5 | `deeptutor_reading_essentials.egg-info/entry_points.txt` | 5 个入口（同 v0.1.0） |
| 6 | `deeptutor_reading_essentials.egg-info/requires.txt` | `deeptutor` |
| 7 | `deeptutor_reading_essentials.egg-info/top_level.txt` | `deeptutor_reading_essentials` |
| 8 | `deeptutor_reading_essentials/__pycache__/__init__.cpython-313.pyc` | 2026-08-24 09:07 编译缓存 |

要点：
- **源码文件已不存在**：目录里没有 `pyproject.toml`、`README.md`、`deeptutor_reading_essentials/__init__.py`（`find` 全量清单即上表 8 项）。
- **git 不追踪**：`git ls-tree -r HEAD -- packages/` 为空、`git status --porcelain -- packages/` 为空——这些文件被 `build/`、`*.egg-info/`、`__pycache__/` 忽略规则覆盖，属于删除源码后遗留的构建垃圾。

### 2.2 删除前最后提交内容（v0.2.0，local main `763a4b12d`，2026-08-29）

共 3 个包文件 + 1 个专属测试（快照见 `snapshots/`）：

| 文件 | 内容 | 快照 |
|------|------|------|
| `pyproject.toml` | 20 行：setuptools 构建；`name=deeptutor-reading-essentials`，`version=0.2.0`，`dependencies=["deeptutor"]`，`requires-python>=3.11,<3.14`；5 个 entry point | `snapshots/pkg-pyproject-0.2.0.toml` |
| `README.md` | 91 行：定位为“可选沉浸阅读扩展”，宣称 `pip install deeptutor-reading-essentials` 安装 | `snapshots/pkg-README-0.2.0.md` |
| `deeptutor_reading_essentials/__init__.py` | 676 行：5 个扩展类 + LLM 兜底逻辑 | `snapshots/pkg-init-0.2.0.py` |
| `tests/reading/test_essentials_package.py` | 297 行：sys.path 注入方式加载包源码做契约测试 | `snapshots/test-essentials-package-0.2.0.py` |

### 2.3 对外入口（entry points）

组名 `deeptutor.reading_extensions`，5 个入口（v0.1.0 与 v0.2.0 名称一致，`snapshots/residue-entry_points.txt`、`snapshots/pkg-pyproject-0.2.0.toml:13-17`）：

| 入口名 | 目标类 | 行号（v0.2.0 源码） |
|--------|--------|---------------------|
| `guided_learn` | `deeptutor_reading_essentials:GuidedLearnExtension` | `snapshots/pkg-init-0.2.0.py:217` |
| `quiz` | `deeptutor_reading_essentials:QuizExtension` | `snapshots/pkg-init-0.2.0.py:593` |
| `read_aloud` | `deeptutor_reading_essentials:ReadAloudExtension` | `snapshots/pkg-init-0.2.0.py:199` |
| `translation` | `deeptutor_reading_essentials:TranslationExtension` | `snapshots/pkg-init-0.2.0.py:408` |
| `vocabulary` | `deeptutor_reading_essentials:VocabularyExtension` | `snapshots/pkg-init-0.2.0.py:299` |

## 3. 版本与发布方式

- 版本演进：v0.1.0（`2efb33651`，2026-08-23）→ v0.2.0（`0bf4ac0c3`，2026-08-24）。仅存在于 local main；myfork 的 backup/codex 分支保留镜像副本（tip 仍为 v0.1.0，如 `myfork/codex/fix-reading-annotation-click` 的 `packages/deeptutor-reading-essentials/pyproject.toml:6`）。
- 发布方式：**源码树内 setuptools 包，仅支持本地路径安装**（`pip install ./packages/deeptutor-reading-essentials`），依赖 `deeptutor` 本体；无 PyPI 发布、仓库内无 wheel 产物。egg-info 时间戳（2026-08-23 17:00）表明只在本地构建/安装过一次 v0.1.0。
- 上游状态：`git ls-tree -r origin/main | grep -ci reading-essential` = 0，origin/dev 同样为 0——**上游从未包含此包**，也不存在上游 PR。

## 4. 消费关系

### 4.1 历史消费者（包存在期间，2026-08-23 ~ 2026-08-30）

- entry-point 加载器：`deeptutor/reading/extensions.py:22`（origin/main 现行文件，`ENTRY_POINT_GROUP = "deeptutor.reading_extensions"`）；`2efb33651` 引入包时同步修改了该文件与路由。
- 注册表：`ReadingExtensionRegistry.__init__` 经 `load_entry_point_group` 发现已安装发行版（origin/main `deeptutor/reading/extensions.py:110-118`）。
- API 路由闸门：`deeptutor/api/routers/reading_extensions.py:17,143`（`allowed_reading_extensions` 白名单过滤）。
- 多用户权限：`deeptutor/multi_user/learning_access.py:109`。
- 插件运行时类型映射：`deeptutor/plugins/runtime.py:446`（组 → `reading_extension` 类型）。
- 专属测试：`tests/reading/test_essentials_package.py:14`（以 `PACKAGE_ROOT` 把包源码注入 `sys.path` 加载，:34 构造带 `unit_text` 的上下文）；该测试随包一起在 `47c00260a` 删除。

### 4.2 当前消费者：零

- **未安装**：`/Users/Shared/DeepTutor/.venv` 的 site-packages 中无 `deeptutor_reading_essentials`/`deeptutor-reading-essentials` 发行版（扫描 0 命中）。发现机制是 `importlib.metadata.entry_points`（`deeptutor/plugins/entry_points.py:30`），只认已安装发行版；残留的 `packages/**.egg-info` 不在 `sys.path` 上，不会被注册。
- **代码零引用**：origin/main 全树（`*.py`/`*.toml`/`*.md`）grep `reading-essentials|reading_essentials` 仅命中与包无关的 `reading_extensions` 机制文件；live checkout 的 `tests/reading/` 现为 core 扩展测试（`test_extensions.py`、`test_read_aloud.py`、`test_study_guidance.py`、`test_quiz.py`、`test_translation.py`），无 essentials 专属测试。
- **文档零引用**：origin/main 与 live checkout 的 `docs/`、`docs-for-user/` grep 包名均 0 命中；现行用户文档 `docs-for-user/READING_EXTENSIONS.md` 描述的是 core 机制。
- 前端 `web/components/reading/ReadingExtensionBar.tsx` 消费的是扩展 API 结果，与具体发行版无关。

## 5. 与 deeptutor/reading 主代码的重复与漂移

### 5.1 功能重复：包的 5 个动作已被 core 原样接管

- origin/main 根 `pyproject.toml:100-106` 注册同一组 5 个入口，实现全部在 core 模块：`deeptutor/reading/read_aloud.py`、`study_guidance.py`、`vocabulary.py`、`quiz.py`、`translation.py`（5 个文件均存在，逐一验证）。
- origin/dev `pyproject.toml:100-105`、live local main `pyproject.toml:92-97` 内容相同。
- 对应关系：`read_aloud`↔`ReadAloudExtension`、`guided_learn`↔`StudyGuidanceExtension`（入口名改为 `guided_learning`）、`vocabulary`↔`VocabularyExtension`、`quiz`↔`ReadingQuizExtension`、`translation`↔`TranslationExtension`。即包内 5 类与 core 5 模块**一一对应、完全重复**。

### 5.2 API 漂移：包 v0.2.0 源码已不可运行

- 现行 `ReadingContext`（origin/main `deeptutor/reading/extensions.py:44-50`；live `deeptutor/reading/extensions.py:45`）字段仅有 `material_id/locator/source_anchor/locale/selection/visible_text`，**没有 `unit_text` 和 `age_band`**。
- 历史版本曾有这两个字段（`763a4b12d:deeptutor/reading/extensions.py:49,52`），删除包的同一时期被一并移除。
- 包 v0.2.0 源码 6 处引用将直接 `AttributeError`：`snapshots/pkg-init-0.2.0.py:187,228,240,331,398,604,608`（如 `_BaseExtension._source` 的 `context.unit_text`、`GuidedLearnExtension` 的 `context.age_band`）；其专属测试同样构造了已废弃字段（`snapshots/test-essentials-package-0.2.0.py:34`）。

### 5.3 依赖漂移：两个依赖模块已不存在

- `deeptutor/immersive_reading/kids_word_hints.py`、`deeptutor/immersive_reading/sight_words.py` 在 origin/main **不存在**（`git cat-file -e` 逐一验证）；包 v0.2.0 的 lazy import 位于 `snapshots/pkg-init-0.2.0.py:310,484`，调用即 `ModuleNotFoundError`。live checkout 的 `deeptutor/immersive_reading/` 下仅剩 `bilingual/`。
- LLM 依赖仍在：`deeptutor/services/llm/exceptions.py` 存在（origin/main），`deeptutor/utils/json_parser.py` 存在；包引用见 `snapshots/pkg-init-0.2.0.py:18-19,234,432,529`。

### 5.4 残留自身漂移：构建物落后最后提交两代

- 残留 `build/lib` 与 egg-info 均为 **v0.1.0**（`snapshots/residue-PKG-INFO.txt:3`；`snapshots/residue-build-init-0.1.0.py` 为同步 `run_action`、无 LLM 增强），而删除前最后提交的源码是 **v0.2.0**（async `run_action`、LLM learn/quiz、kids word hint 判题）。与 `pkg-init-0.2.0.py` diff 超过 400 行差异。

### 5.5 若误装残留包的风险

- 入口名冲突 4/5：`quiz`、`read_aloud`、`translation`、`vocabulary` 与 core 入口同名（§2.3 vs origin/main `pyproject.toml:101-105`）。
- 注册表按 manifest id `setdefault` 去重、**先到先得**（origin/main `deeptutor/reading/extensions.py:118`），entry-point 跨发行版的枚举顺序未定义 → 旧 v0.1.0 实现**可能非确定性地遮蔽 core 实现**。

## 6. 时间线（local main）

| 时间 (UTC) | 提交 | 事件 |
|------------|------|------|
| 2026-08-23 10:08 | `2efb33651` | 引入包 v0.1.0 + loader/路由/测试 |
| 2026-08-23 17:00 | —（本地构建） | 生成 egg-info/build 残留（v0.1.0） |
| 2026-08-24 08:58 | `0bf4ac0c3` | 升级 v0.2.0（kids parity） |
| 2026-08-29 18:14 | `763a4b12d` | local main 上最后一个仍含包的提交 |
| 2026-08-30 01:44 | `786e3ac92` 等 | 镜像分支（myfork backup/codex）上的 harden 副本，**不在 local main** |
| 2026-08-30 03:21 | `47c00260a` | 从 local main 删除包 3 个源文件（`git diff 763a4b12d 47c00260a -- packages/` 全为 `D`），功能已并入 core |
| 上游 | — | origin/main、origin/dev 从未包含（全树 grep 0 命中） |

## 7. 治理建议

1. **删除残留**：`packages/deeptutor-reading-essentials/` 在 live checkout 中是纯构建垃圾（git 忽略、未安装、零引用），直接整目录删除即可，无任何代码影响。本卡不改代码，删除动作留给仓库主人。
2. **不恢复独立包**：core 已内建同组 5 个扩展且 API 已演进（§5.2），包 v0.2.0 复活即失效；若确需“可选扩展分发”，应走插件体系方向（`docs/plugin-platform-rfc.md:33` 列出 `deeptutor.reading_extensions` 为插件 entry-point 组之一）。
3. **可选加固（不改代码，仅记录）**：若担心历史误装 v0.1.0 残留发行版遮蔽 core，可在 `ReadingExtensionRegistry` 对同 id 冲突打告警日志（落点 origin/main `deeptutor/reading/extensions.py:118`）。
4. **无上游行动**：上游从未有过该包，无需 issue/PR/文档变更；镜像分支（myfork backup/codex）如需清理属 fork 侧杂务，与上游无关。

## 8. 验收对照

1. **列全包内文件与对外入口** → §2.1（现存 8 个残留文件）、§2.2（最后提交 3+1 文件）、§2.3（5 个 entry point 全列）。
2. **每个结论附 path:line** → 全文各节；快照文件行号以 `snapshots/` 内文件为准。
3. **不改任何代码** → 本分支相对 origin/main `6cf793bd8` 仅新增 `evidence/reading-essentials-package-20261013/`；live checkout 与主 worktree 全程只读。

## 附录：方法

- worktree：`git worktree add -b scan/reading-essentials-package-20261013 <wt> origin/main`（基线 `6cf793bd8`）。
- 历史定位：`git log --all -- packages/deeptutor-reading-essentials`、`rev-list` 逐提交 `cat-file -e <c>:packages/.../pyproject.toml` 定位引入/最后存在/删除点。
- 消费者排查：`git grep`（origin/main 全树）、live `.venv` site-packages 扫描、live docs/tests 目录清点。
- 漂移对比：`diff` 残留 build 副本 vs `763a4b12d` 源码；现行 `ReadingContext` 字段核对（origin/main 与 live 各一次）。

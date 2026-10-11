# scan: Python 依赖清单漂移扫描（requirements/pyproject × 实际 import）

- 基线：`origin/main` = `origin/dev` = `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14，2026-10-08），只读扫描。
- 方法：纯静态 AST 扫描（`ast.parse` 全量解析），零安装、零代码改动。对每条 import 记录：根模块、`file:line`、方式（top=模块顶层 / lazy=函数或方法内 / dynamic=`importlib.import_module`/`__import__`/`importlib.util.find_spec` 常量串）、是否处于 `try/except ImportError` 守卫内。
- 扫描范围：主范围 `deeptutor/` + `deeptutor_cli/`（pyproject 打包发布面，1078 个 .py）；参考范围 `scripts/` + `tests/` + `examples/`（820 个 .py，仅用于佐证，不计入漂移主表）。合计 1898 个 .py，16506 条 import 记录；主范围去重后 9276 条，见 `imports-inventory.tsv`。
- 声明面：`pyproject.toml`（`[project] dependencies` 54 项 + `[project.optional-dependencies]` extras）与 `requirements/*.txt` 镜像（`requirements.txt` → partners.txt → server.txt → cli.txt）。
- 去重说明：web/JS 侧 bundle 依赖不在本卡（见 scan-web-bundle-deps 卡）；scripts 侧清单参见 scan-scripts-inventory 卡，本卡不重复。
- 标准库与第一方模块（`deeptutor*`、`scripts`、`tests` 等）已排除。

## 三类计数（主范围）

| 类别 | 行数 | 说明 |
| --- | --- | --- |
| A 未声明（代码在用、任何声明层都没有） | 10 | 6 条依赖传递依赖兜底、2 条 crypto 库完全未声明、1 条未声明可选 SDK、1 条 import 名与声明不符 |
| B 声明未用（声明存在、零 import 证据） | 9 + 2 注记 | 6 条 core、3 条 partners；注记：python-multipart（框架运行时所需，非删除候选）、dev 工具 4 件（CLI 工具，无 import 属预期） |
| C 可选被当必宣（core 声明，实际用法为 lazy/guarded） | 15 | 10 条有显式回退或守卫报错、5 条 lazy 无守卫；另注：`mcp` 属注释论证过的有意 core 声明，不计入 |

## 文件

- `01-undeclared-imports.md` — A 类：未声明依赖清单
- `02-unused-declarations.md` — B 类：声明未用清单
- `03-optional-as-required.md` — C 类：可选依赖被当必宣清单
- `imports-inventory.tsv` — 主范围全部第三方 import 明细（root → dist 映射、方式、守卫、file:line）
- `SHA256SUMS` — 以上文件校验和

## 复现

对任意工作副本（只读）执行 AST 扫描脚本即可重现；脚本逻辑、扫描口径与本 README 描述一致（`ast` + `sys.stdlib_module_names` 排除标准库）。零进程残留、零网络访问。

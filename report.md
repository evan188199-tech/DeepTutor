# GitHub Actions 配置一致性清点（2026-10-07）

- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13）
- 范围：`.github/workflows/` 全部 4 个文件、11 个 job、24 个 `uses:` 引用。只读清点，未修改任何代码，未触发任何 workflow。
- 分级：**高** = 影响发布产物正确性；**中** = 缺显式护栏（权限 / 超时 / 并发 / 可移动引用）；**低** = 一致性与文档口径。
- 结论计数：**高 1 · 中 8 · 低 14，共 23 项**，覆盖 4/4 个 workflow 文件。

## 总览

| 维度 | 现状 |
| --- | --- |
| workflow 文件覆盖 | 4/4（tests、repository-hygiene、docker-release、pypi-release） |
| job 数 | 11（tests 6、docker 2、pypi 2、hygiene 1） |
| `timeout-minutes` | **0/11 job 设置**（默认 360 分钟） |
| 显式 `permissions` | 2/4（缺 tests.yml、repository-hygiene.yml） |
| `concurrency` | 1/4（仅 pypi-release.yml） |
| `uses:` 引用 | 24 个：major tag 23、可移动分支引用 1（`@release/v1`）、SHA 固定 0 |
| secrets 引用 | 1 处：`secrets.GITHUB_TOKEN`（docker-release.yml:84），无自定义 secret |
| vars 引用 | 2 个：`DEEPTUTOR_MULTI_WORKER_E2E_URL`、`DEEPTUTOR_MULTI_WORKER_CONTROL_URL`（均未在仓库文档中说明） |

## 一、docker-release.yml（7 项：高 1 · 中 2 · 低 4）

| ID | 分级 | 位置 | 现状 | 建议 |
| --- | --- | --- | --- | --- |
| DR-1 | 高 | `.github/workflows/docker-release.yml:68-69` | checkout 未指定 ref；`release` 事件的 `github.sha` 解析到默认分支最新提交而非发布 tag，镜像可能从非 tag 提交构建。对照 pypi-release.yml:65-69 已显式 `ref: ${{ github.event.release.tag_name }}` 并在 :71-81 校验 tag 在 main | 补 `ref: ${{ github.event.release.tag_name }}`，并对齐 pypi-release 的"tag 在 main"祖先校验 |
| DR-2 | 中 | `docker-release.yml:22-25`、`62-65` | 两个 job 均无 `timeout-minutes`；build-and-push 含 QEMU arm64 交叉构建，耗时长，默认 360 分钟兜底过宽 | 每 job 设 `timeout-minutes`（validate 约 5，build 约 30–45） |
| DR-3 | 中 | `docker-release.yml:13-21` | 无 `concurrency` 块；pypi-release.yml:24-26 有按 tag 分组的并发控制，两个发布 workflow 口径不一致 | 加 `concurrency: group: docker-release-${{ github.event.release.tag_name }}` |
| DR-4 | 低 | `docker-release.yml:69,73,77,80,90,98` | 6 个 `uses:` 均为 major tag（@v4/@v3/@v3/@v3/@v5/@v6），未 SHA 固定 | SHA 固定（可配 Dependabot 维护） |
| DR-5 | 低 | `docker-release.yml:17-19` | 顶层 `packages: write` 作用到 validate job（:22-25），该 job 无写包需求 | 权限下放到 build-and-push job，validate 仅 `contents: read` |
| DR-6 | 低 | `docker-release.yml:9` | 头注释称 latest "always points to the most recently published release"，与 :95（仅 stable 非 prerelease 打 latest）及 README.md:397 口径不一致，注释过期 | 更新注释为"latest 仅指向最新稳定版" |
| DR-7 | 低 | `docker-release.yml:68-69` | 发布类 workflow 的 checkout 未设 `persist-credentials: false`，运行期保留 GITHUB_TOKEN 凭据（加固建议，非缺陷利用描述） | 加 `persist-credentials: false` |

正面：`permissions` 显式（:17-19）；`provenance: mode=max` + `sbom: true`（:105-106）；tag 校验正则严格（:37-49）；镜像/tag 口径与 README.md:396-397 一致。

## 二、pypi-release.yml（5 项：中 2 · 低 3）

| ID | 分级 | 位置 | 现状 | 建议 |
| --- | --- | --- | --- | --- |
| PY-1 | 中 | `.github/workflows/pypi-release.yml:179` | `pypa/gh-action-pypi-publish@release/v1` 是可移动的分支式引用，行为随上游漂移，且该步骤持有 id-token: write | 固定到具体发布 tag 或 commit SHA |
| PY-2 | 中 | `pypi-release.yml:29-32`、`56-59` | 两个 job 均无 `timeout-minutes`；build-and-publish 含前端构建 + 打包，默认 360 分钟兜底过宽 | 每 job 设 `timeout-minutes`（validate 约 5，build 约 30） |
| PY-3 | 低 | `pypi-release.yml:20-22` | 顶层 `id-token: write` 覆盖 validate job（:29-32），该 job 无发布需求 | id-token: write 下放到 build-and-publish job（:56-59） |
| PY-4 | 低 | `pypi-release.yml:66,84,89` | 3 个 `uses:` 为 major tag，未 SHA 固定 | SHA 固定 |
| PY-5 | 低 | `pypi-release.yml:60-62` | 隐含依赖名为 `pypi` 的 GitHub environment + PyPI Trusted Publisher 配置；CONTRIBUTING.md、README.md、docs-for-user/ 均未记录该配置要求（仅头注释 :13-14 一句带过） | 在文档中补一段发布前置配置说明 |

正面：tag checkout + "tag 在 main"祖先校验（:65-81）；tag 与 `deeptutor/__version__.py` 双向版本校验（:100-134）；构建从 /tmp 执行避免本地 build/ 目录遮蔽（:151-156）；并发组按 tag 分组且不取消进行中的发布（:24-26）。

## 三、tests.yml（7 项：中 3 · 低 4）

| ID | 分级 | 位置 | 现状 | 建议 |
| --- | --- | --- | --- | --- |
| TS-1 | 中 | `.github/workflows/tests.yml:34`（文件级） | 全文件无 `permissions` 块，job 以仓库默认 token 权限运行 | 顶层加 `permissions: contents: read` |
| TS-2 | 中 | `tests.yml:35-37,64-66,109-112,155-157,221-223,291-293` | 6 个 job 均无 `timeout-minutes`；python-tests（:221）还起 redis 服务容器（:225-234）跑全量 pytest，4 个 Python 版本 × 无超时 | 每 job 设 `timeout-minutes`（lint 约 10、web 约 30、import/python 约 45） |
| TS-3 | 中 | `tests.yml:7-10` | push 到 main/dev 无 `concurrency`，连续提交会并行叠跑全矩阵（4×Python + 2 个 web job） | 加 `concurrency: group: tests-${{ github.ref }}` 并对 push 取消进行中跑批（schedule/dispatch 保留） |
| TS-4 | 低 | `tests.yml:11-19,24-32` | paths 过滤未含 `scripts/**`，而 lint job 执行 `scripts/check_architecture.py`（:62）；单独改该脚本不触发 CI | paths 补 `scripts/**`（或至少 `scripts/check_architecture.py`） |
| TS-5 | 低 | `tests.yml:111,141,143` | 引用 `vars.DEEPTUTOR_MULTI_WORKER_E2E_URL` / `vars.DEEPTUTOR_MULTI_WORKER_CONTROL_URL`；README.md、CONTRIBUTING.md、docs-for-user/ 均未说明如何配置（消费方仅 web/tests/e2e/fixtures/runtime.ts:45-59） | 文档补两个 repo variable 的配置口径 |
| TS-6 | 低 | `tests.yml:41,44,70,73,116,119,147,179,182,187,242,245,250` | 13 个 `uses:` 均为 major tag，未 SHA 固定 | SHA 固定 |
| TS-7 | 低 | `tests.yml:262` | `pip install pytest pytest-asyncio` 未固定版本；同文件 :51 已固定 `ruff==0.16.0 import-linter==2.11`，口径不一致 | 固定 pytest/pytest-asyncio 版本 |

正面：test-summary 以 `always()` + 显式失败判定守门（:294-295、:310-312）；artifact 上传 `if: always()`（:146）；web 审计起服带 trap 清理与就绪轮询（:94-106）；触发器 branches + paths 双过滤设计合理（:7-32）；multi-worker job 以 `vars != ''` 作为可选开关并在汇总中区分 skipped（:111、:306）。

## 四、repository-hygiene.yml（4 项：中 1 · 低 3）

| ID | 分级 | 位置 | 现状 | 建议 |
| --- | --- | --- | --- | --- |
| RH-1 | 中 | `.github/workflows/repository-hygiene.yml:13` | 无 `permissions` 块；job 仅需读（:22-23） | 加 `permissions: contents: read` |
| RH-2 | 低 | `repository-hygiene.yml:14-16` | 无 `timeout-minutes`、无 `concurrency`（job 开销小，优先级低） | 顺手补 `timeout-minutes: 5` |
| RH-3 | 低 | `repository-hygiene.yml:23` | 用 runner 默认 `python3`（版本不受控）；其余 workflow 显式 setup-python@v5 + 3.11（tests.yml:44-46、pypi-release.yml:83-86） | 对齐为显式 setup-python 3.11 |
| RH-4 | 低 | `repository-hygiene.yml:20` | checkout 为 major tag，未 SHA 固定 | SHA 固定 |

## 上游重叠检查（开工时）

- PR #1693（open，head `fix/tool-hint-sanitize`）：diff 覆盖 300+ 文件且将 4 个 workflow 文件整体删除（`status: removed`），属宽同步型 PR，非 hygiene 修复，与本卡无重叠。
- PR #1322（open）：新增 `electron-release.yml`（新 workflow，另一条线），与本卡无重叠。

## 可拆修复卡条目

1. 【高】docker-release checkout 固定 release tag 并对齐 pypi-release 的主线祖先校验（DR-1，独立 1 PR）。
2. 【中】4 个 workflow 全部 job 补 `timeout-minutes`（DR-2 / PY-2 / TS-2 / RH-2，1 PR）。
3. 【中】tests.yml、repository-hygiene.yml 补显式 `permissions`，两个 release workflow 按 job 最小化权限（TS-1 / RH-1 / DR-5 / PY-3，1–2 PR）。
4. 【中】补 `concurrency`：tests（push 取消叠跑）、docker-release（按 tag 分组）（TS-3 / DR-3，1 PR）。
5. 【中】`pypa/gh-action-pypi-publish` 固定到具体 tag/SHA（PY-1，1 PR，可与 6 合并）。
6. 【低】全部 24 个 `uses:` SHA 固定 + 引入 Dependabot 维护（DR-4 / PY-4 / TS-6 / RH-4，1 PR）。
7. 【低】tests.yml paths 补 `scripts/**`、固定 pytest 版本（TS-4 / TS-7，1 PR）。
8. 【低】文档口径：更新 docker-release.yml:9 注释；在 CONTRIBUTING 或 docs-for-user 补 multi-worker vars（TS-5）与 pypi environment/Trusted Publisher（PY-5）的配置说明（1 PR，或并入导读轴）。

## 与其他轴的去重

- 本卡只覆盖 workflow 配置一致性；不含 guide-ci-workflows（CI 导读）、scan-secret-leak（代码内密钥）、scan-docker-compose-drift（compose 部署口径）。
- 密钥面仅 `secrets.GITHUB_TOKEN` 一处（docker-release.yml:84），属 workflow 配置口径；未发现自定义 secret 引用，代码内密钥归 scan-secret-leak 轴。

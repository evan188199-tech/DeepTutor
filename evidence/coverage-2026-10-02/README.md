# 覆盖率证据 · 2026-10-02（DT-21）

## 基线与运行环境

| 项 | 值 |
|---|---|
| 代码基线 | `origin/main` @ `ef2d9e5c3`（release: v1.6.12） |
| 日期 | 2026-10-02（本地时区 UTC-7） |
| Python | 3.13.13（独立 venv，未改动仓库 `.venv`） |
| pytest / pytest-cov / coverage | 8.4.2 / 7.1.0 / 7.16.2（pytest-asyncio 1.4.0） |
| Node / vitest / @vitest/coverage-v8 | v22.22.2 / 4.1.11 / 4.1.11 |
| 安装方式 | `pip install -e ".[dev]" + requirements/partners.txt`；`npm ci && npm i -D @vitest/coverage-v8@4.1.11`（均为临时目录内一次性安装） |

## 复跑命令（在仓库根目录执行）

后端（约 4.5 分钟，8674 collected）：

```bash
python -m pytest \
  --cov=deeptutor --cov=deeptutor_cli \
  --cov-report=term-missing:skip-covered \
  --cov-report=json:evidence/coverage-2026-10-02/backend/coverage.json \
  --cov-report=xml:evidence/coverage-2026-10-02/backend/coverage.xml \
  -q
```

前端（在 `web/` 下执行；include 显式列出源码目录，未被 import 的文件以 0% 计入）：

```bash
cd web && npx vitest run --coverage \
  --coverage.reporter=text --coverage.reporter=json-summary --coverage.reporter=json --coverage.reporter=html \
  --coverage.reportsDirectory=../evidence/coverage-2026-10-02/frontend/vitest \
  --coverage.include='app/**' --coverage.include='components/**' --coverage.include='features/**' \
  --coverage.include='hooks/**' --coverage.include='lib/**' --coverage.include='context/**' --coverage.include='shared/**' \
  --coverage.exclude='**/*.d.ts'
```

## 关键数字

- 后端：**75.69%** 行覆盖（97,437 / 128,732，缺失 31,295）；测试 **8615 passed / 55 skipped / 4 failed**（254.48s）。4 个失败为 origin/main 既有问题（3 例时区日期断言、1 例沙箱 runner exit 127），详见 `top15-gaps.md` 末尾。
- 前端：statements **28.11%**、branches **25.53%**、functions **23.62%**、lines **29.24%**（42,474 行）；856 个文件中 **397 个 0% 覆盖，共 19,814 条语句未被任何测试触碰**。

## 目录说明

| 文件 | 说明 |
|---|---|
| `top15-gaps.md` | **主产物**：按风险排序的 Top 15 测试空白清单（模块/原因/建议测试） |
| `backend/summary.md` / `backend/pytest.log` | 后端摘要 + 原始输出 |
| `backend/coverage.json.gz` / `backend/coverage.xml.gz` | 后端逐行明细（gzip 压缩，`gunzip` 后为 pytest-cov 原生格式） |
| `frontend/summary.md` / `frontend/vitest.log` | 前端摘要 + 原始输出 |
| `frontend/vitest/coverage-summary.json` | vitest json-summary（总计 + 每文件） |
| `frontend/vitest/coverage-final.json.gz` | istanbul 格式逐行明细 |
| `SHA256SUMS` | 以上全部文件的 SHA256 校验（自校验文件除外） |

未入库：vitest HTML 报告树（可再生资产，复跑上述命令即重新生成）；pytest 中途产物无。

## 备注

- 全程未修改任何源代码；仅新增本 `evidence/` 目录。
- 工作分支 `audit/coverage-gaps-20261003`（自 `origin/main` 新建 worktree），基线 commit `ef2d9e5c3`。

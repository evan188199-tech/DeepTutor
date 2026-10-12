# learner 学习进度 API 面盘点（AGEN-1857，配套上游 #1130）

基线：`origin/main @ 6cf793bd8`（v1.6.14），新 worktree + 新分支 `scan/learner-progress-api-parity`，产品代码零改动。

## 方法

1. 从 `deeptutor/api/main.py` 挂载表提取全部 router 前缀（637 条路由全量见 `routes-all.json`）。
2. 按 progress / record / journal / mastery / analytics / dashboard 等关键词过滤出学习进度/记录面，逐路由阅读 handler 与存储层。
3. 前端消费面对照 `web/lib/*-api.ts` 与 `web/lib/learning-dashboard.ts`。
4. 矩阵内全部 `path:line` 已逐一对照基线源码核验。

## 一句话结论

**单面进度能力完整（reading/mastery/practice/book/video 各自有读写端点），但"个人学习进度视图"需要的跨面聚合层只有半成品**：`GET /api/dashboard/learning-index` 只给入口清单不给进度数值，真正的进度数字由前端从 4 个列表端点自行拼装（`web/lib/learning-dashboard.ts:30-46`）。且全仓**没有学习时长、每日 streak、XP/徽章**任何存储或端点。上游 #1130 若要做聚合进度视图，缺的主要是后端聚合端点，而非底层记录。

## 矩阵与缺口

- `matrix.md` — 端点 × 能力矩阵（7 个面、34 条相关路由）
- `gaps.md` — 12 条缺口，逐条附 `path:line`
- `routes-all.json` — 637 条路由全量提取（file/line/method/route/handler/prefix）

## 去重说明

- `test-learning-records-20261004`（AGEN-441）：已覆盖 `/api/mastery-paths/reading/records` 的访问隔离/分页/鉴权回归测试；本卡为盘点，不重复补测，其结论（真实实现挂在 mastery-paths 而非 #1130 正文所写路径）已纳入矩阵。
- guide-learner / test-learner-profile：账号画像与守卫面，与本卡进度面不重叠。

## 测试命令

本卡为只读盘点，未运行测试套件；提取脚本仅读源码（grep/python ast 级），无网络、无服务器。

# web-zero-deep-20261009 — ConnectionsEditor 补测说明（AGEN-1192）

## 来源

- 上游扫描证据：`web/evidence/web-test-gaps-20261007/summary.json` zero 清单
  - `components/settings/ConnectionsEditor.tsx`（762 行，basis: no test file
    references this path or basename）
- 去重边界：
  - `test-web-multiuser-api` 卡测 multi-user API 客户端，与本卡无交集；
  - `web/tests/settings/settings-store.test.ts`（node:test，走 `npm run test:node`）
    覆盖 code-block 设置同步等 store 管道，无 connection 相关用例，不重复；
  - 本卡只测编辑器组件（挂真实 `SettingsProvider`，store 动作真实执行），
    `ProviderModelDiscovery` 探测面板以 stub 隔离（其网络行为不在本卡范围）。

## 产物

- `web/tests/settings/connections-editor.smoke.spec.tsx`（15 个用例，jsdom +
  @testing-library/react；网络访问全部经 mock 的 `@/lib/api`，不触网、不启动
  服务器）。

### 文件名说明

卡面原写 `web/tests/settings/connections-editor.smoke.test.tsx`。仓库 vitest
配置（`web/vitest.config.mts`）的 include 只匹配 spec 文件（`.test.ts` 走
`npm run test:node`，tsc 编译 + node:test，无 jsdom，跑不了组件）；仓库现无
任何 `.test.tsx`。为让测试真实被执行（验收要求 Vitest 通过），按仓库既有约定
命名为 `connections-editor.smoke.spec.tsx`，与同批
`tests/memory/memory-section.smoke.spec.tsx`（AGEN-1188）一致，语义与卡面相同。

## 覆盖点清单

1. 权限/失败分支：`/api/settings` 加载失败（mock 500）→ settingsError →
   "Backend unreachable" 面板，且不渲染 Add 按钮。
2. 权限/非编辑分支：catalog 为 null → "Model endpoints are assigned by your
   administrator" 面板，不渲染 Add 按钮。
3. 空态：无连接、无独立 profile → "No connections yet." + 引导文案 +
   Add 按钮；不显示 standalone 提示。
4. 空态：存在独立（未连接）profile → "Credentials are currently entered
   separately for LLM, Speech-to-Text."（CONNECTABLE_SERVICES 顺序 + ", " 连接）。
5. 行渲染：服务端掩码 `***` → "••••••••"；短 key（≤10 字符）→ 前 2 位 + "••••"；
   长 key → 前 5 位 + "••••" + 后 4 位；空 key → "No key"。已连接服务渲染为
   链接且 href 指向 `/<service>?profile=<id>`；未连接行显示 "Not supplying any
   service yet"（按行隔离断言）。chip 只来自该行 target 支持且未连接的服务
   （Primary 无 LLM/TTS chip，Aux 有 LLM/TTS/STT chip）。
6. 新增校验：Add 面板初始提交禁用；选 provider 后自动勾选全部支持服务并启用
   提交；Base URL placeholder 随 target 切换；全部取消勾选后再次禁用；
   llm 勾选未填 Model ID 时显示提示。
7. 新增成功：填 Base URL（含尾斜杠）/API Key/Model ID → 提交 → 连接创建
   （name 取 target label，base_url 仅去空白保留尾斜杠）、每服务生成连接
   profile（llm base 去尾斜杠、embedding 追加 /embeddings、dimension/
   send_dimensions 落值）、空缺服务成为 active → toast
   "Configured 3 services and made them active."，面板关闭，行与链接出现。
8. 新增保活：llm 已有独立 active profile 时再创建 → llm active 不被切换，
   toast "Configured 3 services — LLM kept your existing choice."。
9. 新增取消：Cancel 关面板，草稿零改动。
10. 编辑：Edit 展开表单回填现值；API Key 默认 password、Show/Hide 切换；
    Name/Base URL/API Key 修改即时写入 draft（行标题跟随）；discovery 入参
    断言（binding/base_url/api_key/connection_id/extra_headers/api_version，
    base_url 跟随输入不回落）；"Saving pushes these values…" 提示存在；
    连接字段修改不提前镜像进已连接 profile（保存才镜像，符合文案约定）；
    Done 收起。
11. 删除（已连接）：trash → 确认条显示 "Profiles it supplies keep their
    current credentials but stop following this connection."；Cancel 收起；
    再删 → 行消失、空态与 standalone 提示出现，profile 凭据被镜像
    （api_key/base_url）且 connection_id 摘除，active 指向不变。
12. 删除（未连接）：确认条显示 "Nothing is using this connection."，删除后
    行消失。
13. 行内连接服务：Embedding chip 点击 → 生成 embedding 连接 profile 并成为
    active → toast "Embedding now uses Primary."，chip 消失、出现指向新
    profile 的链接（href 含 profile id）。
14. 行内连接服务（非激活分支）：STT 已有 active profile 时点击 chip →
    新增 profile 但不切换 active → toast "Added a Speech-to-Text profile —
    switch to it on its own page."。
15. 中文：语言 zh-CN → standalone 列表用顿号连接（"LLM、语音识别"）、Add
    面板服务 chip 用中文标签（LLM/语音合成/语音识别）。

## 运行方式与结果

```
cd web
npx vitest run tests/settings/connections-editor.smoke.spec.tsx
# Test Files 1 passed, Tests 15 passed（约 1.5s；连续 3 次运行均稳定通过）
npx vitest run          # 全量回归：147 files / 668 tests 全部通过（含本卡新增 15 例）
npx eslint tests/settings/connections-editor.smoke.spec.tsx   # 0 问题
npx tsc --noEmit -p tsconfig.json                             # 0 错误
```

## 观察到的行为（非缺陷，供后续参考）

- `addConnection` 对 base_url 只做首尾空白裁剪，不剥离尾斜杠；连接本体保留
  `https://proxy.example/v1/`，而派生的连接 profile 会 `replace(/\/+$/,"")`
  去掉尾斜杠（embedding 再追加 `/embeddings`）。两者用途不同（连接原样存储、
  profile 拼端点），不构成缺陷，但值得知晓。
- 行内 chip 可用性由 `target.services[service]` 与是否已连接决定；connection
  的 provider 在 targets 中无对应项（fixture 中的 vertex）时无 chip、
  discovery 入参回落到 connection 自身字段，行为自洽。
- 测试夹具刻意区分服务端掩码 `***` 与本会话输入明文，避免把掩码显示逻辑
  误判为泄露路径。

## 边界确认

- 产品代码零改动（`git status` 仅新增测试与证据文件）。
- 未 merge、未部署、未改运行中的服务；工作在独立 worktree + 新分支
  `test/web-connections-editor-20261009`（基于 origin/main v1.6.14，
  6cf793bd868ba5ecbe64722936d4be8fab5a01df）。

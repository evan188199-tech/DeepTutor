# `web/lib/markdown-display.ts` 安全补测（失败测试集）

- 基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12）
- 分支：`test/markdown-display-security`（推送至 `myfork`）
- 测试文件：`web/tests/lib/markdown-display-security.test.ts`
- 日期：2026-10-03
- 对应覆盖率缺口：top15-gaps 第 14 项（206 缺失 / 40.3%）
- **未改任何产品代码**（`git diff ef2d9e5c3 -- web/lib` 为空）

## 运行方式

```bash
cd web && npm run test:node   # tsc -p tsconfig.node-tests.json + node --test 全量
```

## 结果

全量 `test:node`：**1246 tests / 1242 pass / 4 fail**。4 个失败全部是本卡新增的
"揭示缺口" 测试（刻意的失败测试，供修复卡领取）；其余 1242 个测试在基线上全绿，
本卡未引入任何意外回归。

单文件运行：

```bash
node -r ./scripts/register-node-test-aliases.cjs \
  --test dist/node-tests/tests/lib/markdown-display-security.test.js
# 12 tests / 8 pass / 4 fail
```

## 失败测试（修复卡的验收目标）

### 1. `escapeUnknownHtmlTagsForDisplay escapes an iframe whose srcdoc value contains markup`

- 样本：`<iframe srcdoc="<script>alert(1)</script>"></iframe>`
- 现状：输出为 `<iframe srcdoc="\`<script>\`alert(1)\`</script>\`">` —— 开标签
  **原样保留**在 code span 之外。
- 根因：`HTML_LIKE_TAG_REGEX`（`/ <\/?([A-Za-z][A-Za-z0-9_-]*)\b[^<>]*?\/?> /g`）的
  `[^<>]*?` 无法跨越属性值里的 `<`，整个 iframe 开标签匹配失败，不会被转义；
  而 rehype-raw（parse5，HTML 兼容分词）仍把它解析为**活的** `<iframe>` 元素并带上
  srcdoc 属性，react-markdown 会渲染该元素。

### 2. `escapeUnknownHtmlTagsForDisplay sanitizes handlers hidden behind a quoted '>'`

- 样本：`<a title="a>b" onclick="alert(1)">link</a>`、`<img src="x>y" onerror="alert(1)">`、
  `<details open ontoggle="a>b" data-x="1">body</details>`
- 现状：三个样本输出与输入**完全相同**（处理器零清洗）。
- 根因：同一 `[^<>]*?` 在引号内的 `>` 处提前截断标签匹配；`sanitizeAllowedHtmlTag`
  只清洗匹配片段，`>` 之后的 `on*=` 落在清洗范围外。parse5 会把引号内的 `>` 当作
  属性值字面量，整个串仍解析为**一个**带事件处理器的活标签。
- 影响：白名单标签（a/img/details…）经 `sanitizeAllowedHtmlTag` 后仍可携带
  `onclick`/`onerror`/`ontoggle`；react-markdown 对事件属性不做二次拦截。

### 3. `escapeUnknownHtmlTagsForDisplay keeps decoded percent-encoded markup inert`

- 样本：`safeDecodeURIComponent("%3Ca%20title%3D%22a%3Eb%22%20onclick%3D…")`
- 现状：一次解码后的标签经 escaper 原样输出（复现缺口 2）。
- 意义：锁定"解码产物重新进入展示管道后必须仍惰性"的二次解码安全契约。

### 4. `repairMalformedStrongEmphasis keeps plain text identical before and after repair`

- 不变式：修复前后"去掉 `**` 标记后的可见文本"必须逐字符一致，且 `**` 数量不变。
- 失败样本（现状把闭合标记内的空白改写成单个空格）：
  - `**A:  **b` → `**A:** b`（双空格折叠为单空格）
  - `**Label:\t**value` → `**Label:** value`（tab 被替换为空格）
  - `**Time:  **now **Ref:\t**1`（混合）
- 建议修法：把 `MALFORMED_STRONG_EMPHASIS_REGEX` 的 `[ \t]+` 捕获为分组并在替换中
  原样回填（`**$1**$2`），空白总量与种类即保持不变。

## 通过的守卫（修复时不得回归）

script/iframe/object/embed/svg 转义、大小写与属性变体、`<script >`、`<SCRIPT/SRC=…>`、
iframe 普通 src、允许标签剥离 on*/style/unsafe URL、`markdownUrlTransform` 拦截
`javascript:`（含大小写混淆、真实 tab、`data:text/html`、`data:image/svg+xml`、
`vbscript:`）并放行 https 与 img 栅格 data 图、`safeDecodeURIComponent` 全输入不抛错、
双重解码链 `%253C…` 终态惰性、`normalizeMarkdownForDisplay` 不做百分号解码、
`repairMalformedStrongEmphasis` 对奇数 `**`、已合法行、代码块/行内代码/数学守恒逐字节不变。

## 修复卡提示

- 两个 XSS 缺口同根：`HTML_LIKE_TAG_REGEX` 不感知引号内 `<`/`>`。修复方向是让标签
  匹配感知引号包裹的属性值（如 `(?:"[^"]*"|'[^']*'|[^<>"'])*?`），使整标签落入
  `sanitizeAllowedHtmlTag`；或对未匹配完整的 `<tag …` 残段直接转义。
- 修复后本卡 4 个失败测试转绿、1246 全绿即为验收；不得改动上列守卫样本的行为。

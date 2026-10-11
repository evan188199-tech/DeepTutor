# 前端漂移矩阵（`resolveTextSelectors` @ `web/lib/reading-w3c-annotations.ts`）

对真实模块直接实测（`frontend_results.json`）。前端没有持久化环节：
返回 `null` 的行在页面上被静默丢弃（不画高亮），标注仍留在列表里。

| 场景 | 输入 | 结果 |
| --- | --- | --- |
| stale_position_unique_quote | position 过期 + quote 唯一 | anchored——按 quote 重锚，prefix/suffix 以 10 字符窗口重建 |
| duplicate_no_context | quote 重复、无 context | null（不画）——与后端 ambiguous 一致 |
| duplicate_context_distinguishes | quote 重复、context 可区分 | anchored——锚到 context 命中的那份 |
| stale_context_duplicate | quote 重复、存储 context 已过期 | null——过期 context 与两份都不匹配，回退 raw 计数 2；与后端 G2 复合失效同构 |
| stale_position_whitespace_variant_accepted | position 仍覆盖 normalize 等价的空白变体 | anchored——position 优先（现有单测已覆盖，属既定行为） |
| word_extended_partial_word | fox→foxes | **anchored 且词内半截**——与后端 G1 同一正则缺陷的客户端复现 |
| case_change | quick→Quick | null——大小写敏感 |
| regex_metacharacters | quote 含 `.(±)[]` | anchored——`escapeRegExp` 正确转义 |
| legacy_quote_only_unique | 无 selector、quote 唯一 | **anchored**——`annotation.quote` 兜底生效 |
| legacy_quote_only_duplicate | 无 selector、quote 重复 | null |
| moved_quote_stale_context_unique | 换环境 + position/context 全过期、quote 唯一 | anchored——raw quote 兜底 |

## 与后端的关键差异

1. **旧行处理相反（G9）**：后端把无 selector 行一刀切 unresolved
   （`store.py:1267-1273`）；前端 `resolveTextSelectors` 用 `annotation.quote`
   兜底（`reading-w3c-annotations.ts:48-52`），quote 仍唯一时能正常锚定。
   同一行数据在列表里显示 "Not found"，在页面上却（若无 resolution 过滤）
   本可渲染——两个层面给出矛盾信号。
2. **前端每次渲染重建 prefix/suffix**（`quoteAt`，10 字符窗口），但结果不
   回写后端，后端存储的 context 因此永远不会被前端修正（G2 的另一半）。
3. **渲染即验证**：position 只有在 slice normalize 等于 quote 时才被采信，
   否则回退 quote 匹配；唯一性不足即 null。这条防线使后端侧的过期 position
   不会直接导致错画——但 null 行（unresolved/ambiguous）在页面上无任何
   痕迹，只有列表徽章（`AnnotationList.tsx:168-179`）。

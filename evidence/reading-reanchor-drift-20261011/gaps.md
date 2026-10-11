# 缺口清单：阅读 selector 再锚定漂移健壮性

基线：`origin/main` @ `6cf793bd8`（v1.6.14）。每条含位置与中性复现条件；
所有复现均可由本目录 fixture 离线重现（无服务、无网络、不改源码）。
按影响排序。

## G1 词扩展时锚进词内（后端+前端同源缺陷）

- 位置：`deeptutor/reading/store.py:141`（`_find_all_quote_spans` 的
  `\s+`-join 正则，无词边界；`_find_quote_span` `store.py:107` 同）；
  `web/lib/reading-w3c-annotations.ts:171`（`occurrences` 同一模式）。
- 复现：标注 quote 为 "quick brown fox"；修订把后续词变成其前缀的扩展词
  （"fox" → "foxes"）。迁移报 resolved，stored quote/position 被改写为
  "foxes" 内的前 3 个字符。实测：backend `word_extended`（partial_word=true）、
  frontend `word_extended_partial_word`（partial_word=true）。
- 影响：高亮覆盖残词，stored quote 与可见词不再一致；后续修订的 context
  校验也建立在这个坏 span 上。

## G2 迁移后 prefix/suffix context 永不刷新，漂移跨修订累积

- 位置：`deeptutor/reading/store.py:1283`——`dataclass_replace(quote_selector,
  exact=canonical_exact)` 仅更新 exact；前端虽在渲染时重建 context
  （`reading-w3c-annotations.ts:148-159`）但不回写存储。
- 复现：①修订在 quote 前改写文本 → resolved 但 prefix_stale=true；
  ②下一次修订复制该 quote → stale context 与两份都不匹配 → ambiguous，
  而新鲜 context 本可消歧。实测：backend `stale_context_compound`
  （resolved@rev2 → ambiguous@rev3，此后钉死）。
- 影响：context 是唯一消歧手段，单向老化使重复文本（常见于网页改版的
  重复段落/页眉）在第二次漂移即降级为 ambiguous 且无法自愈。

## G3 跨单元不应用 context 消歧，也没有原 locator 邻近先验

- 位置：`deeptutor/reading/store.py:1275-1279`——匹配按单元分别调用
  `_find_all_quote_spans`（context 过滤只在单元内部生效，
  `store.py:129-144`）后聚合计数；标注原有 locator 未参与打分。
- 复现：quote 位于单元 2 且带有效 context；修订把同一句复制进单元 1
  （无该 context）。单元 1 返回 raw 命中、单元 2 返回 contextual 命中，
  聚合 2 个 → ambiguous。实测：backend `duplicate_across_units`。
- 影响：单元间的重复文本（目录/摘要/页眉类漂移）即使 context 可明确
  指认正确单元，仍被判 ambiguous；contextual 命中被 raw 命中稀释。

## G4 无 selector 的历史行被一刀切 unresolved，`Annotation.quote` 未被利用

- 位置：`deeptutor/reading/store.py:1267-1273`——只检查
  `row.selectors` 中的 `TextQuoteSelector`，从不读取 `row.quote`
  （`deeptutor/reading/models.py:375`）。
- 复现：selector 出现之前保存的标注（仅 quote 字段）；任意一次修订后，
  即使 quote 在新文本中逐字唯一存在，行也被标 unresolved。
  实测：backend `legacy_quote_only_survives`。
- 影响：存量标注在首次修订时集体失活；与前端行为直接矛盾（见 G9）。

## G5 unresolved 行保留越界 locator

- 位置：`deeptutor/reading/store.py:1306-1308`（及 1271）——unresolved
  行保留原 locator，未按新 unit_count 收敛或标记越界状态。
- 复现：标注位于单元 3；修订删除单元 3（unit_count 3→2）→ 行为
  unresolved 且 locator=3 越界。实测：backend `unit_removed`
  （三种行形全部 OOR）。
- 影响：列表按 locator 分组展示一个已不存在的单元号
  （`web/components/reading/AnnotationList.tsx:106-110`），点击跳转目标
  页不存在；不崩溃，但审查入口指向空处。

## G6 `refresh_document` 提 revision 但不做任何 selector 校验/再锚定

- 位置：`deeptutor/reading/store.py:440-603`（revision 在 568 递增，
  annotations 在 582-585 原样拷贝；`_reanchor_annotations` 全仓唯一调用点
  是 `store.py:753` 的 `ingest_units`）。
- 复现：对已标注材料执行 re-extract（unit_count 不变、单元内文本因
  更好的文本层而变化）→ manifest.revision+1，annotations 的 selectors、
  resolution、material_revision 全部原地不动。
- 影响：两条 revision 路径语义分叉——URL 快照路径会再锚定，本地上传
  refresh 路径不会；refresh 造成的文本漂移对 stored 状态完全不可见
  （渲染期前端逐次校验缓解了错画，但 resolution 仍显示 resolved，
  G2 的 context 老化同样在该路径上无检查地累积）。

## G7 匹配大小写敏感、Unicode 归一化敏感

- 位置：`deeptutor/reading/store.py:141`（无 re.IGNORECASE、无 NFC/NFKD
  折叠）；`web/lib/reading-w3c-annotations.ts:165-176` 同。
- 复现：抽取器输出大小写变化（quick→Quick）或 NFC→NFD 分解
  （café → cafe+U+0301）→ 匹配失败 → unresolved。
  实测：backend `case_change`、`unicode_nfd_drift`。
- 影响：纯再编码层面的差异被当成内容漂移；换抽取器或上游站点改字体
  大小写约定即触发批量失活。

## G8 页内无审查/修复入口，unresolved 标注在正文静默消失

- 位置：后端 docstring 承诺 "the reader can show an explicit review state"
  （`deeptutor/reading/store.py:1236-1238`）；实际仅列表徽章落地
  （`web/components/reading/AnnotationList.tsx:168-179`），正文渲染直接
  丢弃无法锚定的行（`web/components/reading/TextUnitView.tsx:309-314`
  过滤 `toRecogitoTextAnnotation` 的 null），`resolution` 字段在 ReaderPane
  无任何消费。
- 复现：标注后修订页面使 quote 消失/重复 → 列表出现 "Not found"/
  "Ambiguous" 徽章；正文无痕迹；无"重新选中正确段落以修复"的流程。
- 影响：review state 名义存在、实际止步于列表；ambiguous 标注没有任何
  用户可操作的自愈路径，与 G2 叠加后只会持续恶化。

## G9 前后端对无 selector 行为矛盾（G4 的另一面）

- 位置：后端强制 unresolved（`store.py:1267-1273`）；前端
  `resolveTextSelectors` 以 `annotation.quote` 兜底并接受唯一匹配
  （`web/lib/reading-w3c-annotations.ts:48-52`）。
- 复现：同一 legacy 行：列表徽章 "Not found"（后端 resolution），
  而前端锚定逻辑对同一数据返回有效 selector。
  实测：frontend `legacy_quote_only_unique`（anchored=true）对照
  backend `legacy_quote_only_survives`（unresolved）。
- 影响：两层信号冲突；由于后端永远不迁移这些行，"Not found" 状态
  在后续每次修订中都持续存在，即使 quote 一直唯一。

## 已确认的稳健面（非缺口，防止误报）

- 无漂移/纯空白重排/段落插入/句子跨单元搬移：resolved 迁移正确，
  locator 与 position 同步更新。
- quote 真消失 → unresolved；同单元重复且无 context → ambiguous；
  均不会画到错误段落。
- 修订前状态完整归档到 `revisions/000001/`（含标注副本）供审计
  （`store.py:721-736`）。
- 渲染期 position 校验（前端）阻止过期 position 直接错画。

# 后端漂移矩阵（`_reanchor_annotations` via `ingest_units`）

所有行均为 fixture 实测（`backend_results.json`），非推断。
基础文档：3 单元；标注默认带 quote+prefix(10 字符)+suffix(10 字符)+position。
`partial_word` = 锚定 span 边界落在词内；`prefix/suffix_stale` = 迁移后存储的
上下文与新文本不再吻合；`OOR` = locator 超出新 unit_count；
`POS_MISMATCH` = 未迁移行的旧 position 与新文本不符（预期内，仅记录）。

| 场景 | 漂移 | 标注 | 迁移后行为 |
| --- | --- | --- | --- |
| control_unchanged | 无（原样重 ingest） | a_title / a_mid | 均 resolved，locator 不变，revision 1→2，context 未过期 |
| whitespace_reflow | 空格翻倍 | a_mid | resolved，position 更新到新偏移（空白不敏感匹配生效） |
| title_edited | 标题追加 "(Revised)" | a_title / a_mid | a_title resolved——quote 作为子串锚进新标题尾部，suffix_stale；a_mid resolved，prefix_stale |
| paragraph_inserted_before | quote 前插入新段落 | a_mid | resolved，position 正确后移；stored prefix 指向旧邻接文本（prefix_stale，**未刷新**） |
| paragraph_deleted | 删除 quote 所在段落 | a_end / a_mid | a_end unresolved（revision 钉在 1，旧 position 留存，POS_MISMATCH）；a_mid resolved |
| word_replaced | quick→swift | a_mid | unresolved（正确拒绝） |
| word_extended | fox→foxes | a_mid | **resolved 但锚进词内**：span 覆盖 "foxes" 的前 3 字符（partial_word），suffix_stale |
| duplicate_same_unit | 同单元内句子复制 | a_ctx（带 context）/ a_noctx（仅 exact） | a_ctx resolved——context 在单元内消歧成功；a_noctx ambiguous |
| duplicate_across_units | 句子从单元 2 复制进单元 1 | a_u2（带 context，位于单元 2） | **ambiguous**——单元 1 命中 raw、单元 2 命中 contextual，聚合计数=2；跨单元不应用 context，亦无原 locator 邻近先验 |
| sentence_moved_across_units | 句子从单元 2 搬到单元 3 | a_u2 | resolved，locator 2→3（跨单元迁移本身可用），context 全部过期未刷新 |
| unit_removed | 删除单元 3（3→2） | a_gamma / a_legacy_u3 / a_posonly_u3 | 三种行形全部 unresolved 且 **locator=3 越界**（OOR），revision 钉在 1 |
| legacy_quote_only_survives | 加引言段；quote 仍逐字唯一存在 | a_legacy（无 selector） | **unresolved**——无 TextQuoteSelector 的行一律不尝试用 `Annotation.quote` 再解析 |
| stale_context_compound | 两步：①quote 前改写 ②复制 quote | a_mid | ①resolved 但 prefix_stale；②**ambiguous**（stale context 与两份都不匹配，新鲜 context 本可消歧）；revision 钉在 2 |
| case_change | quick→Quick | a_mid | unresolved（大小写敏感） |
| unicode_nfd_drift | café 由 NFC 变 NFD | a_nfc | unresolved（无 Unicode 归一化） |

## 解读

1. **保守失败方向正确**：漂移导致无法唯一定位时一律 unresolved/ambiguous，
   不会把标注画到错误段落；未迁移行保留旧 locator+旧 revision 供审计
   （旧修订副本由 `REVISIONS_DIR` 承载）。
2. **两类真实的错误锚定（非保守失败）**：
   - 词扩展（G1）：`fox`→`foxes` 时 quote 匹配进词内，stored quote 被改写成
     半个词。
   - 标题扩展（title_edited）：quote 锚进新标题的子串，语义上标注不再是
     "整个标题"，但这是 quote 锚定的固有边界行为，危害低于 G1。
3. **漂移是单向累积的**（G2/G3）：每次成功迁移只更新 `exact` 与 position，
   prefix/suffix 保持旧值；context 越用越旧，第二次漂移即可把本可消歧的
   标注打成 ambiguous，且此后永远停在 ambiguous（无再修复路径）。
4. **旧行一刀切**（G4）：`Annotation.quote` 字段在再锚定路径中完全未被使用；
   无 selector 的历史行即便 quote 仍唯一存在也直接 unresolved。

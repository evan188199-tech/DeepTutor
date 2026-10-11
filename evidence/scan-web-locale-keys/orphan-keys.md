# 孤儿 key 清单（locale 文件有但代码不用）

定义：不在任何 t() 字面量中的目录 key。confirmed = web 源码+tests 全文（含动态引用）均无该字符串出现；guarded = 有裸字符串命中（可能经动态 map/测试引用，删除前需人工核对）。

## 计数

| locale | 目录 key | 孤儿候选 | confirmed | guarded |
|---|---|---|---|---|
| en | 5507 | 1479 | 750 | 729 |
| zh | 5507 | 1479 | 750 | 729 |
| fr | 5887 | 1910 | 1407 | 503 |
| de | 5507 | 1479 | 750 | 729 |
| uk | 5523 | 1479 | 750 | 729 |
| pl | 5523 | 1479 | 750 | 729 |

- uk/pl 相对 en 多出的 16 个 key 全部是 `_few`/`_many` 复数形式（基 key 在用，非真孤儿）。
- fr 相对 en 多出 909 个 fr-only key（en 已删除的历史 key），全部属于 fr 目录孤儿。
- confirmed 样例：`"(untitled chat)"`、`"{{count}} books_one"`、`"(no question)"` 等，全量见 orphan-keys.json（guarded 字段 false）。

## common.json 文件级孤儿

- web/i18n/init.ts 只加载 app.json；locales/{en,zh,de,fr}/common.json（各 37 key）从未被加载，且 37 个 key 全部已重复存在于同 locale app.json → 4 个文件共 148 个 key 实例为文件级孤儿。
- pl/uk 无 common.json（fix-web-locales-parity 计划补齐的目标文件本身未接线）。

全量明细：orphan-keys.json（en_orphans[].guarded 区分两档；extra_vs_en 给出 fr/uk/pl 相对 en 的多出 key）。
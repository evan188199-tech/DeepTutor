# evidence: services/persona 存取单元测试（AGEN-1040）

日期：2026-10-07　基线：origin/main `f07029cfc`（release v1.6.13）　分支：`test/persona-store-unit-20261007`

## 变更范围

- 新增 `tests/services/persona/test_persona_store_roundtrip_resilience.py`（18 个用例）。
- 不改任何产品代码；不改动已有测试文件 `tests/services/persona/test_persona_service.py`。

## 场景覆盖（对应验收三类路径）

1. 读取/保存往返（5 例）
   - `test_create_read_roundtrip_preserves_name_and_description`：create 后落盘文件 frontmatter 与 get_detail 一致。
   - `test_create_normalizes_slug_and_strips_description`：名称归一为小写 slug、描述去空白，任意大小写可查。
   - `test_update_content_roundtrip_rewrites_frontmatter`：update 携带外来 frontmatter 时重写为规范 name/description，body 保留。
   - `test_full_lifecycle_roundtrip`：create → list → update（Unicode 描述）→ rename → delete 全链路，to_dict/read_only 断言。
   - `test_list_descriptions_match_detail`：list 与 get_detail 的 description 一致。
2. 默认值回退（6 例）
   - 根目录不存在时 `list_personas` 返回空；`load_for_context` 对非法名（含路径样式）返回空串；空 body persona 渲染为空串。
   - 无 frontmatter / 缺 description 键时 description 回退为空串、body 仍可渲染。
   - `PRESETS_DIR` 不存在时 `seed_presets` 返回空（monkeypatch）。
3. 损坏数据容忍（7 例）
   - frontmatter YAML 非法（未闭合流序列）、解析为非 dict（列表）、`null`：均不抛错，description 回退空串，body 保留。
   - `list_personas` 跳过：无 PERSONA.md 的目录、根下散文件、PERSONA.md 为目录（OSError）的条目；空文件可列出且渲染为空。
   - rename 撞名抛 `PersonaExistsError` 且原 persona 完好；delete/get 不存在抛 `PersonaNotFoundError`；非法 rename 抛 `InvalidPersonaNameError`。

## 命令与数字

```bash
# macOS 无 timeout，用 perl alarm 900 实现等价 900s 硬限时
perl -e 'alarm shift; exec @ARGV' 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/services/persona/
# → 32 passed in 0.26s（新 18 + 已有 14）

perl -e 'alarm shift; exec @ARGV' 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/services/persona/test_persona_store_roundtrip_resilience.py
# → 18 passed in 0.24s

.venv/bin/python -m ruff check tests/services/persona/          # All checks passed!
.venv/bin/python -m ruff format --check tests/services/persona/ # 2 files already formatted
```

## 结论

32/32 全绿，三类路径全覆盖，无产品代码改动。

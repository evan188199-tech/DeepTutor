# 仍可领取种子清单（still-claimable 2026-10-11）

口径：drift-conclusions-20261011.md 中结论为「仍可领取」的种子，共 17 条，供下轮 harvest 直接取用；领卡前按当日看板再做一次快照复核。

| ID | 轴 | 模块/主题 | LOC | fanin | 测试焦点/备注 |
|---|---|---|---:|---:|---|
| E14 | E | #14 NO-CODE：~597 处纯文本 detail 无机器可读 code | - | - | 子集卡在案（AGEN-1364 sessions.py、AGEN-880 web 解析层），主项系统性 code 信封仍无卡 |
| FZ51 | F | `capabilities.reading._tool_base` | 86 | 2 | - |
| FZ92 | F | `__version__` | 11 | 2 | 相关卡（不去重）：verify-citation-version-parity；仅有 guide/scan/verify 级相关卡，不构成去重 |
| FZ94 | F | `book.errors` | 8 | 2 | - |
| FZ95 | F | `__main__` | 6 | 0 | - |
| FZ96 | F | `services.llm.provider_registry` | 3 | 0 | 相关卡（不去重）：AGEN-1265,guide-provider-registry；仅有 guide/scan/verify 级相关卡，不构成去重 |
| FT35 | F | `video_learning.invidious_account_storage` | 177 | 1 | AGEN-806 覆盖 invidious_account(.py)+client，storage.py 未含 |
| FT46 | F | `book.overview_copy` | 104 | 1 | - |
| FT50 | F | `services.imagegen.adapters.openai_compat` | 98 | 1 | 仅有 guide/scan/verify 级相关卡，不构成去重 |
| FT75 | F | `textbook_struct.page_headers` | 100 | 2 | ★AGEN-1315 焦点见 seed-ledger.md；AGEN-791 称 page_headers 现有测试，领取前 fresh 复扫确认触达数 |
| FT115 | F | `services.session.attachment_parsing` | 158 | 1 | - |
| FT116 | F | `services.config.settings_presets` | 135 | 1 | AGEN-1240 为 web lib settings-presets，非本后端模块 |
| FT120 | F | `agents.visualize.agents.code_generator_agent` | 117 | 1 | AGEN-1344 仅 math_animator 同名代理，visualize 侧无卡 |
| FT122 | F | `agents.research.utils.json_utils` | 94 | 1 | - |
| FT129 | F | `services.codex_auth.client_version` | 55 | 1 | AGEN-1009 文件清单（oauth/service/storage/catalog）不含 client_version.py |
| FT133 | F | `services.session.turns.resource_reuse` | 18 | 1 | - |
| FT139 | F | `reading.study_guidance` | 103 | 0 | - |


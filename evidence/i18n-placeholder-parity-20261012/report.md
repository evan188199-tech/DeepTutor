# i18n placeholder / interpolation parity scan

- Repo root: `/private/tmp/multica-task-1892156986/opencode/dt-agen1832-i18nph-wt`
- Scanned HEAD: `6cf793bd868ba5ecbe64722936d4be8fab5a01df`
- Syntax by surface: `backend.*` uses Python `str.format` placeholders (`{name}`, `{name!r}`); `web.locales.*` uses i18next `{{name}}`.
- Comparison rule: per key, every language is diffed against the `en` entry (or the first language when `en` is absent): `missing` = in reference but not in this language, `extra` = the reverse.

| surface | syntax | keys | compared (>=2 langs) | single-lang keys | findings |
|---|---|---|---|---|---|
| `backend.messages` | str.format | 37 | 37 | 0 | 0 |
| `backend.metadata` | str.format | 17 | 17 | 0 | 0 |
| `backend.status` | str.format | 22 | 22 | 0 | 0 |
| `web.locales.app` | i18next | 6424 | 5523 | 901 | 1 |
| `web.locales.common` | i18next | 37 | 37 | 0 | 0 |

Total findings: **1**

## web.locales.app — key `“{{title}}” and its reading conversations will be deleted. The {{count}} materials in it stay in your library._one`
- `zh` vs `en`: extra `{count}`.
  - en: `web/locales/en/app.json:3582` → `{"title": ""}`
  - zh: `web/locales/zh/app.json:3582` → `{"count": "", "title": ""}`

Re-run:
```bash
python3 evidence/i18n-placeholder-parity-20261012/scan_i18n_placeholders.py --repo-root .
```

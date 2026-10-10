# Secret-defaults & debug-config hygiene scan — deeptutor

- Generated: 2026-10-11 (UTC) · read-only static scan, no code changes
- Revision: `origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df` (release: v1.6.14)
- Scope: hardcoded default credentials / sample keys; debug or permissive configuration enabled by default; key-file on-disk locations and permissions; call sites that may log key fragments.
- Scanner: `scan_secret_defaults.py` (this directory); raw triage input in `findings.candidates.json`; graded results in `findings.json`.
- Detail policy: this report carries locations and neutral risk descriptions only; triage detail travels as a private attachment to the card, not in this branch.

## Dedup (referenced, not re-reported)

| Prior work | Relationship |
|---|---|
| scan-log-exception-bodies | Exception-body leakage in log/error messages — the two overlapping sites found here are dedup-marked under I7, not counted. |
| fix-provider-body-leak (`myfork/fix/provider-body-leak` @ a8618a063) | Provider response bodies kept out of user-facing errors — referenced under I7. |
| test-secret-files (`myfork/test/secret-files-helpers-20261009`) | Unit coverage of the `secret_files` helper contracts — referenced under I4. |

## Summary

| Severity | Count |
|---|---|
| 🔴 high | 1 |
| 🟠 medium | 3 |
| 🟡 low | 4 |
| 🔵 info | 7 |

Top risk pattern (H1 + M1 + L2 combined): the shipped compose files publish the backend, frontend and PocketBase ports on all host interfaces while authentication defaults to disabled and CORS matches any origin in that mode — the default deployment posture is network-reachable unauthenticated API access rather than the loopback-only posture `.env.example` describes.

## Findings

### 🔴 High — 1

| ID | Rule | Location | Neutral description |
|---|---|---|---|
| H1 | compose-ports-published-on-all-interfaces | docker-compose.yml:55,85-86 · docker-compose.ghcr.yml:65-66 | Port mappings lack loopback prefixes, so services bind all host interfaces by default; `.env.example` documents the host side as loopback and the codex-oauth overlay does prefix 127.0.0.1, but the base files do not. With auth off by default this exposes the API (including settings surfaces where provider keys are entered) to the network out of the box. Direction: default host mappings to loopback; wider binding only by explicit opt-in. |

### 🟠 Medium — 3

| ID | Rule | Location | Neutral description |
|---|---|---|---|
| M1 | cors-permissive-when-auth-off | deeptutor/api/main.py:95 | `allow_origin_regex` matches any http(s) origin whenever auth is disabled (the default); amplifies H1. Explicit-origins mode exists once auth is enabled. |
| M2 | fastapi-docs-endpoints-ungated | deeptutor/api/main.py:404 | Docs/redoc/openapi.json are not disabled and router auth dependencies do not cover them, so the full route schema stays reachable even with AUTH_ENABLED=true. |
| M3 | secret-bearing-state-file-default-mode | deeptutor/services/partners/web_continuity.py:94 | Web-continuity state containing a session_key is persisted via plain `write_text` + rename, inheriting umask mode (typically group/world-readable) instead of the owner-only mode every other secret store enforces (I4). |

### 🟡 Low — 4

| ID | Rule | Location | Neutral description |
|---|---|---|---|
| L1 | cookie-secure-default-false | deeptutor/services/config/runtime_settings.py:87 · deeptutor/api/routers/auth.py:36 | Session cookie issued without `Secure` (SameSite lax fallback) unless opted in; weaker on non-loopback HTTP deployments. |
| L2 | auth-disabled-by-default | deeptutor/services/config/runtime_settings.py:83 · deeptutor/services/auth.py:4 | Deliberate, documented localhost-first default; multiplier that turns H1/M1 into default unauthenticated network exposure. |
| L3 | tls-verify-bypass-sites | deeptutor/services/llm/openai_http_client.py:102,153 · deeptutor/services/config/context_window_detection.py:138 | Opt-in (default off, prod-refused, warned) TLS bypass for provider traffic; non-prod opt-in still sends provider credentials over unverified TLS. |
| L4 | stop-token-file-default-mode | deeptutor/runtime/launcher.py:1315 | Detached-launcher stop token written with umask-derived mode while the sibling state file uses an owner-only atomic write; local-only surface. |

### 🔵 Info — 7

| ID | Rule | Location | Neutral description |
|---|---|---|---|
| I1 | keyless-sentinel-default | 11 sites (system.py:482; provider_runtime.py:924,1245,1299,1340,1381; pageindex/client.py:80; embedding openai_compatible.py:48, openai_sdk.py:48; settings_spec.py:542; agentic/client.py:168) | `sk-no-key-required` sentinel for keyless local endpoints; treated as non-secret by doctor.py. |
| I2 | default-bootstrap-admin-username | runtime_settings.py:84 | Default seeds username `admin` with an empty hash that cannot authenticate; no default password. |
| I3 | no-hardcoded-key-literals | — | Zero provider-shaped literals and zero secret-valued env defaults in non-test source; fixture/ locale/ banner false positives triaged out. |
| I4 | secret-store-inventory | secret_files.py:9; mcp/secrets.py:54,178; identity.py:103; skill/credentials.py:27; codex_auth/service.py:1201; invidious_account_storage.py:22; model_catalog.py:292; partners/manager.py:612 | All inventoried stores enforce owner-only modes or owner-private trees (0600/0700, owner-only temp creation, rename-relocation into `data/system/<owner>/private`); model catalog holds plaintext provider keys at `data/user/settings/model_catalog`, owner-only mode and outside the sandbox-runner mounts; partner channel secrets plaintext at rest in `data/partners/<id>/config.yaml`, masked in read APIs. Only M3/L4 deviate. |
| I5 | sandbox-subprocess-default-on | runtime_settings.py:37 | Restricted-subprocess exec on by default (documented tradeoff; stronger backends take precedence). |
| I6 | redaction-helpers-present | doctor.py:325; provider_factory.py:22; gemini.py:121; partners/manager.py:128; settings_profile.py:155; mcp/manager.py:605; codex_auth/service.py:865 | Active redaction/masking helpers verified. |
| I7 | no-key-value-logging-confirmed | — | 44 AST candidates triaged, none prints a credential value; two exception-body sites dedup-marked to scan-log-exception-bodies (pocketbase_client.py:160; dingtalk.py:249 — the latter also misuses `{}` placeholders with stdlib logging); provider-body axis belongs to fix-provider-body-leak. |

## Method & reproducibility

1. `python3 evidence/scan-secret-defaults/scan_secret_defaults.py` — regex/AST passes over non-test source (`findings.candidates.json`, 442 candidates: A2 70, B 11, C1 317, D1 44).
2. Manual triage of every A/B/D candidate and of C-axis write sites that carry credential payloads; graded results in `findings.json` (this report renders them).
3. Cross-checked compose overlays and `.env.example` for the binding claims in H1; verified guardrails (prod refusal, warnings) for L3 by reading the gating helper.

## Verdict

No hardcoded credentials, sample keys, or key-logging call sites in default configuration. The actionable surface is configuration exposure by default (H1/M1/M2) plus two file-mode outliers (M3/L4); secret storage and log redaction elsewhere follow a consistent owner-only discipline.

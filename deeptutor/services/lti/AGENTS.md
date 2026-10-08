# AGENTS.md — LTI 1.3 integration (first slice)

Upstream tracking: HKUDS/DeepTutor#567. This is the **minimal launch
skeleton**: platform-initiated SSO into DeepTutor, config-gated and off by
default. It was scoped after a feasibility review; the phasing below records
what is deliberately *not* here yet.

## What exists here

| Piece | File | Notes |
|---|---|---|
| OIDC login init | `service.py` (`LtiService.begin_login`) | validates `iss`/`client_id`/`target_link_uri`/`lti_deployment_id` against the registration, issues single-use `state` + `nonce` |
| Launch validation | `service.py` (`LtiService.complete_launch`) | consumes `state`, verifies the `id_token` (RS256 only, `kid` → platform JWKS), checks `iss`/`aud`/`exp`/`iat`, `nonce` binding, message type, deployment id, target link uri |
| Identity mapping | `provisioning.py` | `lti-<sha256(issuer\|sub)[:32]>` local username, JIT-provisioned on first launch |
| HTTP routes | `deeptutor/api/routers/lti.py` | `GET/POST /api/lti/login`, `POST /api/lti/launch` |
| Config | `deeptutor/services/config/runtime_settings.py` (`lti.json`) | same runtime-settings pattern as `auth.json`/`integrations.json`; env override `LTI_ENABLED` |

## Invariants — keep these when evolving the code

1. **Default-off equivalence.** With `enabled=false` (the default) or no
   platform registered, every `/api/lti` route returns 404 and nothing else in
   the system changes. The router is also dark when built-in auth is disabled
   or PocketBase mode is active — LTI must never be a side door around the
   configured auth mode.
2. **Never admin.** JIT provisioning only creates `teacher`/`student`
   accounts (`deeptutor/multi_user/identity.py::provision_external_user`
   rejects `admin`), and a launch into an account that was *manually* elevated
   to admin is refused. Role is fixed at first provisioning; re-launches do
   not drift it.
3. **No password login.** Provisioned accounts carry an unusable hash marker
   (`!` + random hex); their identity is re-established by the platform on
   every launch.
4. **Session reuse, not a new session system.** A successful launch calls the
   normal `create_token` + `dt_token` cookie path, so downstream auth is
   exactly the same as a password login.
5. **Launch rejects loudly, reflects nothing.** Error responses carry a
   stable code (`invalid_state`, `unknown_signing_key`, …) never platform
   input; details stay in server logs.
6. **State is single-use, in-process.** Pending login states (state → nonce,
   target, issuer) live in memory with a 10-minute TTL and a hard cap, fine
   for the default single-worker deployment. If DeepTutor grows multi-worker
   by default, this store must move to shared storage before LTI is enabled
   there.

## Configuration (`data/user/settings/lti.json`)

```json
{
  "version": 1,
  "enabled": true,
  "platforms": [
    {
      "issuer": "https://lms.example.edu",
      "client_id": "deeptutor-client-1",
      "deployment_ids": ["deployment-7"],
      "auth_login_url": "https://lms.example.edu/mod/lti/auth.php",
      "target_link_uri": "https://deeptutor.example.edu/app",
      "key_set_url": "https://lms.example.edu/mod/lti/certs.php"
    }
  ]
}
```

`key_set_url` is fetched with a 15-minute cache; alternatively an inline
`key_set` (JWKS object) can be pinned for offline deployments. Invalid
entries are dropped at load; an empty `platforms` list keeps LTI disabled.

Deployment prerequisite for iframe launches: HTTPS with
`auth.json` `cookie_secure=true`, otherwise browsers refuse the
`SameSite=None` cookie the in-iframe launch needs.

## Tests

* `tests/services/lti/` — login-init validation, launch validation (mock
  IdP: per-test RSA key, inline `key_set`, `python-jose` signing — fully
  offline), provisioning.
* `tests/api/test_lti_router.py` — route surface: 404-when-disabled, full
  login → launch → cookie round trip.

## Not in this slice (deferred phases)

* Tool-side JWKS endpoint + deep linking (Phase 2)
* AGS grade passback, NRPS names/roles (Phase 3 — re-review before touching:
  it moves grade data)
* `pylti1p3next` adoption (its FastAPI adapter does not exist yet; revisit
  when it lands — see the feasibility memo referenced in #567)
* Iframe cookie fallback (top-level window / session handoff)

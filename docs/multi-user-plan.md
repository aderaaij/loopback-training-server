# Multi-User Training API — Implementation Plan

**Status:** planned, not started (2026-07-15)
**Goal:** anyone can self-host this stack for themselves *and their family members* — Audiobookshelf-style: each person points the iOS app at the server URL and logs in with username + password. All data (workouts, queue, plans, notes, health metrics, actions, feedback, inventory) is scoped per user. The MCP is scoped by *whose token it presents* — no MCP-side user concept needed.

**Deployment model:** self-hosted single instance, N users (a household). Not SaaS — no orgs, no sharing, no billing. Admin creates accounts; no open registration (the API is public via Tailscale Funnel).

---

## Phase 0 — ✅ DONE 2026-07-15: settings page leaked the API key publicly

`routes/dashboard.py` (settings view) passes `full_key` (the real `settings.api_key`) into `settings.html`, which embeds it in inline JS (`const fullKey = "..."`). The dashboard router is mounted **without auth** (`main.py:11`, comment says "local network only") — but Tailscale Funnel proxies **all of port 8001** at `/`, so `https://ardencore.tail38e03e.ts.net:8443/dashboard/settings` serves the full read-write API key to the public internet.

**Fixed 2026-07-15:** `full_key` removed from the template context and the reveal/copy JS deleted (`masked_key` display only); key rotated in `backend/config/.env` + `mcp/config/.env`; a stale permission entry embedding the old key was scrubbed from `.claude/settings.local.json` (git-ignored, never left the machine). Verified through the **public** Funnel ingress: page serves no key, old key → 401, new key → 200. Remaining: update the key in the iOS app. The proper replacement (per-user token management UI behind a login) comes in Phase 3.

---

## Current state (what the refactor builds on)

- Auth = one global bearer key checked by `verify_api_key` (`app/auth.py`), applied router-wide at `main.py:23`. Single choke point — good.
- 8 ORM models, none with any owner column. ~20 `db.get(Model, id)` PK-only lookups. Two global unique constraints that break under multi-user (`uq_daily_health_metrics_date`, `uq_workout_feedback_workout_id`). One destructive cross-user hazard: `inventory.py` `delete(...).where(id.notin_(incoming))` would wipe *other users'* inventory rows.
- Dashboard is 100% server-rendered Jinja2, unauthenticated, `app/static/` is empty (no JS API calls to worry about).
- `schedule_utils.py` is pure (no DB) — needs **no change**; scoping happens in the queries that feed it.
- Migrations auto-run on container start (`scripts/start.sh` → `alembic upgrade head`).
- MCP is a stateless HTTP client (`mcp/app/services/api_client.py`) holding one env token; runs behind supergateway (stdio → headers can't reach it; native FastMCP HTTP migration is already planned fleet-wide, finance-mcp is the proven pilot).
- No auth libs in `pyproject.toml` yet; no test suite.

---

## Design decisions

| Decision | Choice | Why |
|---|---|---|
| Credential model | Username + password → **opaque per-device API tokens** (ABS-style) | Revocable per device, no JWT expiry/refresh dance, trivial for the iOS app and MCP (both already speak `Bearer <token>`) |
| Token format | `tapi_` + 32 bytes urlsafe random; store **SHA-256 hash** only | High-entropy → plain SHA-256 is fine (no bcrypt cost per request); prefix makes tokens identifiable in configs |
| Password hashing | **argon2-cffi** (direct, not passlib — passlib is unmaintained and flaky on 3.13) | Modern default, two-function API |
| Roles | `admin` / `user` | Admin creates accounts + can manage users; that's all v1 needs |
| Registration | **None.** Admin bootstrapped from env on first run; family members created by admin (CLI first, dashboard page later) | The API is Funnel-exposed; open signup on the public internet is asking for it |
| Login rate limiting | **slowapi** on `/api/auth/login` (e.g. 5/min/IP) | Public endpoint accepting passwords |
| Legacy compatibility | Migration seeds the current `API_KEY` as a token owned by the bootstrap admin | Existing iOS app + training-mcp keep working through the whole refactor with zero re-config |
| Sessions (dashboard) | Same token mechanism, delivered as an **HttpOnly + Secure cookie** set by a login form | One auth system, not two; no server-side session store needed |

### New tables

```
users
  id            UUID PK (server-generated)
  username      TEXT UNIQUE NOT NULL   (store lowercased; validate [a-z0-9_.-]{3,32})
  password_hash TEXT NULL              (NULL = login disabled until set)
  display_name  TEXT NOT NULL DEFAULT ''
  role          TEXT NOT NULL DEFAULT 'user'   CHECK (role IN ('admin','user'))
  is_active     BOOL NOT NULL DEFAULT true
  created_at    TIMESTAMPTZ NOT NULL

api_tokens
  id            UUID PK
  user_id       UUID NOT NULL FK users(id) ON DELETE CASCADE
  token_hash    TEXT UNIQUE NOT NULL   (sha256 hex)
  name          TEXT NOT NULL DEFAULT ''       (device label: "Arden's iPhone", "training-mcp")
  created_at    TIMESTAMPTZ NOT NULL
  last_used_at  TIMESTAMPTZ NULL       (update at most every ~5 min to avoid a write per request)
  expires_at    TIMESTAMPTZ NULL       (NULL = long-lived; dashboard cookies get ~30d)
```

---

## Phase 1 — ✅ DONE 2026-07-15: Users, tokens, login (backend still effectively single-user)

**Shipped:** `users` + `api_tokens` tables (migrations `a1u2s3e4r5s6` schema, `b1t2o3k4e5n6` seed); `app/security.py` (argon2 passwords, `tapi_` tokens stored as SHA-256); `app/auth.py` swapped to `get_current_user` (token-hash lookup + expiry/active checks + throttled `last_used_at`); `app/routes/auth.py` (`POST /api/auth/login` rate-limited 5/min, `GET /api/auth/me`, `DELETE /api/auth/tokens/{id}`); `app/cli.py` (`bootstrap`/`create-user`/`set-password`/`create-token`/`list-users`); startup `cli bootstrap` in `scripts/start.sh`. Deps: `argon2-cffi`, `slowapi`. Verified end-to-end: legacy key still authenticates (seeded as admin's token — iOS app + MCP unaffected), admin login issues a working `tapi_` token, `/me` + revoke work, revoked/expired/garbage tokens 401, wrong password 401, rate limit trips at the 6th attempt, MCP still 35 tools. Admin password set once from `BOOTSTRAP_ADMIN_PASSWORD` in `backend/config/.env`.

Original plan below.



New files: `app/models/user.py`, `app/models/api_token.py`, `app/routes/auth.py`, `app/security.py` (hashing + token generation), `app/cli.py`.

1. **Models + migration A** (schema only): create `users`, `api_tokens`.
2. **Migration B** (data): insert bootstrap admin (`username='admin'`, `password_hash=NULL`, `role='admin'`) and insert `sha256(settings.api_key)` into `api_tokens` (name `legacy-api-key`) owned by admin. Alembic already loads app settings (`migrations/env.py` calls `get_settings()`), so the key is available at upgrade time. → the current key keeps working, now attributed to a user.
3. **Startup bootstrap** (in `scripts/start.sh` → small `python -m app.cli bootstrap`): if `BOOTSTRAP_ADMIN_USERNAME`/`BOOTSTRAP_ADMIN_PASSWORD` env vars are set and that user has no password, set it. Fresh installs get a working admin from `docker-compose.yml` env; existing install (this one) sets it once.
4. **CLI** (`python -m app.cli`): `create-user <username> [--admin]` (prompts for password), `set-password <username>`, `create-token <username> --name <label>` (prints token once), `list-users`. This is the whole v1 admin surface — dashboard user management is a later nice-to-have.
5. **Auth endpoints** (`/api/auth`, mounted *outside* the authenticated router):
   - `POST /api/auth/login` `{username, password, deviceName?}` → `{token, user: {id, username, displayName, role}}`. Creates an `api_tokens` row. Rate-limited. Never distinguishes "no such user" from "wrong password".
   - `GET /api/auth/me` (authenticated) → current user + token list (id, name, created, lastUsed — never hashes).
   - `DELETE /api/auth/tokens/{id}` (authenticated, own tokens only) → revoke.
6. **Swap the dependency:** replace `verify_api_key` with

   ```python
   def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: DbSession) -> User:
       token = db.scalar(select(ApiToken).where(ApiToken.token_hash == sha256(credentials.credentials)))
       # check exists, not expired, user.is_active → else 401; throttled last_used_at touch
       return token.user
   CurrentUser = Annotated[User, Depends(get_current_user)]
   ```

   Keep the router-level `dependencies=[Depends(get_current_user)]` in `main.py` (enforcement), and add `user: CurrentUser` as a param in handlers that need the id (FastAPI caches the dependency per-request — no double lookup).
7. **Config:** `api_key` setting becomes migration-only (drop from `Settings` after Migration B ships; keep reading it in the migration via raw env). Add `bootstrap_admin_username/password: str | None`.
8. **Deps:** add `argon2-cffi`, `slowapi`. Add `pytest` + `httpx` test client as dev deps (see Testing).

**Verify:** existing iOS app + MCP still work unchanged (legacy key token); login returns a token that works on `/api/workouts`.

## Phase 2 — ✅ DONE 2026-07-15: Tenancy: `user_id` everywhere

**Shipped:** `user_id` FK (NOT NULL, ON DELETE CASCADE, indexed) on all 8 data tables via Migration C `c1d2e3f4a5b6` (add nullable → backfill to admin → NOT NULL); the two global unique constraints became per-user composites (`uq_daily_health_metrics_user_date`, `uq_workout_feedback_user_workout`). `app/tenancy.py:get_owned` replaced ~20 bare PK lookups; every list/summary/upsert query is scoped by `user.id`; the inventory snapshot delete is now scoped so it can't wipe other users. `build_calendar` takes a `user_id` (None = dashboard's unscoped all-users view until Phase 3). Added the first test suite (`backend/tests/`, pytest as a `test` extra installed in the image): 9 two-user isolation tests — all pass, including the inventory-wipe hazard. Live-verified on the real DB: a throwaway second user saw 0 of admin's 200 workouts, 404'd on admin's ids; legacy admin token, dashboard, and MCP all still work. Family accounts are now safe to create.

Original plan below.



**Migration C** (one revision, per table): add `user_id UUID NULL` → `UPDATE ... SET user_id = <admin id>` → `ALTER ... SET NOT NULL` + `FK users(id) ON DELETE CASCADE` + index. Tables: `workout`, `workout_queue`, `workout_action`, `workout_feedback`, `workout_inventory`, `daily_health_metrics`, `plans`, `plan_note`.

Constraint/index changes in the same revision:
- `uq_daily_health_metrics_date` → **`uq_daily_health_metrics_user_date` on `(user_id, date)`** — and update the `on_conflict_do_update(constraint=...)` name in `routes/health_metrics.py`.
- `uq_workout_feedback_workout_id` → **`(user_id, workout_id)`** — same name-update in `routes/feedback.py`.
- Composite indexes where the hot queries are: `(user_id, start_date)` on workout, `(user_id, status)` and `(user_id, scheduled_date)` on workout_queue, `(user_id, status)` on plans, `(user_id, created_at)` on plan_note.

**Shared helper** (`app/tenancy.py`) to kill the ~20 PK-only lookups in one idiom:

```python
def get_owned(db: Session, model: type[T], obj_id: UUID, user: User) -> T:
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(404)   # 404, not 403 — don't leak existence
    return obj
```

### Route-by-route touch list

| File | Changes |
|---|---|
| `routes/workouts.py` | `POST ""` upsert: if row exists with different `user_id` → 409 (client-supplied HealthKit UUIDs; collision ~impossible but must not cross-write). Set `user_id` on insert. `GET ""` + `/summary`: add `WHERE user_id`. 4 PK-gets (`get`, `splits`, `heartrate`, `DELETE`) → `get_owned`. |
| `routes/queue.py` | Both routers. `pending`/list: `WHERE user_id`. create/batch: set `user_id`. 4 PK-gets (`PATCH`, `PATCH /status`, `DELETE`, app `DELETE /{id}`) → `get_owned`. |
| `routes/plans.py` | list: `WHERE user_id`; create: set `user_id`; `_get_plan_or_404` → `get_owned` (fixes all 6 PK-gets); `_runs_by_date` conflict scan: `WHERE user_id`. |
| `routes/plan_notes.py` | list/context: `WHERE user_id` (incl. `_resolve_active_plan` — "the active plan" becomes per-user); create: set `user_id`; 3 PK-gets → `get_owned`. |
| `routes/schedule.py` | `build_calendar(db, user, ...)`: scope all three sub-queries (WorkoutQueue, Workout strength, active Plans). `schedule_utils.py` untouched. |
| `routes/health_metrics.py` | Upsert: set `user_id`, conflict target → new composite constraint name. List: `WHERE user_id`. |
| `routes/actions.py` | list: `WHERE user_id`; create/batch: set `user_id`; 1 PK-get → `get_owned`. |
| `routes/feedback.py` | Upsert: set `user_id`, conflict target → composite. List: `WHERE user_id`. |
| `routes/inventory.py` | **The hazard.** `PUT ""` snapshot replace: `delete(WorkoutInventory).where(WorkoutInventory.user_id == user.id, id.notin_(incoming))`; per-item upsert via `get_owned`-style ownership check; set `user_id`. `GET ""`: `WHERE user_id`. |
| `routes/health.py` | No change (liveness probe). |
| `routes/dashboard.py` | Phase 3. |

**Schemas:** no request/response schema changes needed — `user_id` is derived from the token, never accepted from or echoed to clients.

**Verify:** two-user isolation test suite (see Testing) is the acceptance gate for this phase.

## Phase 3 — Dashboard: login + per-user views + token management

1. `GET/POST /dashboard/login` — username/password form; on success create an `api_tokens` row (name `dashboard`, `expires_at` +30d) and set it as an **HttpOnly, Secure, SameSite=Lax cookie**. `POST /dashboard/logout` revokes + clears.
2. Cookie-auth dependency (`get_dashboard_user`): read cookie → same token lookup as Phase 1 → `RedirectResponse("/dashboard/login")` when missing/invalid. Applied to the dashboard router.
3. Scope every dashboard query by the logged-in user: overview stats/counts, plan view, schedule grid (`build_calendar(db, user, ...)`), latest health metrics.
4. **Settings page rebuilt** as per-user token management: list tokens (name, created, last used), create token (value shown exactly once — this is how a family member gets their MCP/app token if not using the login flow), revoke token, change password. The `full_key` embedding is already gone (Phase 0).
5. Admin-only section (role check): create user, reset password, deactivate. (Can trail the CLI; not a blocker.)
6. Base template: show logged-in user + logout link.

## Phase 4 — MCP scoping

**Tier 1 — ships automatically with Phase 1** (zero code): `TRAINING_API_KEY` in `mcp/config/.env` is now just a *user's* token. Each family member runs their own instance (`new-mcp` makes this cheap) or points their own client at their own instance. Update `main.py` instructions text: remove "This is a single-user system" (it stays true *per token*, which is exactly what the LLM needs to believe).

**Tier 2 — one shared MCP, per-session identity via token passthrough:**
1. **Native HTTP first** (prereq — headers cannot cross supergateway's stdio bridge): copy the finance-mcp pilot's `MCP_TRANSPORT` env switch into `mcp/app/main.py` (`mcp.run(transport="http", host=MCP_HOST, port=8590)` when set); swap the systemd unit the same way (`Environment=MCP_TRANSPORT=http MCP_PORT=8590`, keep the `.pre-native.bak` rollback next to it). Already on the fleet migration list — this feature is the forcing function.
2. **Passthrough in `api_client.py`:** replace the singleton's fixed key:

   ```python
   from fastmcp.server.dependencies import get_http_headers

   def _resolve_key(self) -> str:
       incoming = get_http_headers().get("authorization", "")
       if incoming.lower().startswith("bearer "):
           return incoming[7:]
       return self._api_key          # env fallback = single-user default
   ```

   (Requires bumping the `fastmcp>=2.0.0` pin to a version with `get_http_headers`, ≥2.3.x — check installed version at implementation time.) Called per-request in `headers`; env-token fallback keeps the current setup working unchanged.
3. **Client config:** Claude Code `claude mcp add --transport http training http://ardencore:8590/mcp --header "Authorization: Bearer tapi_..."`; Claude Desktop via `mcp-remote --header` (its native remote-connector UI can't set arbitrary headers). Tailscale grants can additionally restrict who can reach :8590 at the network layer.
4. A 401 from the backend should surface as "your token is invalid/revoked — create a new one on the dashboard settings page" instead of the current `TRAINING_API_KEY` message.

**Tier 3 — claude.ai (OAuth): explicitly out of scope.** Would require mapping OAuth identity → training-api user through the auth-proxy layer. Only worth it if a family member actually wants claude.ai access; revisit then.

## Phase 5 — iOS app contract (separate repo; handoff doc like `app-scheduling-handoff.md`)

- New: settings screen takes **server URL + username + password** → `POST /api/auth/login` (send `deviceName`) → store token in Keychain. Everything else is unchanged (same `Bearer` header on every call).
- Handle `401` anywhere → clear token, return to login (covers revocation + deactivation).
- HealthKit sync, queue fetch, inventory PUT, feedback, health metrics: no payload changes — scoping is server-side from the token.
- Watch-per-user comes free: each phone logs in as its owner, so each watch only sees its owner's queue.

## Phase 6 — Self-host packaging

- `docker-compose.yml`: add `BOOTSTRAP_ADMIN_USERNAME`/`BOOTSTRAP_ADMIN_PASSWORD` (env-file), drop `API_KEY` once migrated. README quick-start: `docker compose up -d` → log into dashboard as admin → `create-user` for each family member → each installs the app and logs in.
- Document the exposure options (Tailscale Funnel like this instance, plain tailnet, reverse proxy) and that login is rate-limited but public exposure means strong passwords.
- `CLAUDE.md` + `README.md` updates; note in `docs/` that `get_plan_context`/plan-notes are now per-user (the plan-note audit routine concept doc should note it must run per user or as admin over all).

## Testing (new — repo currently has none)

Minimal pytest suite, gating Phase 2 especially:
- **Isolation invariant (the one that matters):** create users A and B with data in every table; assert every list endpoint returns only the owner's rows, every PK endpoint 404s cross-user, the inventory `PUT` for A **does not delete B's rows**, upserts (health metrics same date, feedback same workout_id) don't collide across users.
- Auth: login happy path, wrong password, inactive user, revoked token, expired cookie token, rate limit trips.
- Legacy: seeded legacy-key token resolves to admin.
- Run against a throwaway Postgres (compose service or testcontainers).

## Rollout order & rollback

1. **Phase 0 now** (leak fix + key rotation) — independent commit.
2. Phase 1 → deploy. Everything behaves identically (legacy key = admin token). Rollback: revert image; migrations A/B are additive.
3. Phase 2 → deploy behind the isolation test suite. Rollback: revert image (schema keeps `user_id`, harmless to old code? **No** — old code doesn't set `user_id` on inserts and NOT NULL would reject them; rollback = revert image + `alembic downgrade` one revision. Write Migration C's `downgrade()` properly.)
4. Phase 3 (dashboard) and Phase 4 tier 2 (MCP) are independent of each other, any order.
5. Phases 5–6 as the app catches up.

Each phase is a PR-sized branch. Phases 1+2 are the bulk (~2–3 sessions); 3 is ~1 session; 4 tier 2 is small once native HTTP lands.

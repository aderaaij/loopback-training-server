# Training API

Personal workout tracking API with Apple Watch integration queue, training plans, health metrics, and a web dashboard.

The companion iOS app lives at [aderaaij/loopback-training-app](https://github.com/aderaaij/loopback-training-app); a working copy is usually checked out as a sibling directory (`../loopback-training-app`). Cross-reference it for the client side of the API contract (`WorkoutAPIClient.swift`, `SessionStore.swift`, `WorkoutScheduleManager.swift`) before changing wire formats — and `git pull` it first, since development happens elsewhere.

## Tech Stack

- **Backend:** FastAPI (Python 3.13) with Uvicorn
- **Database:** PostgreSQL 16 with SQLAlchemy 2.0 ORM, Alembic migrations
- **Package manager:** uv
- **Frontend:** React 19 + TypeScript SPA ("Loopback", in `frontend/`) — Vite 8, React Compiler, TanStack Query, react-router, hand-rolled SVG charts, Leaflet route maps
- **MCP Server:** FastMCP 2.0 (in `mcp/`)
- **Infrastructure:** Docker Compose (`docker-compose.yml`)

## Project Structure

```
backend/
  app/
    main.py              # FastAPI app entry point (+ serves the SPA build, see below)
    auth.py              # Bearer token auth
    config.py            # Pydantic-settings
    database.py          # SQLAlchemy setup
    models/              # ORM models
    routes/              # API route handlers
    schemas/             # Pydantic request/response schemas
  migrations/            # Alembic migrations
  Dockerfile             # Multi-stage build: Node (frontend) + uv (backend); context = repo root
frontend/
  src/
    lib/                 # api client, wire types, auth context, query hooks, formatters
    components/          # layout, shared UI, SVG chart primitives, route map
    screens/             # one file per screen (Overview, Calendar, Workouts, Plans, Notes, Health, Queue, Settings, Users)
    styles/              # global design tokens + per-screen CSS
mcp/
  app/
    main.py              # FastMCP server entry point
    config.py            # MCP settings
    coaching/            # Coaching playbook content (core.md + goals/*.md) + loader
    tools/               # MCP tool routers (workouts, queue, actions, feedback, health, plans, coaching)
    services/            # HTTP client for backend API
```

## Frontend (web dashboard)

The authenticated React dashboard replaces the old unauthenticated server-rendered one.
It is served **same-origin by FastAPI**: the Docker build bakes `frontend/dist` into the
image at `/app/static` (`SPA_DIST` env var), `main.py` serves it at `/` with an SPA
fallback for client-side routes. No CORS needed; the Tailscale Funnel setup is unchanged.

```bash
cd frontend
npm run dev        # Vite dev server on :5173, proxies /api → localhost:8001
npx tsc -b         # typecheck
npm run build      # production build (also run inside the Docker build)
```

**Wire-casing warning:** the API's JSON casing is inconsistent per resource — auth,
feedback and calendar are camelCase; workouts, queue, plans and health-metrics are
snake_case; plan-notes are mixed. `frontend/src/lib/types.ts` mirrors this exactly on
purpose. Don't "normalize" one side without the other.

Login is rate-limited (5/min/IP). On any 401 the SPA wipes its token and returns to
the login screen. The bearer token lives in localStorage (`loopback.*` keys). Because
of that 401 contract, *authenticated* endpoints that check a password signal "wrong
password" with **400, never 401** (e.g. `POST /api/auth/password` on a wrong current
password). Login itself 401s on bad credentials — there is no token to wipe yet.

Account management is fully in the dashboard (admin CRUD on `/api/admin/users` —
role-guarded, deactivation revokes all tokens; self-service `POST /api/auth/password`
+ `POST /api/auth/tokens`). New passwords require ≥8 chars; the CLI (`app.cli`)
remains as a fallback. Remaining dashboard work (polish list):
see `docs/dashboard-next-steps.md` (`docs/` is gitignored — local working notes
and handoff docs, not part of the shared repo).

**Admin vs athlete dashboard (2026-07-17):** an admin (role `admin`) manages accounts
and is not an athlete, so the athlete screens (Overview/Calendar/Workouts/Plans/Notes/
Health/Queue) are hidden for them — the `AthleteOnly` guard in `App.tsx` redirects
those routes (incl. `/`) to `/users`, and `Layout.tsx` swaps to an admin-only nav
(Users + System). The athlete experience is byte-for-byte unchanged. Admins keep
`/settings` (own password/tokens). The two **admin-only screens**:
- **Users** (`screens/Users.tsx`) — the existing member CRUD, now with an expandable
  per-user **token list** (`GET/DELETE /api/admin/users/{id}/tokens[/{tid}]`, revoke a
  single stolen device without nuking the whole account) and a **sync-freshness** line
  per athlete (`lastWorkoutSyncAt` = when the last workout row arrived, `lastHealthDate`
  = newest health day). Metadata only — never workout content — so it respects the
  athlete/admin data boundary. Admins show no sync line (they have no data).
- **System** (`screens/System.tsx`, `/system`) — backup freshness card (reads the
  read-only `/backups` mount, green<26h / amber<50h / red), DB size + row counts +
  Alembic head, and an **auth-activity feed** (`GET /api/admin/events`).

**Auth audit trail:** `auth_events` table (`models/auth_event.py`) + `record_auth_event`
helper (`app/auth_events.py`) log login success/failed/rate-limited, password
change/reset, token create/revoke, and user create/deactivate/reactivate. FKs are
`SET NULL` (trail survives user deletion) and the attempted username is kept as text
(failed logins never resolve to a user). Events stage on the caller's session so they
commit atomically with the change they describe; the rate-limit handler (`main.py`)
uses its own short-lived session. The events endpoint opportunistically prunes rows
>365d on read (no timer). The publicly-Funnel-exposed login endpoint made this the
genuinely monitoring-shaped addition — failed-login/rate-limit visibility.

## Development

```bash
make up                          # Start containers (postgres + app)
make down                        # Stop containers
make build                       # Rebuild images
make logs                        # Tail logs
make migrate                     # Run Alembic migrations
make create_migration m="desc"   # Create new migration
```

The API runs on port **8001**. Auth is per-user: `POST /api/auth/login` mints opaque `tapi_` bearer tokens (argon2 passwords, SHA-256-hashed tokens); only `/api/health` and `/api/auth/login` are unauthenticated.

**Demo stack:** `docker compose -f docker-compose.demo.yml up -d && python3 scripts/seed_demo.py` boots a fully isolated demo instance on **:8011** (own compose project `training-api-demo`, own volume, hardcoded throwaway creds: `admin`/`demo-admin`, athlete `sofia`/`sofia-demo`) and seeds ~16 weeks of synthetic training through the public API (stdlib-only seeder, deterministic per `--seed`, anchored to today). The README screenshots are captures of exactly this seed. Reset: `docker compose -f docker-compose.demo.yml down -v`. The seeder creates the run plan *last* on purpose — plan-note context resolves to the most recently created active plan. `--skip-workouts` seeds everything except workout rows (queue completions and all other state stay) — for the combined simulator demo where the iOS app's DEBUG HealthKit seeder (`DebugWorkoutSeeder.swift` in the app repo) uploads the same story and workout ids match end-to-end; this script is the canonical spec for that seeder.

**Configuration (since Phase 6, 2026-07-18):** a containerized install is configured entirely from the repo-root `.env` (template `.env.example`) — compose derives `DATABASE_URL` from the same `POSTGRES_*` variables the db service uses and passes `BOOTSTRAP_ADMIN_USERNAME`/`BOOTSTRAP_ADMIN_PASSWORD` through only when set. `backend/config/.env` is optional (compose `env_file` is `required: false`): it's for running the backend outside Docker, and on upgraded pre-auth installs it may still hold the legacy `API_KEY` (now optional in `Settings`; when present the seed migration registers it as an admin-owned token). First boot with no admin password logs a loud warning with the fix.

## Database

Models live in `backend/app/models/`. Key tables:
- **Workout** - recorded workouts with splits, heart rate, JSONB metadata. Aggregates *all* HealthKit workouts by source — running (Apple), Strava rides, Bend flexibility, Garmin, and **Hevy strength** (source `com.hevyapp.hevy`, activity `traditionalStrength`). There is **no Hevy API integration**; strength sessions arrive via HealthKit sync like everything else.
- **WorkoutQueue** - structured workouts queued for Apple Watch sync (status: pending/fetched/synced/completed/skipped). Posting missed-workout feedback with `action: "skip"` retires the queue item to `skipped` (feedback `workoutId` == queue item id): the watch endpoints stop serving it and it no longer counts as a schedule collision. One-way; never downgrades `completed`. `scheduled_date` is a first-class indexed column (kept in sync with `workout_data.scheduledDate`, which the iOS app still reads) so the schedule is queryable and can be conflict-checked.
- **Plan** - training plans with JSONB metadata (goals, guardrails, phases). Metadata may also hold a **`schedule`** — a recurring weekly cadence `{startDate, weeks, days: {mon: {title, routineId}, ...}, time, timezone}`. Used for strength/Hevy cycles: each weekday slot references a **Hevy routine** (opaque `routineId` + title; the LLM looks these up via the separate `hevy-mcp` and passes them in — this API never resolves them). Strength slots are plan markers only; they are **not** pushed to the Apple Watch. Completed strength sessions auto-match to schedule dates via the `traditionalStrength` workouts Hevy syncs in.
- **PlanNote** - cross-conversation continuity notes (decisions, preferences, life context). LLM reads via `get_plan_context`, writes via `append_plan_note`.
- **DailyHealthMetrics** - daily HealthKit data (sleep, HR, HRV, weight, VO2Max, etc.)
- **DailyNutrition** - daily dietary totals from HealthKit (energy, carbs, protein, fat, saturated fat, fiber, sugar, sodium, potassium, cholesterol, water, caffeine + an open `micros` JSONB for the long tail). Kept out of `daily_health_metrics` on purpose: written by food-logging apps rather than the watch, sparse by nature (**an absent row means "not tracked", never "ate nothing"**), and keeping it separate keeps the health-metrics payload lean. `partial: true` marks a day synced while still in progress — excluded from every average until a later sync completes it. `entry_count`/`sources` record logging adherence and which app wrote the day.
- **WorkoutAction** - edit/delete actions for on-device workouts
- **WorkoutFeedback** - missed workout feedback
- **WorkoutInventory** - current on-device workout snapshot

### Plan completion
- Plan reads (list/get) carry computed `progress` (queue-derived run counts, plus scheduled strength sessions for plans with a recurring schedule — completed via the same date-matching to synced `traditionalStrength` workouts the calendar uses, past-unmatched counted as skipped; the `runs_*` wire names are historical) and `finishable` — an active, started plan whose window has passed or whose sessions are all retired (≥1 actually completed). Nothing flips status automatically: the dashboard shows a celebration banner/modal (Overview, Plans, PlanDetail) for finishable plans and the user confirms.
- `POST /api/plans/{id}/complete` (400 if not active) — sets status `completed`, stamps `metadata.completion` `{completed_on, rating?, feedback?}`, stores feedback/rating as a **kind:"feedback" PlanNote** (the coach LLM sees it via `get_plan_context`), and returns `next_plan` — another already-active same-activity plan, or null, which the UI turns into a "chat with your coach to shape the next block" nudge.

### Plan validation (deterministic, no AI)
- `backend/app/plan_validation.py` (pure, unit-tested) + `validation_service.py`
  (DB assembly): a "linter" for the athlete's upcoming schedule. Checks the coaching
  playbook's numeric invariants against queued compositions + real workout history:
  weekly ramp vs the 4-week baseline (warn >1.3×, critical >1.5×), volume with no
  history baseline, missing down weeks, long-run share >35%, back-to-back hard days,
  no rest day, frequency jumps, taper shape before `metadata.goals.race_date`,
  strength-day collisions (via plan schedules), and the plan's own
  `metadata.guardrails` (`max_sessions_per_week`, `max_weekly_km` — breaches are
  critical). Warn-don't-block throughout.
- Surfaced four ways: `POST /api/queue` gains an additive `validation` key,
  `POST /api/queue/batch` now returns an **envelope** `{items, validation}`
  (shape change — only the MCP consumed the old bare array),
  `POST /api/plans/{id}/validate` returns `{plan_id, warnings, weeks}` with
  per-week summaries (MCP tool: `validate_plan`), and the dashboard's
  **PlanDetail "Schedule check" card** (active plans only; severity-colored
  warnings + per-week rows; snake_case wire, unlike the camelCase schedule
  endpoint). Deliberately **not** in the iOS app — warnings are planning-time
  info; the athlete acts on them via the coach, not the app.
- PlanDetail renders `metadata.guardrails` in **both** LLM-authored shapes:
  legacy array of goal-like entries and the validator-readable dict
  (`{max_weekly_km: 30}`).
- Estimation: time-goal steps convert to km via the step's pace alert, else the
  athlete's median historical speed (`estimated: true` flags assumption-based
  numbers). "Hard" = interval structure (work + rest/recovery × 2+) or a pace alert
  faster than easy — so C25K walk/run sessions classify hard (harmless: they're
  never scheduled on consecutive days).

### Nutrition
- `POST /api/nutrition` (bulk upsert, non-null fields only — same contract as health metrics), `GET /api/nutrition` (daily rows, newest first, bounded by `limit`), `GET /api/nutrition/summary?period=week|month&timezone=` — **the analysis endpoint**: per-period intake averages (partial days excluded), `protein_g_per_kg`, body-weight start/end/change, and training load, all aligned on the same buckets so diet-vs-weight-vs-performance needs one call instead of three plus date arithmetic.
- Period bucketing is pure + unit-tested in `backend/app/nutrition_summary.py`. It buckets in Python rather than SQL `date_trunc` because nutrition is keyed by local date while workouts carry an instant — truncating a timestamptz in the session timezone drifts a late-evening workout into the neighbouring week. Pass `timezone` to attribute workouts to the athlete's local day.
- `days_logged` / `days_in_period` accompanies every average on purpose: an average over 2 logged days is an anecdote, and the LLM instructions plus the dashboard both say so.
- Whole-day totals + field-by-field overwrite means **the client must compute them over a complete local day**; a window edge landing mid-day would store that day's tail (the July 2026 sleep/steps corruption, `docs/sleep-data-handoff.md`). App-side spec: `docs/app-nutrition-handoff.md`.
- MCP: `get_nutrition` (daily rows) and `get_nutrition_summary` (the aligned table — the tool the server instructions push the LLM toward). Dashboard: the Nutrition block on the Health screen (`frontend/src/components/NutritionCards.tsx`).

### Scheduling / calendar
- `GET/PUT/DELETE /api/plans/{id}/schedule` — read/set/clear a plan's recurring cadence; the response resolves it to concrete dated `sessions` and flags any that **collide with a queued run** (`warnings`, surfaced not blocked). Weekday keys validated against `mon..sun`.
- `GET /api/schedule/calendar?from=&to=` — unified timeline merging scheduled runs (queue) + strength sessions (active plan schedules), each with a `conflict` flag. Shared by the dashboard **Schedule** page and the MCP.
- Expansion/conflict logic is in `backend/app/schedule_utils.py` (pure) + `routes/schedule.py`.
- MCP tools (`mcp/app/tools/plans.py`): `set_strength_schedule`, `get_plan_schedule`, `clear_plan_schedule`, `get_training_calendar`. Workflow: pull routines from `hevy-mcp` → `get_training_calendar` to see runs → `set_strength_schedule` placing sessions on free days.

When adding/changing models, create a migration with `make create_migration m="description"`. Migrations auto-run on container startup.

## MCP Server

The MCP server (`mcp/`) exposes training data to Claude via FastMCP. It talks to the backend API over HTTP.

- Runs as a separate systemd service (`training-mcp`) on port **8590** — native FastMCP streamable HTTP at `/mcp` since 2026-07-17 (`MCP_TRANSPORT=http` in the unit, no supergateway; stdio remains the default transport for direct clients). Rollback: `training-mcp.service.pre-native.bak`
- Config: `~/.config/systemd/user/training-mcp.service`
- Env: `mcp/config/.env` (needs `TRAINING_API_URL` and `TRAINING_API_KEY`)
- **Coaching playbook:** `get_coaching_playbook(goal?, experience?)` serves the running-coach
  methodology any LLM client should follow before creating/revising a plan (server
  `instructions` direct models to call it). Content is plain markdown in `mcp/app/coaching/`:
  `core.md` (evidence-based principles + API mapping, always included) + `goals/<goal>.md`
  modules (`first_5k` = C25K walk/run, `5k`, `10k`, `half_marathon`, `marathon`,
  `general_fitness`). Goal files may have top-level `## Beginner/Intermediate/Advanced`
  sections — the loader returns only the requested level. Adding a goal = dropping a new
  `goals/<name>.md` **plus** adding the value to the `Goal` Literal in `tools/coaching.py`.
  Served as a tool (not an MCP prompt) deliberately: tools are the one primitive every MCP
  client supports, and content updates ship server-side with no client changes.
- **Token passthrough (multi-user):** an `Authorization` header on the incoming MCP request is forwarded to the backend as-is, so each caller acts as their own Training API user; any presented header disables the fallback (a bad token fails, never silently downgrades). With no header, `TRAINING_API_KEY` (an athlete token, not admin) is the fallback — set `REQUIRE_AUTH_HEADER=true` in the unit/env to disable the fallback once multiple users have network access to :8590. Note: FastMCP's `get_http_headers()` strips `authorization` unless included explicitly (`include={"authorization"}`).
- **Text-only tool results (2026-07-23):** every tool is wrapped with `@text_result` (`mcp/app/wire.py`) so results ship as one compact-JSON text block — no `structuredContent`, which FastMCP otherwise duplicates the entire payload into (and which made empty lists render as `{"result": []}`). New tools must add the decorator **under** `@router.tool`. LLM-facing payload trimming lives server-side in `backend/app/workout_summary.py`: `strip_samples` (sample arrays → `samplesSummary`, segment-event pruning, float rounding) plus `downsample_timed`/`round_floats` used by the heartrate/splits endpoints; `get_training_summary` and `get_workout_heartrate` are bounded by default (`limit=52` rows / `max_samples=500`).

## Deployment

Managed via Docker Compose. The backend container auto-runs migrations on startup.

**Releases (since v0.1.0, 2026-07-23):** the version's single source of truth is `backend/app/version.py` (`pyproject.toml` reads it via hatchling; surfaced at `/api/health` and the admin System screen as `appVersion`). Cutting a release = bump it + CHANGELOG entry + `git tag -a vX.Y.Z` + push — the Docker workflow then publishes GHCR images tagged `X.Y.Z` and `X.Y` alongside `latest` (which tracks `main`). Compose pins via `IMAGE_TAG` in the root `.env` (default `latest`). SemVer with the 0.x caveat: breaking changes bump the minor.

**Server-managed backups (since v0.1.1):** `backend/app/backup.py` — nightly `pg_dump` at `BACKUP_TIME` (container time) into `BACKUP_DIR=/backups`, keeping `BACKUP_KEEP`; a catch-up dump after downtime; a pre-migration dump on startup when migrations are pending (`python -m app.backup pre-migrate` in `start.sh`, warn-don't-block); and `POST /api/admin/backup` behind the System screen's "Back up now". **This deployment disables all of it** — `docker-compose.override.yml` sets `BACKUP_ENABLED=false` and keeps the NAS mount `:ro`, because the host's `training-api-backup.timer` remains the canonical backup path here.

```bash
docker compose up -d --build     # Deploy changes
docker compose logs -f backend   # Check logs
```

This deployment is exposed via Tailscale Funnel (HTTPS on :8443, proxying the API on :8001) for iPhone app access.

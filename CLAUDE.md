# Training API

Personal workout tracking API with Apple Watch integration queue, training plans, health metrics, and a web dashboard.

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
    templates/           # Jinja2 templates of the RETIRED server dashboard (not mounted)
    static/              # Assets of the retired dashboard (not mounted)
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
    tools/               # MCP tool routers (workouts, queue, actions, feedback, health, plans)
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
of that 401 contract, auth endpoints signal "wrong password" with **400, never 401**.

Account management is fully in the dashboard (admin CRUD on `/api/admin/users` —
role-guarded, deactivation revokes all tokens; self-service `POST /api/auth/password`
+ `POST /api/auth/tokens`). New passwords require ≥8 chars; the CLI (`app.cli`)
remains as a fallback. Remaining dashboard work (polish list):
see `docs/dashboard-next-steps.md`.

## Development

```bash
make up                          # Start containers (postgres + app)
make down                        # Stop containers
make build                       # Rebuild images
make logs                        # Tail logs
make migrate                     # Run Alembic migrations
make create_migration m="desc"   # Create new migration
```

The API runs on port **8001**. Auth is via `Authorization: Bearer <API_KEY>` header. The `/health` and `/dashboard` endpoints are unauthenticated.

## Database

Models live in `backend/app/models/`. Key tables:
- **Workout** - recorded workouts with splits, heart rate, JSONB metadata. Aggregates *all* HealthKit workouts by source — running (Apple), Strava rides, Bend flexibility, Garmin, and **Hevy strength** (source `com.hevyapp.hevy`, activity `traditionalStrength`). There is **no Hevy API integration**; strength sessions arrive via HealthKit sync like everything else.
- **WorkoutQueue** - structured workouts queued for Apple Watch sync (status: pending/fetched/synced/completed/skipped). Posting missed-workout feedback with `action: "skip"` retires the queue item to `skipped` (feedback `workoutId` == queue item id): the watch endpoints stop serving it and it no longer counts as a schedule collision. One-way; never downgrades `completed`. `scheduled_date` is a first-class indexed column (kept in sync with `workout_data.scheduledDate`, which the iOS app still reads) so the schedule is queryable and can be conflict-checked.
- **Plan** - training plans with JSONB metadata (goals, guardrails, phases). Metadata may also hold a **`schedule`** — a recurring weekly cadence `{startDate, weeks, days: {mon: {title, routineId}, ...}, time, timezone}`. Used for strength/Hevy cycles: each weekday slot references a **Hevy routine** (opaque `routineId` + title; the LLM looks these up via the separate `hevy-mcp` and passes them in — this API never resolves them). Strength slots are plan markers only; they are **not** pushed to the Apple Watch. Completed strength sessions auto-match to schedule dates via the `traditionalStrength` workouts Hevy syncs in.
- **PlanNote** - cross-conversation continuity notes (decisions, preferences, life context). LLM reads via `get_plan_context`, writes via `append_plan_note`.
- **DailyHealthMetrics** - daily HealthKit data (sleep, HR, HRV, weight, VO2Max, etc.)
- **WorkoutAction** - edit/delete actions for on-device workouts
- **WorkoutFeedback** - missed workout feedback
- **WorkoutInventory** - current on-device workout snapshot

### Plan completion
- Plan reads (list/get) carry computed `progress` (queue-derived run counts) and `finishable` — an active, started plan whose window has passed or whose queued runs are all retired (≥1 actually completed). Nothing flips status automatically: the dashboard shows a celebration banner/modal (Overview, Plans, PlanDetail) for finishable plans and the user confirms.
- `POST /api/plans/{id}/complete` (400 if not active) — sets status `completed`, stamps `metadata.completion` `{completed_on, rating?, feedback?}`, stores feedback/rating as a **kind:"feedback" PlanNote** (the coach LLM sees it via `get_plan_context`), and returns `next_plan` — another already-active same-activity plan, or null, which the UI turns into a "chat with your coach to shape the next block" nudge.

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
- **Token passthrough (multi-user):** an `Authorization` header on the incoming MCP request is forwarded to the backend as-is, so each caller acts as their own Training API user; any presented header disables the fallback (a bad token fails, never silently downgrades). With no header, `TRAINING_API_KEY` (an athlete token, not admin) is the fallback — set `REQUIRE_AUTH_HEADER=true` in the unit/env to disable the fallback once multiple users have network access to :8590. Note: FastMCP's `get_http_headers()` strips `authorization` unless included explicitly (`include={"authorization"}`).

## Deployment

Managed via Docker Compose. The backend container auto-runs migrations on startup.

```bash
docker compose up -d --build     # Deploy changes
docker compose logs -f backend   # Check logs
```

Exposed via Tailscale Funnel at `https://ardencore.tail38e03e.ts.net:8443` for iPhone app access.

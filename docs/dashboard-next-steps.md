# Dashboard — remaining work (handoff)

Status 2026-07-16: the Loopback React dashboard (`frontend/`) is complete, deployed,
and served same-origin by FastAPI. Everything below is follow-up work, roughly in
priority order. The UI already has affordances for items 1–3 (marked "BACKEND
PENDING"), so each one is backend-first with a small frontend enable step.

## 1. Admin user-management endpoints (S11 — CLI-only today)

The Users screen (`frontend/src/screens/Users.tsx`) probes `GET /api/admin/users`
and, on 404/405, degrades to a "CLI only today" banner. Build (mirroring the
`app.cli` verbs, camelCase like the auth router, guarded by `role == "admin"`):

- `GET /api/admin/users` → array of
  `{id, username, displayName, role, isActive, tokenCount, lastSeenAt}`
  (this exact shape is what the frontend's `AdminUserRow` already expects;
  `lastSeenAt` = max `lastUsedAt` across the user's tokens, nullable).
- `POST /api/admin/users` `{username, password, displayName?, role?}` — create.
- `POST /api/admin/users/{id}/password` `{password}` — reset.
- `PATCH /api/admin/users/{id}` `{isActive?}` — deactivate/reactivate.
  **Deactivation must revoke all the user's tokens** — the UI copy promises
  "devices stop authenticating immediately" (auth already checks `is_active`,
  so strictly the tokens die with the flag, but deleting rows keeps /me tidy).

Frontend enable: replace the create-user modal's "copy CLI command" flow with a
real mutation; add reset-password / deactivate row actions. The list will light
up on its own once the GET stops 404ing.

## 2. Change-password endpoint (S10)

Suggested: `POST /api/auth/password` `{currentPassword, newPassword}` (re-verify
current, bcrypt like the CLI). Frontend: `Settings.tsx` has a disabled
"Change password · BACKEND PENDING" button — swap for a modal + mutation.
Decide whether changing the password should revoke other tokens (nice touch).

## 3. Self-service token minting (S10)

Suggested: `POST /api/auth/tokens` `{name, expiresAt?}` → `{token, tokenId}`,
raw token shown **once** (same rule as login). Frontend: disabled "New token"
button in `Settings.tsx`; show the minted token in a copy-once dialog.
Use case: hooking up a personal MCP without logging in on that device.

## 4. Polish / smaller items

- **HR zones are fixed bpm boundaries** (120/140/155/170 in
  `frontend/src/components/charts.tsx` + `WorkoutDetail.tsx`). Derive from a
  per-user max HR (settings field, backend-less via localStorage, or a proper
  user preference endpoint).
- **Coach teaser wording:** the Overview teaser prints `continuity_hint`
  verbatim, which is LLM-directed text ("…call append_plan_note…"). Fine for
  the Notes screen (that's the point), odd on the Overview — consider a
  user-facing paraphrase there.
- **Topbar search** existed in the design but was omitted (would have been
  non-functional). If wanted: client-side search over workouts/plans/notes.
- **Route map tiles** are an external fetch (CARTO dark). Offline alternative:
  draw the GPS polyline standalone (no tiles) when the tile fetch fails.
- **PWA manifest** (add-to-home-screen on iPhone) — the dashboard is
  mobile-first and checked from a phone; cheap win.
- **E2E test in-repo:** verification currently lives in throwaway scripts
  (headless chromium from `~/.cache/ms-playwright`, temp CLI user, seed via
  API, screenshot, delete rows). Worth turning into a checked-in Playwright
  test. Gotcha discovered: screenshot only after an explicit settle delay —
  `networkidle` can fire before the post-login query burst begins.

## 5. Ops notes (already done, for context)

- Container runs **production mode**: `ENVIRONMENT: PRODUCTION` is pinned in
  `docker-compose.yml`'s `environment:` block (overrides the env_file, which
  is deliberately untouched).
- Deploys are manual: `docker compose up -d --build` (watchtower instances are
  scoped elsewhere and never rebuild local images).
- The frontend builds **inside** the Docker image (Node stage in
  `backend/Dockerfile`, build context = repo root). No dist/ is committed.
- Wire casing is inconsistent per resource — read the warning in CLAUDE.md
  before touching `frontend/src/lib/types.ts` or backend schemas.

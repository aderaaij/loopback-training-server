# Changelog

Notable changes to Loopback Server. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) — with the usual 0.x caveat that
**breaking changes bump the minor version** until 1.0.

Each release `vX.Y.Z` is a git tag and publishes multi-arch Docker images
tagged `X.Y.Z` and `X.Y` to GHCR (see README "Releases & upgrading").
The running server reports its version at `/api/health` and on the admin
System screen.

## [0.1.33] — 2026-11-27

### Added

- **Coach tokens: an assistant's token now works for the coach and nothing
  else.** Until now there was one kind of token. The one Claude or ChatGPT was
  given when you approved it, or the one the Connect dialog made, could do
  everything you can, including making more tokens and changing what you share.
  Tokens handed to an assistant are now *coach tokens*: the server accepts them
  for the requests the coach's tools make and answers 403 to everything else.
  With one, nobody can change your password, create or revoke tokens, change
  what you share, approve another assistant, or upload data as if they were
  your phone. It can still do everything the coach can, which includes
  rewriting a plan and deleting a workout.
  - **What you share with the coach is now enforced for these tokens.** The
    sharing setting in the app used to shape what the coach was handed, while a
    direct call to the API with the same token got everything. A coach token is
    filtered on every request.
  - Signing in from an assistant and **Settings → AI coach → Connect** both
    make coach tokens. They are marked **Coach only** under Devices & tokens
    and in the admin's token list. **New token** still makes a full token, for
    a script of your own. For API users: `POST /api/auth/tokens` takes
    `"scope": "coach"`, token lists carry `scope`, and
    `app.cli create-token` takes `--coach`.
  - A coach token used for anything else shows up in the admin's auth activity
    feed as a refused token, once per token every six hours.
  - **Tokens you already have are not changed.** Every token from before this
    release stays a full token, including the ones assistants hold. To swap one
    for a coach token, revoke it under Devices & tokens and connect that
    assistant again; Claude and ChatGPT then ask you to sign in once more.
  - This release changes the database. As with any such release, an older
    version does not start on the upgraded database, so going back means
    restoring a backup from before the upgrade (the server makes one before
    it migrates, unless its backups are switched off).

### Changed

- The page that asks you to approve an assistant now also says what it cannot
  do, and **New token** points to Connect for assistants.

### Fixed

- **A scheduled workout could be attached to another athlete's plan**, and the
  calendar then showed that plan's name. It took knowing the plan's id, which
  is random and shown to nobody else, so on a household server this was
  unlikely to have been used. A workout can now only be attached to a plan of
  your own, and the calendar only names your own plans.

## [0.1.32] — 2026-11-27

### Fixed

- **ChatGPT was turned away when signing in**, with "Client ID … not found".
  Its client document says it can sign its token requests, and the server
  refused every client that says so, because it does not check such
  signatures. That refusal protected nothing: a code is only sent to the
  address in the client's own document and cannot be used without the proof
  that already guards every sign-in. Such a client is now accepted like any
  other, and ChatGPT is shown by name on the approval page.

### Changed

- The Connect dialog's entry for signing in is now called **Claude (web,
  phone, desktop)** and says that one sign-in covers all of Claude's apps. It
  read as if the web, the phone and the desktop app each needed setting up.

## [0.1.31] — 2026-11-27

### Fixed

- **The Tailscale add-on's sign-in link only worked for a minute.** The
  container gave up waiting after 60 seconds, restarted and printed a new
  link. A link opened later than that signed in a key that no longer existed:
  the Tailscale admin console gained a dead device called `loopback`, and the
  server was still not on the tailnet. The add-on now waits on one link for as
  long as it takes. If you were caught by this, remove the dead `loopback`
  device in the admin console before signing in again, or the real one is
  named `loopback-1`. Setting `TS_AUTHKEY` was not affected.

## [0.1.30] — 2026-11-27

### Added

- **Connect Claude on the web and phone by signing in.** claude.ai and the
  Claude phone apps cannot be given a token, so until now they could not use
  the coach at all. They can now be connected the way they expect: add the
  server's address as a custom connector, click Connect, and approve it on a
  page in the Loopback dashboard. Claude is handed a token of its own, which
  shows up as **Coach · Claude** under **Settings → Devices & tokens** and is
  revoked there like any other. Claude never sees a password.
  - This is OAuth 2.1 with PKCE on the coach endpoint: discovery documents
    under `/.well-known/`, `/oauth/authorize` and `/oauth/token`. A client
    identifies itself with a published client metadata document; registering a
    client with the server is not supported. Tokens do not expire and there are
    no refresh tokens, as for every other coach token.
  - Claude connects from Anthropic's servers, so this needs a server that can
    be reached from the internet over HTTPS on port 443. A server on a home
    network or tailnet keeps using the Claude Desktop extension.
  - Only the coach has to be public. The pages you sign in and approve on are
    opened by your own browser only, and `OAUTH_AUTHORIZATION_ORIGIN` puts
    them on another address than the one the assistant connects to, so a
    server can publish `/mcp`, `/oauth/token` and the two discovery documents
    and keep its dashboard private.
  - The server reads its own address from each request. `PUBLIC_URL` sets it
    for a proxy that does not pass the original `Host` header on.
  - **Settings → AI coach → Connect** has a **Claude (web & phone)** entry
    with the address to paste.
- **A Tailscale add-on that puts only the coach on the internet**
  (`deploy/tailscale/tailscale.yml`, enabled with one `COMPOSE_FILE` line in
  `.env`). For a home server with no domain and no open ports: it gives the
  server a Tailscale device of its own, with the dashboard, API and coach at
  `https://<name>:8443` for devices on your tailnet, and the coach alone at
  `https://<name>/mcp` for assistants that connect from the cloud. Everything
  else is refused by Tailscale before it reaches the server, so no page that
  takes a password is public. The device joins your tailnet through a link in
  its log, or a `TS_AUTHKEY`.
  - `OAUTH_AUTHORIZATION_PORT` tells the server that the pages you sign in and
    approve on are on another port of the same name. The add-on sets it, so
    there is no address to write down.

### Changed

- **`/mcp` checks the token before opening a session.** It used to check only
  that one was sent, and a wrong or revoked token found out from its first
  tool call. It now answers 401 straight away, which is how an assistant that
  signed in learns it has to do so again, and means a made-up token no longer
  gets a session. The 401's `WWW-Authenticate` header names the discovery
  document.
- The dashboard's pages are sent with headers that stop another site from
  showing them inside a frame.
- Signing in after being sent to the login page returns you to the page you
  were headed for.

## [0.1.29] — 2026-11-27

### Added

- **A Claude Desktop extension for the coach.** Connecting Claude Desktop
  meant installing Node.js, editing a config file by hand and quitting the
  app. The dashboard's **Settings → AI coach → Connect** now offers an
  extension for it instead: download `loopback-coach.mcpb`, open it and paste
  the token. Claude Desktop runs it with the Node.js it ships and keeps the
  token in the system keychain.
  - The server address is filled in by the download. The token never is, so
    the file can be passed on to someone else in the household, who pastes
    their own.
  - When the server restarts while Claude Desktop is open (an upgrade, a
    reboot), the extension opens a new session by itself.
  - `GET /api/coach/claude-desktop.mcpb` returns the extension. It needs a
    token like the rest of the API, takes an optional `serverUrl` to fill in
    the address, and answers 404 when `MCP_ENABLED=false`.
  - The by-hand setup with `mcp-remote` still works and is in the README.

### Fixed

- **`/.well-known/*` answered with the dashboard's HTML and a 200.** An MCP
  client that looked there for OAuth metadata after the 401 from `/mcp`, as
  Claude's "Add custom connector" does, got HTML where it expected a metadata
  document. Those paths are now a JSON 404, unless a real file exists in the
  build.

### Notes

- No migration, and nothing changes on the wire for the iOS app.
- The extension was tested in Claude Desktop on macOS. Windows is untested;
  the by-hand setup is the fallback there.
- Claude Desktop warns that an extension can access the computer and lists
  the developer as unknown. It shows both for an extension that is installed
  from a file and is not signed. This one reads no files: it passes messages
  between Claude Desktop and the server.
- An installed extension does not update itself. A later fix to it reaches
  people who download it again.
- If the server cannot be reached when Claude Desktop starts, the extension
  fails until Claude Desktop is restarted.

## [0.1.28] — 2026-11-25

### Added

- **Calendar entries are clickable.** A run or strength session on the
  calendar, in the month grid or the week list, now opens its details: the
  recorded workout when there is one, otherwise the plan for a strength
  session, or the watch queue with that item highlighted for a run that is
  still waiting. `GET /api/schedule/calendar` entries gain two nullable
  fields, `queueId` (the queue item behind a run) and `workoutId` (the
  workout recorded for it). A strength session's `workoutId` is the strength
  workout on the same day, the earliest if there are several.

### Notes

- Additive on the wire, and no migration. The iOS app ignores the two new
  fields.

## [0.1.27] — 2026-11-25

### Added

- **Fuelling on a workout.** The athlete can record what they drank and ate
  on a workout, and a planned session can carry a fuelling plan. This is
  entered by hand and is separate from the nutrition sync, which is daily
  totals read from Health.
  - **Saved products**, `/api/fuel/products` (list, create, change, delete):
    a gel or a drink mix saved once, with its carbohydrates and caffeine, and
    for a drink the serving those are for.
  - **The log on a workout**, `/api/workouts/{id}/fuel`: `GET` returns what
    was taken with its totals and hourly rates, next to the plan of the
    session the workout counts for. `POST` adds one entry, `PUT` replaces the
    list.
  - **The plan on a session**, `/api/workouts/queue/{id}/fuel`, with the same
    three methods.
  - `GET /api/fuel/history` lists the latest workouts that have a log.
  - A drink is one entry with the total volume; a gel or anything else is an
    entry of its own, with where in the workout it was taken (meters). An
    entry made from a product copies its name and figures, so changing or
    deleting the product leaves the record as it was.
- **Seven coach tools:** `get_fuel_products`, `add_fuel_product`,
  `get_fuel_history`, `get_workout_fuel`, `log_workout_fuel`, `get_fuel_plan`
  and `set_fuel_plan`. The coach can read how a long run was fuelled, log
  what the athlete tells it, and write the plan for the next one from the
  athlete's own products and earlier logs.
- **A pace calculator for the coach.** New coach tool `calculate_pace`: give
  two of a distance (`race` or `distance_m`), a `time` and a `pace`, and it
  returns the third, the pace per km and per mile, the speed in m/s for a
  workout's pace alert, and the split times at every km or mile and at 5K,
  10K, half and 30K. The coach is told to use it for every target pace,
  finish time and split it quotes, rather than doing the arithmetic itself.
  It converts between the numbers and does not judge whether a pace is
  realistic. The iOS app has the same calculator.

### Notes

- Shared with the coach under the existing **nutrition** category: without
  it the seven tools are not offered and the endpoints answer 403 to the
  coach. The app and the dashboard are not filtered.
- Migration `e7f8a9b0c1d2` adds `fuel_product` and `fuel_entry`. Nothing
  existing changes, and older app builds are unaffected.
- Fuelling is camelCase on the wire; volumes in ml, carbohydrates in g,
  caffeine in mg, positions in meters.
- `calculate_pace` has no endpoint and stores nothing, and it is offered
  whatever the athlete shares.

## [0.1.26] — 2026-11-25

### Added

- **Strength sessions on individual dates.** A strength plan's schedule could
  only repeat weekly, so an athlete without fixed gym days got every session
  on the wrong date, and none were ticked off because completion is matched
  by date. `metadata.schedule` can now hold `sessions`
  (`[{date, title, routineId}]`) next to or instead of the weekly pattern,
  and `skipDates` that take single occurrences out of the pattern.
  `PUT /api/plans/{id}/schedule` accepts dated sessions with or without a
  pattern.
- **Add, move or remove one session.**
  `POST /api/plans/{id}/schedule/sessions` adds a session on a date, and
  starts a schedule on a plan without one.
  `DELETE /api/plans/{id}/schedule/sessions/{date}` removes the sessions on
  a date, and `POST /api/plans/{id}/schedule/sessions/{date}/move` moves
  them (`{"to": "YYYY-MM-DD"}`). Removing or moving an occurrence of the
  weekly pattern changes that week only.
- Each session in a resolved schedule has **`recurring`**: false for a
  session on its own date, true for an occurrence of the weekly pattern.
- **Three new coach tools:** `add_strength_session`, `move_strength_session`
  and `remove_strength_session`. The coaching playbook tells the coach to ask
  whether the athlete lifts on fixed days, and to place individual sessions
  after looking at the week's runs when they do not.

### Changed

- The dashboard's plan screen shows a plan without a weekly pattern as
  "Sessions" with the number scheduled, instead of an empty weekday grid.

### Notes

- Additive on the wire, and no migration. `startDate`, `weeks` and `days` are
  always stored, derived from the sessions when there is no weekly pattern,
  because iOS builds up to 1.0 (15) need all three to read the plan.
- On those builds a plan made only of dated sessions shows them in the
  calendar, but its card and detail screen have no line for them. iOS build
  1.0 (16) names the next sessions there.
- Completion still matches by date: a dated session done on another day
  stays open.

## [0.1.25] — 2026-11-23

### Added

- **Illness and injury tracking ("setbacks").** A setback is an illness or
  injury with a first day, a severity, an optional body part and note, and a
  last day once it is over. The athlete can record how they felt on each day
  of it (worse, same, better, fine). New endpoints under `/api/setbacks`
  (camelCase, dates as `YYYY-MM-DD`): list, create, read, change, delete, and
  `PUT /api/setbacks/{id}/checkins/{date}` for the daily status. One illness
  can be open at a time, and one injury per body part.
- **The coach knows about a setback from the first message.**
  `get_plan_context` now returns `setbacks` (open ones, plus those that ended
  in the last three weeks) and a `setback_hint` telling the coach what to do
  about them. Four new coach tools: `get_setbacks`, `log_setback`,
  `update_setback` and `log_setback_status`, so an illness mentioned in
  conversation is recorded too. The coaching playbook has a new
  "Return to running after illness or injury" section.
- **A recovery check on every open setback.** Each open setback carries a
  `recovery` object saying whether it looks over: `looks_recovered`,
  `not_yet` or `insufficient_data`, with a one-sentence summary and the
  numbers behind it. For an illness, resting heart rate, HRV, breathing
  rate and sleeping wrist temperature are compared with the athlete's own median over the four weeks before
  it started; all comparable metrics (at least two) must be back within
  their usual range for two readings in a row. "Fine" on two consecutive
  days also counts, for injuries too, and a fresh "worse" or "same" holds
  the suggestion back. The app and the coach use it to ask the athlete;
  nothing closes a setback automatically.
- **Sleeping wrist temperature** as a daily health metric
  (`wrist_temperature`, °C, filed on the day the athlete woke up). It belongs
  to the recovery data domain, the coach reads it through
  `get_health_metrics`, and the recovery check uses it. Migration
  `d6e7f8a9b0c1`.
- A missed-run check-in can give **"sick"** or **"injured"** as its reason.

### Notes

- Setbacks are shared with the coach under the existing **recovery** data
  domain. An athlete who does not share recovery data keeps them to
  themselves: the coach tools are not offered and the plan context leaves
  setbacks out. The app and dashboard always show them.
- Migration `c5d6e7f8a9b0` adds the `setback` and `setback_checkin` tables
  and widens the check constraint on `workout_feedback.reason`.
- The iOS app needs this release for illness and injury tracking. An older
  app is unaffected.

## [0.1.24] — 2026-11-23

### Added

- **The calendar can start its weeks on Sunday.** Settings has a new "Week
  starts on" choice (Monday / Sunday), and the dashboard calendar's month
  grid, week view and weekday labels follow it. Like units, it is stored per
  user (`GET`/`PUT /api/me/week-start`), so it follows the athlete across
  browsers. Unset means Monday, so existing installs look exactly as before.

### Changed

- Calendar entries show how each session went instead of striking through
  completed ones. A completed session gets a check, a missed one (scheduled
  before today, neither completed nor skipped) gets an ✗, and only a skipped
  session is struck through. The "This week" list says missed and skipped the
  same way. A session scheduled today is never shown as missed.
- On the calendar's month grid, a day where a run and a strength session
  collide is now marked with a small warning icon next to the day number
  instead of an amber border, which looked too much like today's highlight.
  Today is the only cell with a highlighted border. The legend shows the
  same icon.

## [0.1.23] — 2026-11-23

### Added

- **Heart rate recovery and VO2 max on a workout.** A workout upload can
  carry `endHeartRate`, `heartRateAfter1Min` and `heartRateAfter2Min` (bpm as
  the workout ended and one and two minutes later) and `vo2Max` (the estimate
  Health recorded for that workout). They are stored on the workout and
  returned by the workout list and detail as `end_heart_rate`,
  `heart_rate_after_1min`, `heart_rate_after_2min` and `vo2_max`, so the
  coach sees them in `get_recent_runs` and `get_workout_detail`. VO2 max
  follows the athlete's `body` sharing choice, like the daily figure: a coach
  read gets it blank when `body` is withheld. Needs an app build that sends
  them; existing workouts stay empty until the app sends them again
  (migration `a3b4c5d6e7f8`).

## [0.1.22] — 2026-11-21

### Fixed

- A plan is no longer offered as complete when every queued session is done
  but its end date is still ahead. A plan that is filled in a week at a time
  was reported `finishable` at the end of each week. A plan past its end
  date, or without one and with every session done, is offered as before.

## [0.1.21] — 2026-11-21

### Added

- **The coach can work with the athlete's shoes.** `get_shoes` lists the
  pairs with the distance on each, the replacement target, the default pair
  and which are retired. `add_shoe` adds a pair, `update_shoe` renames it,
  corrects its distances, makes it the default, retires it or brings it back,
  and `assign_shoe` puts a pair on a workout or takes it off. `get_recent_runs`
  takes a `shoe_id` to list the runs done in one pair, and `GET /api/workouts`
  takes the same filter. Deleting a pair stays in the app.
- **A run knows whether its shoes were checked.** Workouts carry
  `shoe_confirmed`: false while the pair is still the one assigned
  automatically, true once it was picked, changed or taken off by hand
  (`PUT /api/workouts/{id}/shoe`, from the app or the coach). The coach is
  told to ask about recent unchecked runs when more than one pair is in
  rotation. Runs from before this version all start unchecked.

## [0.1.20] — 2026-11-19

### Added

- **Link a workout to a planned session afterwards.** A run recorded without
  starting the planned session from the watch, on another day, or as
  something else than was planned can now be counted for that session
  (`PUT /api/workouts/{id}/plan-link`, `planWorkoutId: null` to unlink).
  Linking completes the session, so it counts towards the plan and is no
  longer reported as missed; unlinking reopens it. A session counts one
  workout: linking another takes the first one off. A link made or removed
  by hand is marked `plan_link_manual` on the workout and survives the app
  re-uploading it. The coach sees the flag in `get_workout_context`. Needs a
  version of the app with linking.

### Fixed

- `GET /api/workouts/inventory` reports a session as complete when its queue
  item is completed, not only when the watch says so. The coach's missed-run
  list is built from it.

## [0.1.19] — 2026-11-17

### Added

- **Shoe tracking.** Add pairs of shoes with a starting mileage and an
  optional target (`/api/shoes`), and see the distance on each: the starting
  mileage plus every workout run in the pair. One pair can be the default,
  which new runs are assigned to as they sync; any workout can be given a
  different pair, or none (`PUT /api/workouts/{id}/shoe`). Runs from before a
  pair was added are not assigned to it, since that distance is what the
  starting mileage is for. Needs a version of the app with shoe tracking.
- **Built-in HTTPS for a server with a domain.** Two lines in `.env`
  (`COMPOSE_FILE=docker-compose.yml:deploy/https/caddy.yml` and `DOMAIN=`)
  add a Caddy container that obtains and renews a Let's Encrypt certificate
  and serves the dashboard, API and coach at `https://<DOMAIN>`. It also
  closes plain-HTTP port 8001 to everything but the host.
- **`FORWARDED_ALLOW_IPS`** passes through to the server, for installs behind
  their own reverse proxy. Without it every proxied client appears as the
  proxy: the login rate limit is one bucket shared by everyone and the audit
  trail shows the proxy's address on every event. The Caddy file sets it.

## [0.1.18] — 2026-11-13

### Added

- **"Connect your coach" in the dashboard.** Settings has an AI coach card for
  athletes: pick Claude Desktop, Claude Code, Cursor, VS Code or another client,
  and it creates a token and shows the setup with the server address and token
  already filled in, ready to copy. Hidden for admins and when
  `MCP_ENABLED=false`; `/api/health` now reports `mcp` so the dashboard can
  tell. Each app gets its own token, named after it, so one can be revoked
  without touching the others.

### Fixed

- **Setup instructions for Claude Desktop and Claude Code.** Node.js 20.18 is
  the stated minimum (what the `mcp-remote` helper's dependencies now declare;
  the instructions said 18), and the Claude Code
  command now uses `--scope user`: without it the server was registered only
  for the folder the command happened to be run in.

## [0.1.17] — 2026-11-12

### Added

- **The coach MCP is built into the server.** It is served at `/mcp` on the
  same port as the API and dashboard, from the same container, with no
  configuration: wherever the dashboard is reachable, the coach is too. Each
  caller still authenticates with their own token (`Authorization: Bearer`),
  and a request without one gets a 401. `MCP_ENABLED=false` turns the endpoint
  off.

### Changed

- **Running the MCP as a separate process is now optional** — only needed for
  a stdio client that launches it, or to run it on a different machine. If you
  run one today (default port 8590), point your clients at
  `http://<server>:8001/mcp` and retire it; nothing else changes.
- The MCP's Python package is renamed `app` → `training_mcp` so it can share a
  process with the backend. `uv run start` is unaffected. A standalone
  install that runs `.venv/bin/start` directly needs one `uv sync` after
  pulling (the old script still points at `app.main`), and anything calling
  the module path (`python -m app.main`) needs `training_mcp.main`.

## [0.1.16] — 2026-11-12

### Added

- **Configurable route-map tiles.** CARTO now serves an "API key required"
  watermark for keyless tile requests, which broke the route maps. Set
  `CARTO_API_KEY` (CARTO's free key) to use the keyed dark tiles, or
  `MAP_TILE_URL` (plus `MAP_TILE_ATTRIBUTION` / `MAP_TILE_SUBDOMAINS`) to use
  any other provider. The dashboard reads it at runtime from the new
  authenticated `GET /api/config`, so the published image needs no rebuild.
  With neither set, behaviour is unchanged (and, until you add a key, still
  watermarked).
- **Metric / imperial display units in the dashboard.** Distance, pace and
  weight can be shown in miles, min/mi and lb. Metric is the default; imperial
  is opt-in under **Settings → Units**. Display only: the API still speaks
  metric.
- **The units choice is stored on your account**, not in the browser, behind
  the new `GET/PUT /api/me/units`. The dashboard follows it on every device,
  and a choice already made in a browser is carried over the first time you
  open the dashboard after upgrading. The coach reads it too: `get_plan_context`
  now returns `units` and a `units_hint`, so an athlete on miles is coached in
  miles and gets distance goals authored in miles. Unset (`null`) until
  someone chooses, so the iOS app can keep defaulting from the phone's region.
  Splits stay 1 km splits (only their pace converts), and server-written
  warning text on the plan screen is shown as written.

## [0.1.15] — 2026-09-20

### Added

- **`upcoming` plan status, and the distinction it forces.** A block built
  ahead of its start date used to be `active`, so it competed with the block
  actually being run: it won "which plan am I on" lookups by being newest, and
  the dashboard's hero card computed "week 1 of N" off a future start date.
  `upcoming` separates the two — but only half the readers wanted the new
  status. Anything reasoning over the *future timeline* (calendar, strength
  collisions, `next_plan`) needs those sessions, because they are real and
  dated; only "which plan is current" wants `active` alone. That split is now
  a named constant (`SCHEDULED_STATUSES`) rather than a literal repeated at
  each call site, since getting it wrong is silent: the sessions simply don't
  appear, and a check that finds nothing looks exactly like a check that
  passed. The MCP `create_plan` gained a `status` argument, without which
  every plan a coach built landed `active` by default.

### Changed

- **The coach can tell a plan change from a miss.** The iOS app now lets the
  athlete move or skip a run before it lapses, through the same feedback
  endpoint as a missed-run check-in. The MCP feedback tools and instructions
  say how to tell the two apart: an entry acknowledged on or before its
  scheduled day was filed ahead of time, while a missed-run check-in always
  comes on a later day. A skip with reason `other` and a note like "Made room
  for <run>" was cleared off the day another run moved onto.

### Fixed

- **A schedule could be attached to a running plan, and everything downstream
  mis-typed itself.** Nothing enforced the docstring's "create it with
  `activity_type: 'strength'`": the plan's session counts absorbed the gym days
  (a running plan reporting 27 sessions — 15 queued runs plus 12 strength),
  calendar entries for gym sessions were stamped `activityType: "running"`, and
  the iOS app rendered the run block as a gym cycle purely because a schedule
  was present. `PUT /api/plans/{id}/schedule` now 400s on a non-strength plan.
  Guarded on write only, so an existing plan can't start 404-ing on read.

- **Calendar strength entries carried the plan's activity type, not the
  session's.** One entry could claim two vocabularies at once: `activityType:
  "strength"` beside a `completed` flag computed against
  `traditionalStrength`. They now agree.

- **An edit ack updated the composition but not the item title.** `title` is a
  column and `displayName` a key inside `workout_data`; writing only the blob
  left the list title describing the previous session ("Easy 35 min" on a
  30-minute run) with nothing marking which of the two was stale. The ack now
  re-syncs the title — but **only when it was tracking the composition**. A
  title that already diverged is a deliberate label (coaches annotate the list
  title, "… (cap 140) — OPTIONAL", while the watch name stays terse), and
  overwriting it on every ack destroys that. The old blob is still in hand at
  ack time, so "was it tracking?" is an exact question rather than a guess.

- **Ramp warnings nobody could act on.** A layoff inside the 4-week baseline
  window drags the baseline down and inflates every ratio measured against it:
  after a 9-day break, a return at 19 km against a true 17.6 km/wk base scored
  1.71× and three `critical`s that could only be cleared by prescribing
  detraining. Zero weeks are still counted — dropping them would silently
  redefine the average as "the weeks you happened to run", and let a two-week
  layoff resume at full volume with no warning at all — but a degenerate
  window now caps severity at `warn` and the warning ships its constituent
  weeks (`baseline_weeks`) so the number can be checked instead of trusted.
  The check was also non-monotonic in break length: one week longer and
  `MIN_BASELINE_KM` disabled it entirely, so a *longer* layoff produced
  *fewer* warnings.

- **`update_queued_workout` destroyed data on any item past `pending`.** It
  read the current composition back from the pending-only endpoint, so for a
  synced item it started from `{}` and the PATCH then dropped `displayName`,
  `activityType`, `location`, `warmup` and `cooldown`, and nulled
  `scheduled_date`. It now reads through the full listing and refuses to write
  at all when the item isn't found, rather than writing a partial blob.

- **Plan create/update responses left `progress` and `finishable` at their
  defaults.** `progress: null` reads as "not computed", but `finishable: false`
  is a plausible-looking value indistinguishable from a real one — the same
  plan in the same second answered `true` on `get`. Both are now computed on
  every response that returns a plan.

- **MCP tool inputs.** Optional object/array params render as `anyOf` with no
  top-level `"type"`, and a client reading `schema["type"]` to decide whether a
  value is structured finds nothing and sends JSON as a string — so `metadata`
  and `blocks` arrived as `str` and were rejected. The annotations and the
  emitted schema were both already correct; the string arrives anyway, and it
  arrives from the model composing the call, which no server-side schema change
  can reach. All nine affected params now accept a JSON string. Separately,
  `summary`'s 280-character limit lived only in prose, so it 422'd at the
  backend instead of failing tool validation, and `PlanStatus` omitted
  `archived` — a value already in use.

- **`get_missed_workouts` lost a moved run for good.** Any feedback entry hid
  the run, so one that was moved and then also went past its new day was
  never reported. A move's entry now only settles the day the run left.

## [0.1.14] — 2026-09-19

### Added

- **`GET /api/workouts/queue/scheduled?from=<ISO datetime>` — the watch
  schedule a device should have.** Delivered queue items (`fetched`/`synced`)
  scheduled at or after `from`, as compositions in the same shape as the
  pending endpoint, ordered by date. `synced` is recorded per account, not per
  device: once one install confirms an item, the pending endpoint never offers
  it again. So a reinstall or a new phone came up with an empty watch
  schedule, an empty calendar and no upcoming runs, while the plan still
  listed every run. The iOS app now diffs this list against its WorkoutKit
  schedule on every sync and re-schedules what's missing. Completed and
  skipped items are excluded, which is what keeps an acknowledged coach delete
  (→ `skipped`) from coming back.

### Fixed

- **Moving a missed run now re-dates its queue item.** Feedback with
  `action: "move"` recorded the new date only on the feedback row, while the
  app re-dated the run on the watch. The queue item kept the old day, so the
  calendar, schedule validation and the coach all saw the run where it no
  longer was, and a restore on a new phone would have skipped it as past. The
  item's `scheduled_date` and `workout_data.scheduledDate` now follow the move
  (normalised to whole-second UTC for the app's decoder). Dismissed moves and
  completed or skipped items are left alone, as with skip.

### Changed

- **The Docker image installs exactly what `uv.lock` pins** (`uv sync --locked`)
  instead of resolving the `pyproject.toml` ranges at build time. Every build
  used to pick up whatever versions were newest that day. That is how fastmcp
  4.0 broke CI with no change in this repo, and the image was exposed the same
  way. The build now also fails if the lock has drifted from `pyproject.toml`.
  CI installs the same way.

## [0.1.13] — 2026-08-01

### Fixed

- **The Health screen's range toggle moved the data but not the numbers.**
  Every summary stat was computed over a hardcoded tail rather than the
  selected range — sleep over the last 14 nights, steps over the last 30 days,
  macros and energy over the last 21 logged days, the protein dots over 12
  weeks, the table over 8 rows. Switching 30d → 1y refetched a year and then
  averaged the same trailing window, so only the recovery and weight *line
  shapes* changed. On this data the steps average read 6,711 at all three
  settings; it should read 6,711 / 4,208 / 5,397.

  Sleep and steps now cover the whole selected range, and **aggregate into ISO
  weeks beyond 30 days** — 365 daily bars in a 1080-unit viewBox is a ~3px
  slot, which is neither readable nor a usable hover target. Their headings
  say so (`Sleep · weekly`, `Steps · weekly average`) and the tooltip reports
  how many days back each bar.

  Two averaging traps that the weekly view makes easy to fall into, avoided:
  the headline is averaged over **days in range, not over the bars**, since a
  bar is already a mean and a 3-day week would otherwise weigh the same as a
  7-day one; and a sleep stage is averaged over the nights that **recorded
  stages**, not all nights, or a night with no breakdown drags every stage
  down and the stack falls short of its own total.

  Nutrition charts scale their window with the range but are deliberately
  **not** bucketed into weeks: they plot *logged* days, which are sparse, and
  a weekly mean over two logged days is an anecdote wearing the costume of a
  summary. The week-by-week table now states its cap ("most recent 12 of 31
  weeks") instead of silently stopping, which reads as "that is all the data
  there is".

## [0.1.12] — 2026-08-01

### Added

- **Per-domain data consent.** The athlete chooses in the iOS app which
  categories of health data the coach may read — `training`, `recovery`,
  `body`, `activity`, `nutrition` — and the app reports the set on every
  launch. `PUT /api/me/data-consent` stores it (`GET` reads it back); the set
  replaces wholesale rather than merging, `training` is always included, and
  unknown domain strings are stored rather than rejected so a newer app can't
  have its consent push broken by an older server.

  The default for an athlete who has never reported is **all five domains**.
  An absent record means "not yet reported", not "restricted": an install
  predating consent had no way to limit anything, and reading that silence as
  a restriction would strip a working coach of its context. The window where a
  failed push leaves a domain shared is one app launch.

- **The MCP advertises only the tools the athlete shares.** `get_nutrition`,
  `get_nutrition_summary` and `get_health_metrics` are dropped from
  `tools/list` when their domains aren't shared. Filtering the list rather
  than refusing the call is the point: a tool that is listed and then errors
  produces a coach that retries, apologises and tells the athlete to go enable
  sleep tracking — the nagging the app's own surfaces exist to avoid. A tool
  that was never listed is never reasoned about.

- **Reads are column-filtered, not just tool-filtered.** `recovery`, `body`
  and `activity` are columns of one `daily_health_metrics` row, so tool-level
  filtering alone would disclose all three together. Requests carrying
  `X-Consent-Scope` (which the MCP sends on every call it makes) get the row
  with unshared columns **absent** — not null, since null already means "not
  tracked" and the coach would report a gap the athlete doesn't have. The
  athlete's own dashboard and the iOS app send no such header and are
  unaffected. `GET /api/nutrition*` and the sleep-sample read answer 403 when
  their domain isn't shared, with a message that says *not shared*, never
  *not recorded*.

- Admin **Users** screen shows what each athlete shares, flagging
  **"not reported"** in amber — otherwise a consent push that never lands is
  indistinguishable from an athlete who chose everything.

- **Dashboard: "Energy in vs out" on the Health screen.** The energy-balance
  numbers the API has computed since 0.1.10 were never surfaced anywhere. The
  Nutrition block now leads with a per-day chart of food logged against energy
  burned, and the week-by-week table gained **In / Out / Balance** columns
  (`expenditure.tdee_kcal_avg` and `balance_kcal_avg`, each with the day count
  backing it).

  Drawn as a bullet chart — burn is the container, food is how much of it got
  filled — because shading the difference as its own block made it read as a
  second *stacked* segment, i.e. as something added to intake rather than the
  room left above it. A day is paired only when it holds both a complete
  intake and a complete TDEE: **today is always excluded** (health metrics
  carry no `partial` flag, so a day in progress stores the hours elapsed and
  looks like a genuinely low-burn day), and a day missing basal gets no burn
  line rather than falling back to active alone — active is about a third of
  the total, so that fallback would invent a ~2000 kcal deficit out of a
  missing column.

- **Dashboard: hover tooltips on every chart.** All nine hand-rolled SVG charts
  (recovery, sleep, weight, steps, energy balance, macros, protein per kg,
  heart-rate trace, cadence) now report the value under the pointer, with the
  hovered mark highlighted and the rest dimmed. Line and dot charts also get a
  crosshair and an on-line marker. They previously carried SVG `<title>`
  elements, which the browser renders as a slow native tooltip that can't show
  more than one line and never appears on a line chart's individual points.

  One primitive in `components/charts.tsx` (`useChartHover` + `ChartTooltip`)
  rather than nine implementations. It resolves the pointer against the wrapper
  element's rect, not the SVG: every chart here stretches a fixed viewBox with
  `preserveAspectRatio="none"`, so viewBox units are not screen pixels and the
  event's SVG coordinate is meaningless. The tooltip pins to the top corner
  *away* from the hovered mark instead of tracking it — a tooltip centred on
  the mark covers it whenever the card is short (150px card vs ~140px
  tooltip), and one that tracks horizontally has no width it can clamp itself
  to without measuring, so it overflows on a narrow screen.

### Changed

- **`GET /api/nutrition/summary` respects consent per block.** The payload is
  named for nutrition but carries `body` (weight) and `expenditure`
  (active/basal energy) too, so gating it on `nutrition` alone would have
  disclosed both. `body` and the weight-derived `protein_g_per_kg` need
  `body`; `expenditure` — including the balance, which is not reportable
  without a TDEE — needs `activity`.

- **Domain guidance moved from the server instructions onto the tools.** The
  instructions are fixed when a connection opens, before any middleware runs,
  so they reach every athlete regardless of what they share — a page about
  nutrition tooling for a coach with no nutrition tool. Tool descriptions ship
  only when their tool does, and they already carried most of the same text in
  near-identical words. The instructions keep what holds for every athlete
  (training, continuity, plans, queue, units); the health and nutrition
  guidance now lives on `get_health_metrics` and `get_nutrition_summary`.

- `auth_events` gained `data_consent_changed`, written only when the reported
  set actually differs. `data_consent_reported_at` is stamped on every report
  so "never reported" stays distinguishable from "reported, unchanged" — one
  timestamp cannot answer both questions.

## [0.1.11] — 2026-07-31

### Fixed

- **`weight_change` is a fitted trend, not last-minus-first.** Weigh-in
  conditions vary systematically — clothed or not, before or after a meal —
  so differencing the first and last reading reports the gap between two
  arbitrary conditions as a trend. On a real six-day series alternating
  between two conditions ~2.4 kg apart, with the mean flat throughout, that
  yielded **+2.9 kg**; a least-squares fit across the readings' span gives
  +1.78. The `body` block now also carries **`weigh_ins`** (how many readings
  back the numbers — the coverage count every other average in this response
  already had) and **`weight_sd`** (the scatter the fit sits in).

  `weight_sd` matters more than the improved point estimate, and the fit is
  deliberately not sold as a fix: where weigh-in conditions correlate with
  time — as they do here, the heavier readings falling ~1.3 days later on
  average — the condition is confounded with the trend and no estimator can
  separate them from the readings alone. Reporting the scatter alongside is
  what makes a change of the same order as its own noise visible as such.
  `weight_start`/`weight_end` are unchanged; they remain raw facts.

### Changed

- **Nutrition MCP instructions trimmed in favour of signal.** The energy-balance
  guidance told the model what to conclude ("prefer `weight_change` when the two
  disagree"), which on noisy weight data means preferring one artifact over
  another. It now states only what the payload cannot reveal — that
  `weight_change` is a fit rather than a difference, that basal is an estimate,
  and that under-reported intake biases the computed deficit larger — and
  points at `weigh_ins`/`weight_sd` so the model can judge coverage itself.

## [0.1.10] — 2026-07-31

### Added

- **Energy expenditure, so intake has something to be weighed against.**
  `daily_health_metrics` already held `active_energy_burned` — movement plus
  exercise, the "leeway you earned" figure a food logger shows — but total
  daily expenditure also needs the resting half, so this adds
  **`basal_energy_burned`** (HealthKit estimates it directly; no BMR formula
  over a profile). `GET /api/nutrition/summary` gains an **`expenditure`**
  block per period: average active, basal, TDEE and energy balance, aligned on
  the same buckets as intake, body weight and training load, so "am I eating
  for my training?" stays one call. `get_nutrition_summary` and
  `get_health_metrics` surface it to the coach.

  Three things the shape is deliberate about. **TDEE is active + basal and
  nothing else** — active already includes workout calories, so adding
  `training.energy_kcal` on top double-counts every session. **Balance is
  averaged over days holding both a complete intake and a complete TDEE**,
  not by differencing the two period averages, which would silently compare a
  3-day mean against a 7-day one; each average carries its own day count for
  the same reason `days_logged` accompanies intake. And **today is excluded**:
  health metrics have no `partial` flag, so a day still in progress stores
  only the hours elapsed and would read as a genuinely low-burn day.

  Basal is null until a syncing client sends it, in which case TDEE and
  balance are null too and active reports alone — degraded, not broken.

### Changed

- **The MCP's blanket "do not compute an energy balance" is now a calibrated
  rule.** That instruction was written when only the intake side existed;
  with expenditure available the useful answer is a direction, not a refusal.
  The coach is now told to report balance directionally and never as a
  measured quantity, because the two error sources compound rather than
  cancel — self-reported intake skews low, which biases the *computed* deficit
  larger, so a "500 kcal deficit" is routinely nearer 200 — and that scale
  weight over 3–4 weeks is the arbiter, being the one number in the block that
  isn't modelled. When weight and balance disagree, the balance is wrong.

## [0.1.9] — 2026-07-30

### Added

- **`clear` on the nutrition upsert, and `DELETE /api/nutrition/{date}`.**
  Omitted fields never overwrite — the rule that lets an older client ship
  fewer fields safely — but that left a client unable to retract what it has
  *stopped* reporting: gating a field app-side froze the stored value instead
  of removing it. `clear: ["micros", "potassium_mg"]` on a day nulls the named
  fields explicitly (omission means "no opinion", `clear` means "known
  absent"); sending a value for a field also named in `clear` is a 422 rather
  than a silent guess, and non-clearable names are rejected. The DELETE drops
  a whole day, for rows that should never have been stored — a stray day a
  backfill swept in. Neither is exposed through the MCP: the coach reads
  nutrition, it does not edit it.

### Fixed

- **Six more nutrition fields reclassified as lower bounds, not totals.**
  0.1.8 called out `micros` and `potassium_mg` but listed sodium, fiber, sugar
  and saturated fat as reliable — inferred from their values merely looking
  plausible, which proves nothing about completeness. In fact only
  `energy_kcal`, `carbs_g`, `protein_g` and `fat_g` are daily totals;
  `sodium_mg`, `fiber_g`, `sugar_g`, `saturated_fat_g`, `cholesterol_mg`,
  `potassium_mg` and every key in `micros` sum only those logged foods whose
  database entry carried the field. They ship ungated on purpose — a lower
  bound is still useful — and nothing in the wire format marks them, so the
  MCP instructions and tool docs now carry the classification: "at least X" is
  sound, inferring a deficiency or an excess never is, and trends in a bounded
  field track logging detail as much as diet.

## [0.1.8] — 2026-07-30

### Fixed

- **Micronutrient sums are no longer presented as intake.** Verified against
  real food-logger data on 2026-07-30: potassium read 23–206 mg and iron
  0.2–2.8 mg on 1,100–2,600 kcal days — 5–12% of any plausible intake. The
  cause is upstream of this server and of the syncing app: food databases carry
  energy and macros on nearly every entry but micronutrients on only a
  fraction, so a day's `micros` and `potassium_mg` faithfully sum a sparse
  subset of what was eaten. Macros are sound over the same rows
  (macro-derived kcal reconciles with reported kcal within ±11%). The MCP
  server instructions and both nutrition tool docstrings now state which
  fields are reliable (energy, carbs, protein, fat, saturated fat, fiber,
  sugar, sodium) and forbid inferring a deficiency from the rest — without
  this, the first coaching conversation to read those numbers would report a
  severe deficiency that does not exist. Also documents that null
  `water_ml`/`caffeine_mg` means unreported, never zero intake.

### Notes

- MCP-side and documentation only. The Docker image is unchanged from 0.1.7
  apart from the version string; self-hosters running the MCP should pull the
  repo, others have nothing to gain from upgrading.

## [0.1.7] — 2026-07-30

### Added

- **Nutrition.** Daily dietary totals synced from HealthKit — energy, carbs,
  protein, fat, saturated fat, fiber, sugar, sodium, potassium, cholesterol,
  water, caffeine, plus an open `micros` map for anything else a food-logging
  app writes. New `daily_nutrition` table (migration `c3n4u5t6r7i8`),
  `POST/GET /api/nutrition` with the same "null fields never overwrite"
  upsert contract as health metrics, and `entry_count`/`sources` recording
  logging adherence. An absent row means *not tracked*, never *ate nothing*;
  `partial: true` marks a day synced while still in progress and keeps it out
  of every average until a later sync completes it.
- **`GET /api/nutrition/summary`** — intake, body weight and training load
  aligned on the same weeks or months, with `protein_g_per_kg` and
  `days_logged`/`days_in_period` coverage on every row. Diet against
  performance is the question this feature exists for, and answering it
  previously meant three queries and re-deriving week boundaries by hand.
  Bucketing is pure and unit-tested (`app/nutrition_summary.py`), done in
  Python rather than SQL `date_trunc` because nutrition is keyed by local date
  while workouts carry an instant — pass `timezone` to attribute a
  late-evening workout to the day the athlete actually ran it.
- **MCP tools `get_nutrition` and `get_nutrition_summary`**, with server
  instructions that push the coach toward the summary and spell out how to
  read the data honestly: check coverage before averaging, treat
  self-reported intake as trend-not-total, and judge weight against diet over
  3–4 weeks rather than week to week.
- **Dashboard: a Nutrition block on the Health screen** — macro composition,
  energy intake, protein per kg against the 1.6–2.0 g/kg band, and a
  week-by-week table carrying intake, weight change and training load
  together. Partial days are dimmed rather than hidden.
- The demo seeder now seeds nutrition, deliberately imperfect (a fifth of days
  unlogged, one week missed entirely, today partial) so the demo exercises the
  coverage signals rather than an unrealistically complete log.

### Notes

- The iOS app does not yet ship nutrition; until it does, the tables and
  screens stay empty. App-side spec: `docs/app-nutrition-handoff.md`.

## [0.1.6] — 2026-07-24

### Fixed

- **`POST /api/plan-notes` now accepts `kind: "feedback"`.** The plan-completion
  flow wrote feedback notes ORM-side and the MCP's `append_plan_note` advertised
  the kind, but the request schema's pattern predated it — so authoring one via
  the API 422'd. Note kinds are now single-sourced in `NOTE_KINDS` (used by both
  the create and update schemas).
- **The MCP surfaces the API's error detail instead of a bare status code.**
  A validation failure used to reach the LLM as an opaque
  `Client error '422 Unprocessable Content'`, leaving it to retry the same
  payload blindly. The MCP's HTTP client now parses the response body (including
  FastAPI's field-level validation errors) into the raised message, e.g.
  `Training API returned 422 for POST /api/plan-notes: summary: String should
  have at most 280 characters`.

## [0.1.5] — 2026-07-23

### Added

- **Sample-free workout detail.** `GET /api/workouts/{id}?include_samples=false`
  replaces the raw per-second arrays in `data` (GPS `route`, `cadence`,
  `heartRate`) with a compact `data.samplesSummary` — per-series count and
  avg/min/max, plus jitter-filtered elevation gain/loss for the route. A GPS
  run's detail response shrinks from ~650 kB to a few kB. The MCP's
  `get_workout_detail` and `get_workout_activities` now always request the
  compact form (the full payload, doubled by MCP text+structured serialization,
  exceeded 1 MB and broke LLM clients); `get_workout_heartrate` and
  `get_workout_splits` still serve the raw series. The default response is
  unchanged, so the dashboard's route map and charts are unaffected.

## [0.1.4] — 2026-07-23

### Added

- **Per-token client visibility.** Each API token now remembers the last
  client `User-Agent` seen on it (written alongside the existing throttled
  `last_used_at` bookkeeping — an agent change, e.g. an app update, always
  writes immediately). Token lists in the dashboard (admin Users screen and
  own Settings) show a compact client label — e.g. `Loopback iOS 1.0`,
  `browser` — with the full string on hover, and the `lastUserAgent` field is
  on both token wire shapes. Groundwork for the iOS app's version handshake:
  once the app sends `Loopback-iOS/<version>`, the admin can answer "which
  devices still run an old app" before shipping a breaking change.

## [0.1.3] — 2026-07-23

### Added

- **Stranded-device visibility.** A device still presenting a revoked,
  expired, or deactivated-account bearer token used to fail with silent 401s;
  those rejections now appear as `token_rejected` events in the admin
  auth-activity feed. Expired/inactive rejections name the user and token
  ("alice's token 'iPhone' rejected — expired"); unknown tokens can't be
  attributed and show a short token fingerprint instead, so repeats are
  recognizable. Events are throttled per device (per source IP for unknown
  tokens) to at most one per 6 hours, so a retrying device or a scanner can't
  flood the feed.

## [0.1.2] — 2026-07-23

### Added

- **First-run setup screen.** A fresh install now greets the browser with a
  create-admin-account screen instead of a dead login form: the dashboard
  detects that no admin password exists (`GET /api/auth/setup`) and walks you
  through creating the account (`POST /api/auth/setup`), landing you signed
  in. The endpoints close permanently once a passworded admin exists — a
  deactivated admin keeps them closed, and an existing passworded account can
  never be taken over; lockout recovery stays the CLI. The POST is
  rate-limited like login and completing setup shows up in the admin
  auth-activity feed. `BOOTSTRAP_ADMIN_PASSWORD` works unchanged for
  headless/scripted installs and skips the screen entirely.

## [0.1.1] — 2026-07-23

### Added

- **Server-managed backups.** The server now backs itself up: a nightly
  `pg_dump` into the `/backups` mount (`BACKUP_TIME`, default 03:30 container
  time; newest `BACKUP_KEEP` dumps retained, default 30), a catch-up backup
  shortly after startup when the newest dump is stale, and — new safety net —
  an automatic dump **right before pending database migrations** run on an
  upgrade. The admin System screen gains a **Back up now** button
  (`POST /api/admin/backup`). Set `BACKUP_ENABLED=false` to keep managing
  backups yourself; freshness reporting works either way.

### Changed

- The compose `/backups` mount is read-write by default now (was `:ro`).
  Host-managed setups should add `:ro` back in an override file alongside
  `BACKUP_ENABLED=false`.
- The Docker image includes `postgresql-client` (pg_dump).

## [0.1.0] — 2026-07-23

First tagged release — everything before this shipped straight from `main`.

### Highlights

- **Workout storage & analytics** for all HealthKit workout types (running,
  cycling, strength, …) with splits, heart-rate samples, cadence, GPS routes,
  and summary aggregation by week/month/year
- **Apple Watch training queue**: structured workouts (intervals, pace alerts)
  served as WorkoutKit compositions to the companion iOS app, with device
  inventory, edit/delete actions, and missed-workout feedback
- **Training plans** with goals, guardrails, and phases; recurring weekly
  strength schedules; a unified calendar merging runs and strength sessions
  with conflict flags; an explicit plan-completion flow
- **Plan validation** — a deterministic schedule "linter": weekly-ramp and
  taper checks, missing down weeks, back-to-back hard days, guardrail breaches
- **Daily health metrics**: sleep, heart rate, HRV, weight, VO₂max, steps,
  body composition
- **Multi-user auth**: argon2 passwords, per-device revocable API tokens,
  rate-limited login, and an auth audit trail
- **Web dashboard** (React SPA served same-origin by the API): athlete screens
  for overview/calendar/workouts/plans/notes/health/queue, plus an admin
  console for user/token management and system monitoring
- **MCP server** so any MCP client can act as an AI running coach over your
  own data (stdio or streamable HTTP, per-user token passthrough, coaching
  playbook)
- **Self-host niceties**: single `.env` configuration, GHCR multi-arch images
  (amd64/arm64), automatic migrations on startup, backup-freshness reporting,
  and an isolated demo stack with a synthetic-athlete seeder

[0.1.1]: https://github.com/aderaaij/loopback-training-server/releases/tag/v0.1.1
[0.1.0]: https://github.com/aderaaij/loopback-training-server/releases/tag/v0.1.0

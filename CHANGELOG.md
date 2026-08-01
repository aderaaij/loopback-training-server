# Changelog

Notable changes to Loopback Server. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) — with the usual 0.x caveat that
**breaking changes bump the minor version** until 1.0.

Each release `vX.Y.Z` is a git tag and publishes multi-arch Docker images
tagged `X.Y.Z` and `X.Y` to GHCR (see README "Releases & upgrading").
The running server reports its version at `/api/health` and on the admin
System screen.

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

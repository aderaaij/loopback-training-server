/**
 * Wire types for the training-api backend.
 *
 * Casing is intentionally inconsistent per resource — it mirrors the actual
 * FastAPI serialization (only auth, feedback, calendar and parts of
 * plan-notes/plan-schedule use camelCase aliases; the rest is snake_case).
 * Do not "fix" the casing here without changing the backend.
 */

// ── auth (camelCase) ──

export interface AuthUser {
  id: string
  username: string
  displayName: string
  role: 'admin' | 'user' | (string & {})
}

export interface LoginResponse {
  token: string
  tokenId: string
  user: AuthUser
}

/** GET /api/auth/setup — true while no admin account has a password (fresh install). */
export interface SetupStatus {
  required: boolean
}

export interface ApiTokenInfo {
  id: string
  name: string
  createdAt: string
  lastUsedAt: string | null
  /** Last client User-Agent seen on this token (e.g. "Loopback-iOS/1.0"). */
  lastUserAgent: string | null
  expiresAt: string | null
}

export interface MeResponse {
  user: AuthUser
  tokens: ApiTokenInfo[]
}

export interface ChangePasswordResponse {
  revokedTokens: number
}

/** POST /api/auth/tokens — the raw token is shown exactly once. */
export interface MintedToken {
  token: string
  tokenId: string
}

// ── admin users (camelCase) ──

export interface AdminUserRow {
  id: string
  username: string
  displayName: string
  role: string
  isActive: boolean
  tokenCount: number
  lastSeenAt: string | null
  // Sync freshness (metadata only): when the last workout row arrived, and the
  // most recent day that has health metrics. Null for admins — they have no data.
  lastWorkoutSyncAt: string | null
  lastHealthDate: string | null
}

/** GET /api/admin/users/{id}/tokens — same shape as the self-service ApiTokenInfo. */
export type AdminTokenRow = ApiTokenInfo

export interface AuthEventRow {
  id: string
  event: string
  username: string | null
  actorUsername: string | null
  ip: string | null
  detail: Record<string, unknown> | null
  createdAt: string
}

export interface SystemStatus {
  appVersion: string
  backup: { file: string; sizeBytes: number; completedAt: string } | null
  backupCount: number
  dbSizeBytes: number
  migrationHead: string | null
  counts: Record<string, number>
}

// ── workouts (snake_case) ──

export interface WorkoutListItem {
  id: string
  activity_type: string
  start_date: string
  end_date: string
  duration: number | null
  total_distance: number | null
  total_energy_burned: number | null
  source: string | null
  plan_workout_id: string | null
  effort_score: number | null
  estimated_effort_score: number | null
  created_at: string
  updated_at: string
}

export interface WorkoutRead extends WorkoutListItem {
  data: Record<string, unknown>
}

/** GET /api/workouts/{id}/context — server-held plan linkage for a workout.
 *  All three embeds nullable; entirely null for an unplanned run. Note the
 *  embedded feedback is snake_case, unlike the camelCase feedback resource. */
export interface WorkoutContext {
  workout_id: string
  plan_workout_id: string | null
  queue_item: WorkoutContextQueueItem | null
  plan: WorkoutContextPlan | null
  feedback: WorkoutContextFeedback | null
}

export interface WorkoutContextQueueItem {
  id: string
  title: string
  description: string | null
  activity_type: string
  status: string // live status: pending | fetched | synced | completed | skipped
  scheduled_date: string | null
  plan_id: string | null
  workout_data: WorkoutComposition | null
  completed_at: string | null
}

export interface WorkoutContextPlan {
  id: string
  name: string
  activity_type: string
  status: string
  start_date: string
  end_date: string | null
}

export interface WorkoutContextFeedback {
  reason: string
  reason_note: string | null
  action: string // move | adjust | skip
  new_date: string | null
  scheduled_date: string
  dismissed: boolean
  created_at: string
}

export interface WorkoutSummaryRow {
  period: string
  activity_type: string | null
  count: number
  total_distance: number | null
  total_duration: number | null
  avg_distance: number | null
  avg_duration: number | null
  total_energy_burned: number | null
}

/** Element of data.splits (HealthKit composition; fields may be absent). */
export interface WorkoutSplit {
  index?: number
  pace?: number // seconds per km
  distance?: number // meters
  duration?: number // seconds
  startDate?: string
  endDate?: string
  averageHeartRate?: number
  averageCadence?: number
  elevationGain?: number
  elevationLoss?: number
}

export interface TimedSample {
  value: number
  timestamp: string
}

export interface RoutePoint {
  latitude: number
  longitude: number
  altitude?: number
  speed?: number
  timestamp?: string
}

// ── queue (snake_case) ──

export interface QueueItem {
  id: string
  activity_type: string
  title: string
  description: string | null
  workout_data: WorkoutComposition | null
  plan_id: string | null
  status: string // pending | fetched | synced | completed
  scheduled_date: string | null
  created_at: string
  fetched_at: string | null
  completed_at: string | null
}

export interface CompositionGoal {
  type?: string // time | distance | open
  unit?: string
  value?: number
}

export interface CompositionStep {
  goal?: CompositionGoal
  purpose?: string // warmup | work | rest | cooldown
}

export interface WorkoutComposition {
  displayName?: string
  activityType?: string
  scheduledDate?: string
  location?: string
  warmup?: CompositionStep
  cooldown?: CompositionStep
  blocks?: { steps?: CompositionStep[]; iterations?: number }[]
  [key: string]: unknown
}

// ── feedback (camelCase) ──

export interface FeedbackItem {
  id: string
  workoutId: string
  workoutName: string
  scheduledDate: string
  detectedAt: string
  acknowledgedAt: string | null
  reason: string // busy | tired | weather | soreness | motivation | other
  reasonNote: string | null
  action: string // move | adjust | skip
  newDate: string | null
  dismissed: boolean
}

// ── health metrics (snake_case) ──

export interface SleepStages {
  awake?: number
  rem?: number
  core?: number
  deep?: number
}

export interface HealthMetricsDay {
  date: string
  sleep_duration: number | null // seconds
  sleep_stages: SleepStages | null // seconds per stage
  resting_heart_rate: number | null
  hrv_sdnn: number | null
  weight: number | null
  vo2_max: number | null
  steps: number | null
  active_energy_burned: number | null
  body_fat_percentage: number | null
  lean_body_mass: number | null
  respiratory_rate: number | null
  spo2: number | null
  created_at: string
  updated_at: string
}

// ── nutrition (snake_case, like health metrics) ──

export interface NutritionDay {
  date: string
  energy_kcal: number | null
  carbs_g: number | null
  protein_g: number | null
  fat_g: number | null
  saturated_fat_g: number | null
  fiber_g: number | null
  sugar_g: number | null
  sodium_mg: number | null
  potassium_mg: number | null
  cholesterol_mg: number | null
  water_ml: number | null
  caffeine_mg: number | null
  micros: Record<string, number> | null
  entry_count: number | null
  sources: string[] | null
  /** Day was still in progress when synced — totals are incomplete. */
  partial: boolean
  created_at: string
  updated_at: string
}

export interface NutritionPeriod {
  period_start: string
  period_end: string
  days_logged: number
  days_partial: number
  days_in_period: number
  /** Per-logged-day averages, keyed by the same names as NutritionDay. */
  nutrition: Record<string, number | null>
  protein_g_per_kg: number | null
  body: {
    weight_avg: number | null
    weight_start: number | null
    weight_end: number | null
    weight_change: number | null
  }
  training: {
    workouts: number
    distance_km: number | null
    duration_min: number | null
    energy_kcal: number | null
  }
}

export interface NutritionSummary {
  period: string
  start_date: string
  end_date: string
  periods: NutritionPeriod[]
}

// ── plans (snake_case; metadata JSONB is LLM-authored) ──

export interface PlanPhase {
  name?: string
  weeks?: string | number
  focus?: string
  [key: string]: unknown
}

/**
 * Goals are usually objects like {type: "weekly_volume", target: 20, unit:
 * "km", by_week: 4} or {type, detail|description}, but the schema is
 * LLM-authored and open — render via PlanDetail's formatter, never String().
 */
export type PlanGoal = string | Record<string, unknown>

export interface PlanMetadata {
  goals?: PlanGoal[]
  // LLM-authored: historically an array of goal-like entries; the playbook now
  // also teaches a dict form ({max_weekly_km: 30, ...}) that the validator reads.
  guardrails?: PlanGoal[] | Record<string, unknown>
  phases?: PlanPhase[]
  athlete_context?: string
  background?: string
  schedule?: PlanSchedule
  [key: string]: unknown
}

/** Queue-derived run counts; a schedule-only strength plan is all zeros. */
export interface PlanProgress {
  runs_total: number
  runs_completed: number
  runs_skipped: number
  runs_remaining: number
}

export interface Plan {
  id: string
  name: string
  activity_type: string
  status: string // active | completed | archived | ... (free string)
  start_date: string
  end_date: string | null
  description: string | null
  metadata: PlanMetadata
  created_at: string
  updated_at: string
  progress: PlanProgress | null
  /** Active plan that looks done — offer the celebrate-and-complete flow. */
  finishable: boolean
}

export interface PlanCompleteResponse {
  plan: Plan
  /** Another already-active same-activity plan; null → nudge "ask your coach". */
  next_plan: Plan | null
}

// plan schedule (camelCase)
export interface PlanScheduleDay {
  title: string
  routineId?: string | null
}

export interface PlanSchedule {
  startDate: string
  weeks: number
  days: Partial<Record<'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun', PlanScheduleDay>>
  time?: string | null
  timezone?: string | null
}

export interface ScheduledSession {
  date: string
  weekday: string
  title: string
  routineId: string | null
  conflict: boolean
  conflictsWith: string[]
}

export interface PlanScheduleResponse {
  planId: string
  schedule: PlanSchedule | null
  sessions: ScheduledSession[]
  warnings: string[]
}

// ── plan validation (snake_case — unlike the schedule endpoint above) ──

export interface ValidationWarning {
  code: string
  severity: 'critical' | 'warn' | 'info'
  message: string
  week: string | null // ISO date of the week's Monday
  data: Record<string, unknown>
  estimated: boolean
}

export interface WeekSummary {
  week_start: string
  planned_km: number
  actual_km: number
  total_km: number
  run_days: number
  hard_days: number
  longest_km: number
  baseline_km: number | null
  ratio: number | null
  estimated: boolean
}

export interface PlanValidateResponse {
  plan_id: string
  warnings: ValidationWarning[]
  weeks: WeekSummary[]
}

// ── plan notes (mixed casing — matches wire exactly) ──

export type NoteKind =
  | 'decision'
  | 'preference'
  | 'constraint'
  | 'life_context'
  | 'observation'
  | 'blocker'
  | 'feedback'

export interface PlanNote {
  id: string
  planId: string | null
  kind: NoteKind
  summary: string
  body: string | null
  importance: number // 1-3
  conversationId: string | null
  expiresAt: string | null
  created_at: string
  updated_at: string
}

export interface PlanNoteContext {
  plan: Plan | null
  notes: PlanNote[]
  last_note_age_days: number | null
  continuity_hint: string
}

// ── calendar (camelCase, hand-built server side) ──

export interface CalendarEntry {
  date: string
  kind: 'run' | 'strength'
  title: string
  activityType: string
  status: string | null
  planId: string | null
  planName: string | null
  routineId: string | null
  completed: boolean
  conflict: boolean
}

export interface CalendarResponse {
  from: string
  to: string
  entries: CalendarEntry[]
}

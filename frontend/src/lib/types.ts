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

export interface ApiTokenInfo {
  id: string
  name: string
  createdAt: string
  lastUsedAt: string | null
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
  guardrails?: PlanGoal[]
  phases?: PlanPhase[]
  athlete_context?: string
  background?: string
  schedule?: PlanSchedule
  [key: string]: unknown
}

export interface Plan {
  id: string
  name: string
  activity_type: string
  status: string // active | archived | ... (free string)
  start_date: string
  end_date: string | null
  description: string | null
  metadata: PlanMetadata
  created_at: string
  updated_at: string
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

// ── plan notes (mixed casing — matches wire exactly) ──

export type NoteKind =
  | 'decision'
  | 'preference'
  | 'constraint'
  | 'life_context'
  | 'observation'
  | 'blocker'

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

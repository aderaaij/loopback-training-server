import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { toDateKey, addDays } from './format'
import type {
  AdminUserRow,
  CalendarResponse,
  ChangePasswordResponse,
  FeedbackItem,
  HealthMetricsDay,
  MeResponse,
  MintedToken,
  Plan,
  PlanNote,
  PlanNoteContext,
  PlanScheduleResponse,
  QueueItem,
  TimedSample,
  WorkoutListItem,
  WorkoutRead,
  WorkoutSplit,
  WorkoutSummaryRow,
} from './types'

// ── auth ──

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<MeResponse>('/api/auth/me'),
  })
}

export function useRevokeToken() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (tokenId: string) => api.delete(`/api/auth/tokens/${tokenId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { currentPassword: string; newPassword: string }) =>
      api.post<ChangePasswordResponse>('/api/auth/password', body),
  })
}

export function useMintToken() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; expiresAt?: string }) => api.post<MintedToken>('/api/auth/tokens', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  })
}

// ── admin users ──

export function useAdminUsers(enabled: boolean) {
  return useQuery({
    queryKey: ['admin-users'],
    queryFn: () => api.get<AdminUserRow[]>('/api/admin/users'),
    enabled,
  })
}

export function useCreateUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { username: string; password: string; displayName?: string; role?: string }) =>
      api.post<AdminUserRow>('/api/admin/users', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })
}

export function useResetUserPassword() {
  return useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      api.post(`/api/admin/users/${id}/password`, { password }),
  })
}

export function useSetUserActive() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      api.patch<AdminUserRow>(`/api/admin/users/${id}`, { isActive }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })
}

// ── calendar ──

export function useCalendar(from: string, to: string) {
  return useQuery({
    queryKey: ['calendar', from, to],
    queryFn: () => api.get<CalendarResponse>('/api/schedule/calendar', { from, to }),
  })
}

export function useUpcoming() {
  const from = toDateKey(new Date())
  const to = toDateKey(addDays(new Date(), 28))
  return useCalendar(from, to)
}

// ── workouts ──

export interface WorkoutFilters {
  activity_type?: string
  start_after?: string
  start_before?: string
  limit?: number
  offset?: number
}

export function useWorkouts(filters: WorkoutFilters) {
  return useQuery({
    queryKey: ['workouts', filters],
    queryFn: () => api.get<WorkoutListItem[]>('/api/workouts', { ...filters }),
  })
}

const WORKOUT_PAGE = 50

/** Offset-paginated "load more" — the API returns bare arrays with no total. */
export function useInfiniteWorkouts(activityType?: string) {
  return useInfiniteQuery({
    queryKey: ['workouts-infinite', activityType ?? 'all'],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.get<WorkoutListItem[]>('/api/workouts', {
        activity_type: activityType,
        limit: WORKOUT_PAGE,
        offset: pageParam,
      }),
    getNextPageParam: (lastPage, pages) =>
      lastPage.length < WORKOUT_PAGE ? undefined : pages.length * WORKOUT_PAGE,
  })
}

export function useWorkout(id: string | undefined) {
  return useQuery({
    queryKey: ['workout', id],
    queryFn: () => api.get<WorkoutRead>(`/api/workouts/${id}`),
    enabled: !!id,
  })
}

export function useWorkoutSplits(id: string | undefined) {
  return useQuery({
    queryKey: ['workout', id, 'splits'],
    queryFn: () => api.get<WorkoutSplit[]>(`/api/workouts/${id}/splits`),
    enabled: !!id,
  })
}

export function useWorkoutHeartRate(id: string | undefined) {
  return useQuery({
    queryKey: ['workout', id, 'heartrate'],
    queryFn: () => api.get<TimedSample[]>(`/api/workouts/${id}/heartrate`),
    enabled: !!id,
  })
}

export function useWorkoutSummary(period: 'week' | 'month' | 'year') {
  return useQuery({
    queryKey: ['workout-summary', period],
    queryFn: () => api.get<WorkoutSummaryRow[]>('/api/workouts/summary', { period }),
  })
}

export function useDeleteWorkout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/workouts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workouts'] }),
  })
}

// ── plans ──

export function usePlans(status?: string) {
  return useQuery({
    queryKey: ['plans', status ?? 'all'],
    queryFn: () => api.get<Plan[]>('/api/plans', status ? { status } : undefined),
  })
}

export function usePlan(id: string | undefined) {
  return useQuery({
    queryKey: ['plan', id],
    queryFn: () => api.get<Plan>(`/api/plans/${id}`),
    enabled: !!id,
  })
}

export function usePlanSchedule(id: string | undefined) {
  return useQuery({
    queryKey: ['plan', id, 'schedule'],
    queryFn: () => api.get<PlanScheduleResponse>(`/api/plans/${id}/schedule`),
    enabled: !!id,
  })
}

export function usePlanWorkouts(id: string | undefined) {
  return useQuery({
    queryKey: ['plan', id, 'workouts'],
    queryFn: () => api.get<QueueItem[]>(`/api/plans/${id}/workouts`),
    enabled: !!id,
  })
}

// ── plan notes ──

export function usePlanNotes(opts: { kind?: string; includeExpired?: boolean }) {
  return useQuery({
    queryKey: ['plan-notes', opts],
    queryFn: () =>
      api.get<PlanNote[]>('/api/plan-notes', {
        kind: opts.kind,
        include_expired: opts.includeExpired ? 'true' : undefined,
        limit: 200,
      }),
  })
}

export function useNoteContext() {
  return useQuery({
    queryKey: ['plan-notes-context'],
    queryFn: () => api.get<PlanNoteContext>('/api/plan-notes/context'),
  })
}

export interface NotePatch {
  kind?: string
  summary?: string
  body?: string | null
  importance?: number
  expiresAt?: string | null
}

export function useUpdateNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: NotePatch }) =>
      api.patch<PlanNote>(`/api/plan-notes/${id}`, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['plan-notes'] })
      qc.invalidateQueries({ queryKey: ['plan-notes-context'] })
    },
  })
}

export function useDeleteNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/plan-notes/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['plan-notes'] })
      qc.invalidateQueries({ queryKey: ['plan-notes-context'] })
    },
  })
}

// ── health metrics ──

export function useHealthMetrics(startDate: string, endDate?: string) {
  return useQuery({
    queryKey: ['health-metrics', startDate, endDate],
    queryFn: () =>
      api.get<HealthMetricsDay[]>('/api/health/metrics', {
        start_date: startDate,
        end_date: endDate,
      }),
  })
}

// ── queue ──

export function useQueue(status?: string, limit = 100) {
  return useQuery({
    queryKey: ['queue', status ?? 'all', limit],
    queryFn: () => api.get<QueueItem[]>('/api/queue', { status, limit }),
  })
}

export function useDeleteQueueItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/queue/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['queue'] })
      qc.invalidateQueries({ queryKey: ['calendar'] })
    },
  })
}

// ── feedback ──

export function useFeedback() {
  return useQuery({
    queryKey: ['feedback'],
    queryFn: () => api.get<FeedbackItem[]>('/api/workouts/feedback', { limit: 50 }),
  })
}

/**
 * There is no PATCH for feedback; the POST is an idempotent per-workout
 * upsert, so acknowledging = re-posting the row with acknowledgedAt set.
 */
export function useAcknowledgeFeedback() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (item: FeedbackItem) =>
      api.post('/api/workouts/feedback', {
        id: item.id,
        workoutId: item.workoutId,
        workoutName: item.workoutName,
        scheduledDate: item.scheduledDate,
        detectedAt: item.detectedAt,
        acknowledgedAt: new Date().toISOString(),
        reason: item.reason,
        reasonNote: item.reasonNote,
        action: item.action,
        newDate: item.newDate,
        dismissed: item.dismissed,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['feedback'] }),
  })
}

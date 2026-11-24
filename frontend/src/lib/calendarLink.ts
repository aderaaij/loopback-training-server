import type { CalendarEntry } from './types'

/**
 * Where clicking a calendar entry goes, or null when there is nowhere to go.
 *
 * A recorded workout always wins. Without one, a run is still a queue item,
 * and the queue screen scrolls to it (it has no screen of its own); a
 * strength session falls back to its plan.
 */
export function entryLink(entry: Pick<CalendarEntry, 'kind' | 'queueId' | 'workoutId' | 'planId'>): string | null {
  if (entry.workoutId) return `/workouts/${entry.workoutId}`
  if (entry.kind === 'run') return entry.queueId ? `/queue#${entry.queueId}` : null
  return entry.planId ? `/plans/${entry.planId}` : null
}

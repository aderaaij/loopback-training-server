import type { CalendarEntry } from './types'

export type EntryStatus = 'completed' | 'skipped' | 'missed' | 'upcoming'

/**
 * Where a calendar entry stands, for its status mark.
 *
 * `today` is a local YYYY-MM-DD key from `todayKey()`, the same one the
 * calendar's "today" highlight uses, so date keys compare as strings.
 * Missed means strictly before today: a session scheduled today is never
 * missed. Strength entries carry no queue status, so they can only be
 * completed, missed or upcoming. `completed` already reflects a run's
 * queue status (the endpoint sets it from `status === "completed"`).
 */
export function entryStatus(entry: Pick<CalendarEntry, 'date' | 'status' | 'completed'>, today: string): EntryStatus {
  if (entry.completed) return 'completed'
  if (entry.status === 'skipped') return 'skipped'
  if (entry.date < today) return 'missed'
  return 'upcoming'
}

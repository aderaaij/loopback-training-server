import { createServerPreference } from './serverPreference'

/**
 * First day of the week on the calendar (Monday / Sunday). Display only.
 *
 * Like units, the choice belongs to the user and lives on the server
 * (`/api/me/week-start`); see serverPreference.ts for how it is cached and
 * synced. Monday is the default, and what the server's null means, so nothing
 * changes for anyone who never picks.
 */
export const WEEK_STARTS = ['monday', 'sunday'] as const
export type WeekStart = (typeof WEEK_STARTS)[number]

const weekStart = createServerPreference<WeekStart>({
  key: 'loopback.weekStart',
  path: '/api/me/week-start',
  field: 'weekStart',
  values: WEEK_STARTS,
  defaultValue: 'monday',
})

export const setWeekStart = weekStart.set
export const syncWeekStart = weekStart.sync
export const clearWeekStart = weekStart.clear
export const useWeekStart = weekStart.useValue

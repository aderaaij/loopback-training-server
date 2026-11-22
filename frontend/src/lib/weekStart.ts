import { useSyncExternalStore } from 'react'
import { api } from './api'

/**
 * First day of the week on the calendar (Monday / Sunday). Display only.
 *
 * Same shape as the units preference (lib/units.ts): the choice belongs to the
 * user and lives on the server (`/api/me/week-start`), and localStorage under a
 * `loopback.*` key is only a cache so the first paint already has the right
 * week. Monday is the default, and what the server's null means, so nothing
 * changes for anyone who never picks.
 */
export type WeekStart = 'monday' | 'sunday'

const WEEK_START_KEY = 'loopback.weekStart'

// Only set when localStorage is unavailable, so the toggle still works for the session.
let fallback: WeekStart | null = null

function isWeekStart(value: unknown): value is WeekStart {
  return value === 'monday' || value === 'sunday'
}

/** What this browser has explicitly stored, or null if nothing. */
function stored(): WeekStart | null {
  if (fallback) return fallback
  try {
    const value = localStorage.getItem(WEEK_START_KEY)
    if (isWeekStart(value)) return value
  } catch {
    // storage blocked (private mode, etc.) — treat as nothing stored
  }
  return null
}

function read(): WeekStart {
  return stored() ?? 'monday'
}

let current: WeekStart = read()
const listeners = new Set<() => void>()

function notify() {
  listeners.forEach((fn) => fn())
}

// Another tab changing the preference fires `storage` here.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== WEEK_START_KEY && e.key !== null) return
    current = read()
    notify()
  })
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

function store(weekStart: WeekStart) {
  try {
    localStorage.setItem(WEEK_START_KEY, weekStart)
    fallback = null
  } catch {
    fallback = weekStart
  }
  current = read()
  notify()
}

interface WeekStartResponse {
  weekStart: WeekStart | null
}

/** The user's choice: applied here at once, then saved to their account. */
export function setWeekStart(weekStart: WeekStart) {
  store(weekStart)
  // As with units, a failed save keeps the choice in this browser and
  // syncWeekStart offers it to the server again on next load.
  api.put<WeekStartResponse>('/api/me/week-start', { weekStart }).catch(() => {})
}

/**
 * Line this browser up with the signed-in user's account. Call once a session
 * exists (page load while signed in, or right after login). The server wins
 * once it holds a choice; until then a choice made in this browser is handed
 * over.
 */
export async function syncWeekStart(): Promise<void> {
  try {
    const remote = await api.get<WeekStartResponse>('/api/me/week-start')
    if (isWeekStart(remote.weekStart)) {
      if (remote.weekStart !== current || stored() === null) store(remote.weekStart)
      return
    }
    const local = stored()
    if (local) await api.put<WeekStartResponse>('/api/me/week-start', { weekStart: local })
  } catch {
    // Offline or an older server: keep what this browser has.
  }
}

/** Forget the cached choice on sign-out: it belongs to the account, not the browser. */
export function clearWeekStart() {
  fallback = null
  try {
    localStorage.removeItem(WEEK_START_KEY)
  } catch {
    // nothing stored to forget
  }
  current = read()
  notify()
}

/** Current preference; components re-render when it changes. */
export function useWeekStart(): WeekStart {
  return useSyncExternalStore(subscribe, () => current)
}

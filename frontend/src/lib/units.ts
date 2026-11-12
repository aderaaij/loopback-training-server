import { useSyncExternalStore } from 'react'
import { api } from './api'

/**
 * Display-unit preference (metric / imperial). Display only: the API always
 * speaks metric and nothing is converted on the wire.
 *
 * The preference belongs to the user and lives on the server
 * (`/api/me/units`), so the phone and the coach follow the same choice.
 * localStorage under a `loopback.*` key is only a cache, so the first paint
 * is already in the right units. Metric is the default: imperial is opt-in,
 * never guessed from the browser locale.
 */
export type Units = 'metric' | 'imperial'

const UNITS_KEY = 'loopback.units'

// Only set when localStorage is unavailable, so the toggle still works for the session.
let fallback: Units | null = null

/** What this browser has explicitly stored, or null if nothing. */
function stored(): Units | null {
  if (fallback) return fallback
  try {
    const value = localStorage.getItem(UNITS_KEY)
    if (value === 'metric' || value === 'imperial') return value
  } catch {
    // storage blocked (private mode, etc.) — treat as nothing stored
  }
  return null
}

function read(): Units {
  return stored() ?? 'metric'
}

let current: Units = read()
const listeners = new Set<() => void>()

function notify() {
  listeners.forEach((fn) => fn())
}

// Another tab changing the preference fires `storage` here.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== UNITS_KEY && e.key !== null) return
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

function store(units: Units) {
  try {
    localStorage.setItem(UNITS_KEY, units)
    fallback = null
  } catch {
    fallback = units
  }
  current = read()
  notify()
}

interface UnitsResponse {
  units: Units | null
}

/** The user's choice: applied here at once, then saved to their account. */
export function setUnits(units: Units) {
  store(units)
  // A failed save is not worth an error in the UI: the choice still holds in
  // this browser, and syncUnits offers it to the server again on next load.
  api.put<UnitsResponse>('/api/me/units', { units }).catch(() => {})
}

/**
 * Line this browser up with the signed-in user's account. Call once a session
 * exists (page load while signed in, or right after login).
 *
 * The server wins once it holds a choice. Until then, a choice made in this
 * browser before the preference moved server-side is handed over, once, so
 * nobody has to pick again.
 */
export async function syncUnits(): Promise<void> {
  try {
    const remote = await api.get<UnitsResponse>('/api/me/units')
    if (remote.units === 'metric' || remote.units === 'imperial') {
      if (remote.units !== current || stored() === null) store(remote.units)
      return
    }
    const local = stored()
    if (local) await api.put<UnitsResponse>('/api/me/units', { units: local })
  } catch {
    // Offline or an older server: keep what this browser has.
  }
}

/**
 * Forget the cached choice on sign-out. It belongs to the account, not the
 * browser: left behind, it would be handed to the next person to sign in here
 * who has not chosen yet.
 */
export function clearUnits() {
  fallback = null
  try {
    localStorage.removeItem(UNITS_KEY)
  } catch {
    // nothing stored to forget
  }
  current = read()
  notify()
}

/** Current preference; components re-render when it changes. */
export function useUnits(): Units {
  return useSyncExternalStore(subscribe, () => current)
}

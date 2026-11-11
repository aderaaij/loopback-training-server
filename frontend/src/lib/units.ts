import { useSyncExternalStore } from 'react'

/**
 * Display-unit preference (metric / imperial). Display only: the API always
 * speaks metric and nothing is converted on the wire.
 *
 * Stored in localStorage under a `loopback.*` key like the auth bits in
 * api.ts. Metric is the default: imperial is opt-in, never guessed from the
 * browser locale.
 */
export type Units = 'metric' | 'imperial'

const UNITS_KEY = 'loopback.units'

// Only set when localStorage is unavailable, so the toggle still works for the session.
let fallback: Units | null = null

function read(): Units {
  if (fallback) return fallback
  try {
    const stored = localStorage.getItem(UNITS_KEY)
    if (stored === 'metric' || stored === 'imperial') return stored
  } catch {
    // storage blocked (private mode, etc.) — fall through to the default
  }
  return 'metric'
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

export function setUnits(units: Units) {
  try {
    localStorage.setItem(UNITS_KEY, units)
    fallback = null
  } catch {
    fallback = units
  }
  current = read()
  notify()
}

/** Current preference; components re-render when it changes. */
export function useUnits(): Units {
  return useSyncExternalStore(subscribe, () => current)
}

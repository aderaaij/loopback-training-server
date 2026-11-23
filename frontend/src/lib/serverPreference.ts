import { useSyncExternalStore } from 'react'
import { api } from './api'

/**
 * A display preference that belongs to the user's account, with this browser
 * keeping a copy. Units and the calendar's first weekday are built on it.
 *
 * The server is the source of truth, so the phone, the coach and every browser
 * follow the same choice. localStorage under a `loopback.*` key is only a
 * cache, so the first paint is already right. Display only: no data changes
 * with it, and the default is never guessed from the browser locale.
 *
 * Wire contract: GET `path` returns `{ [field]: value | null }` (null = never
 * chosen) and PUT `path` takes `{ [field]: value }`. `values` is the closed
 * vocabulary and has to match what the server accepts.
 */
export interface ServerPreferenceConfig<T extends string> {
  /** localStorage key for the cached choice. */
  key: string
  /** API path of the preference. */
  path: string
  /** JSON field the value travels in. */
  field: string
  /** Every allowed value. */
  values: readonly T[]
  /** What nobody-has-chosen-yet means. */
  defaultValue: T
}

export function createServerPreference<T extends string>(config: ServerPreferenceConfig<T>) {
  const { key, path, field, values, defaultValue } = config

  const isValue = (value: unknown): value is T => values.includes(value as T)

  // Only set when localStorage is unavailable, so the toggle still works for the session.
  let fallback: T | null = null

  /** What this browser has explicitly stored, or null if nothing. */
  function stored(): T | null {
    if (fallback) return fallback
    try {
      const value = localStorage.getItem(key)
      if (isValue(value)) return value
    } catch {
      // storage blocked (private mode, etc.) — treat as nothing stored
    }
    return null
  }

  function read(): T {
    return stored() ?? defaultValue
  }

  let current: T = read()
  const listeners = new Set<() => void>()

  function notify() {
    listeners.forEach((fn) => fn())
  }

  // Another tab changing the preference fires `storage` here.
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (e) => {
      if (e.key !== key && e.key !== null) return
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

  function store(value: T) {
    try {
      localStorage.setItem(key, value)
      fallback = null
    } catch {
      fallback = value
    }
    current = read()
    notify()
  }

  /** The user's choice: applied here at once, then saved to their account. */
  function set(value: T) {
    store(value)
    // A failed save is not worth an error in the UI: the choice still holds in
    // this browser, and sync offers it to the server again on next load.
    api.put(path, { [field]: value }).catch(() => {})
  }

  /**
   * Line this browser up with the signed-in user's account. Call once a session
   * exists (page load while signed in, or right after login).
   *
   * The server wins once it holds a choice. Until then, a choice made in this
   * browser before the preference moved server-side is handed over, once, so
   * nobody has to pick again.
   */
  async function sync(): Promise<void> {
    try {
      const remote = (await api.get<Record<string, unknown>>(path))[field]
      if (isValue(remote)) {
        if (remote !== current || stored() === null) store(remote)
        return
      }
      const local = stored()
      if (local) await api.put(path, { [field]: local })
    } catch {
      // Offline or an older server: keep what this browser has.
    }
  }

  /**
   * Forget the cached choice on sign-out. It belongs to the account, not the
   * browser: left behind, it would be handed to the next person to sign in here
   * who has not chosen yet.
   */
  function clear() {
    fallback = null
    try {
      localStorage.removeItem(key)
    } catch {
      // nothing stored to forget
    }
    current = read()
    notify()
  }

  /** Current value; components re-render when it changes. */
  function useValue(): T {
    return useSyncExternalStore(subscribe, () => current)
  }

  return { set, sync, clear, useValue }
}

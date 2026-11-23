import { createServerPreference } from './serverPreference'

/**
 * Display-unit preference (metric / imperial). Display only: the API always
 * speaks metric and nothing is converted on the wire.
 *
 * The preference belongs to the user and lives on the server
 * (`/api/me/units`), so the phone and the coach follow the same choice; see
 * serverPreference.ts for how it is cached and synced. Metric is the default:
 * imperial is opt-in, never guessed from the browser locale.
 */
export const UNITS = ['metric', 'imperial'] as const
export type Units = (typeof UNITS)[number]

const units = createServerPreference<Units>({
  key: 'loopback.units',
  path: '/api/me/units',
  field: 'units',
  values: UNITS,
  defaultValue: 'metric',
})

export const setUnits = units.set
export const syncUnits = units.sync
export const clearUnits = units.clear
export const useUnits = units.useValue

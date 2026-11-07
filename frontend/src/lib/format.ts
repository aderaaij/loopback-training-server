import type { Units } from './units'

/**
 * Formatting helpers. Backend units: duration seconds, distance meters, pace
 * seconds-per-km, weight kg, energy kcal. The API stays metric; the helpers
 * below that take `units` convert for display only.
 */

const M_PER_MI = 1609.344
const LB_PER_KG = 2.2046226218

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
const DOWS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${m}:${String(sec).padStart(2, '0')}`
}

export function fmtDurationLong(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm === 0 ? `${h} h` : `${h}h ${String(rm).padStart(2, '0')}m`
}

/** Sleep style: 7:24 (hours:minutes) from seconds. */
export function fmtHoursMinutes(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const m = Math.round(seconds / 60)
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`
}

export const distanceUnit = (units: Units) => (units === 'imperial' ? 'mi' : 'km')
export const paceUnit = (units: Units) => (units === 'imperial' ? '/mi' : '/km')
export const weightUnit = (units: Units) => (units === 'imperial' ? 'lb' : 'kg')

/** Meters → km or mi, as a number (no unit, no rounding). */
export function distanceValue(meters: number, units: Units): number {
  return units === 'imperial' ? meters / M_PER_MI : meters / 1000
}

/** Kilometers (plan targets, weekly totals) → km or mi, rounded to one decimal. */
export function kmDisplay(km: number, units: Units): number {
  return Number(distanceValue(km * 1000, units).toFixed(1))
}

/** Short distance label for tight spots: "mi" or "k" (after the number). */
export const distanceShortUnit = (units: Units) => (units === 'imperial' ? ' mi' : 'k')

export function fmtDistance(meters: number | null | undefined, units: Units, digits = 2): string {
  if (meters == null || !Number.isFinite(meters)) return '—'
  return `${distanceValue(meters, units).toFixed(digits)} ${distanceUnit(units)}`
}

/** km or mi → meters; null for anything else (meters included, which callers keep as is). */
export function toMeters(value: number, unit: string | undefined): number | null {
  switch (unit?.trim().toLowerCase()) {
    case 'kilometers':
    case 'kilometres':
    case 'km':
      return value * 1000
    case 'miles':
    case 'mile':
    case 'mi':
      return value * M_PER_MI
    default:
      return null
  }
}

/** A distance goal's value in meters; goals are authored in meters, km or miles. */
export function goalMeters(value: number, unit: string | undefined): number {
  return toMeters(value, unit) ?? value
}

/**
 * Converts a free-form `{target, unit}` from a plan goal when the unit is a
 * known distance unit; anything else comes back unchanged.
 */
export function convertGoalTarget(
  target: number,
  unit: string,
  units: Units,
): { target: number; unit: string } {
  const meters = toMeters(target, unit)
  if (meters == null) return { target, unit }
  return { target: Number(distanceValue(meters, units).toFixed(1)), unit: distanceUnit(units) }
}

/** Kilograms → kg or lb, as a number. */
export function weightValue(kg: number, units: Units): number {
  return units === 'imperial' ? kg * LB_PER_KG : kg
}

export function fmtWeight(kg: number | null | undefined, units: Units, digits = 1): string {
  if (kg == null || !Number.isFinite(kg)) return '—'
  return `${weightValue(kg, units).toFixed(digits)} ${weightUnit(units)}`
}

/** Pace from seconds-per-km → "6:29" per km, or per mile when imperial. */
export function fmtPace(secPerKm: number | null | undefined, units: Units): string {
  if (secPerKm == null || !Number.isFinite(secPerKm) || secPerKm <= 0) return '—'
  const perUnit = units === 'imperial' ? secPerKm * (M_PER_MI / 1000) : secPerKm
  const m = Math.floor(perUnit / 60)
  const s = Math.round(perUnit % 60)
  return s === 60 ? `${m + 1}:00` : `${m}:${String(s).padStart(2, '0')}`
}

/** Pace with its unit: "6:29 /km" or "10:26 /mi". */
export function fmtPaceWithUnit(secPerKm: number | null | undefined, units: Units): string {
  return `${fmtPace(secPerKm, units)} ${paceUnit(units)}`
}

/** Seconds per km — always metric, convert with `fmtPace`. */
export function paceOf(durationSec: number | null | undefined, meters: number | null | undefined): number | null {
  if (!durationSec || !meters || meters < 100) return null
  return durationSec / (meters / 1000)
}

export function fmtKcal(kcal: number | null | undefined): string {
  if (kcal == null || !Number.isFinite(kcal)) return '—'
  return `${Math.round(kcal).toLocaleString('en-US')} kcal`
}

/** "30 JUN" style. */
export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`
}

/** "30 JUN 2026" style. */
export function fmtDayYear(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`
}

/** "THU 2 JUL · 07:00" style. */
export function fmtDowDayTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const dow = DOWS[(d.getDay() + 6) % 7]
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const time = d.getHours() === 0 && d.getMinutes() === 0 ? '' : ` · ${hm}`
  return `${dow} ${d.getDate()} ${MONTHS[d.getMonth()]}${time}`
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function relTime(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'never'
  const mins = Math.floor((Date.now() - d.getTime()) / 60000)
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return fmtDay(iso)
}

/** Compact label for a token's last-seen client User-Agent, null when unknown. */
export function clientLabel(ua: string | null | undefined): string | null {
  if (!ua) return null
  const app = ua.match(/^Loopback-iOS\/(\S+)/i)
  if (app) return `Loopback iOS ${app[1]}`
  if (ua.startsWith('Mozilla/')) return 'browser'
  // "python-httpx/0.28.1 (…)" → "python-httpx": product name without version noise.
  return ua.split(' ')[0].split('/')[0].slice(0, 24)
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n
  let i = -1
  do {
    v /= 1024
    i++
  } while (v >= 1024 && i < units.length - 1)
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

/** Local YYYY-MM-DD (calendar math must not go through UTC). */
export function toDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function todayKey(): string {
  return toDateKey(new Date())
}

export function addDays(d: Date, days: number): Date {
  const out = new Date(d)
  out.setDate(out.getDate() + days)
  return out
}

/** Monday of the week containing d. */
export function startOfWeek(d: Date): Date {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  out.setDate(out.getDate() - ((out.getDay() + 6) % 7))
  return out
}

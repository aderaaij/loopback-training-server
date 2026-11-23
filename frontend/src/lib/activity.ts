import {
  Barbell,
  Bicycle,
  Boat,
  Infinity as InfinityIcon,
  PersonSimpleRun,
  PersonSimpleSki,
  PersonSimpleTaiChi,
  PersonSimpleWalk,
  Pulse,
} from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'

export interface ActivityMeta {
  icon: Icon
  color: string
  label: string
}

/** Real activity_type values in the DB, mapped to the design's iconography. */
const ACTIVITIES: Record<string, ActivityMeta> = {
  running: { icon: PersonSimpleRun, color: 'var(--accent)', label: 'Running' },
  traditionalStrength: { icon: Barbell, color: 'var(--purple)', label: 'Strength' },
  flexibility: { icon: PersonSimpleTaiChi, color: 'var(--teal)', label: 'Flexibility' },
  walking: { icon: PersonSimpleWalk, color: 'var(--green)', label: 'Walking' },
  cycling: { icon: Bicycle, color: 'var(--blue)', label: 'Cycling' },
  snowboarding: { icon: PersonSimpleSki, color: 'var(--teal)', label: 'Snowboarding' },
  elliptical: { icon: InfinityIcon, color: 'var(--steel)', label: 'Elliptical' },
  rowing: { icon: Boat, color: 'var(--steel)', label: 'Rowing' },
  mixedCardio: { icon: Pulse, color: 'var(--orange)', label: 'Mixed cardio' },
  other: { icon: Pulse, color: 'var(--text-3)', label: 'Other' },
}

export function activityMeta(type: string | null | undefined): ActivityMeta {
  if (type && ACTIVITIES[type]) return ACTIVITIES[type]
  // strength sessions on the calendar arrive as kind:"strength"
  if (type === 'strength') return ACTIVITIES.traditionalStrength
  return { icon: Pulse, color: 'var(--text-3)', label: type || 'Workout' }
}

export const ACTIVITY_FILTERS = Object.keys(ACTIVITIES)

/** Source bundle-id → display name + badge color (real prefixes from the DB). */
const SOURCES: [prefix: string, name: string, color: string][] = [
  ['com.apple.health', 'Apple Health', '#E8E2D6'],
  ['com.strava', 'Strava', '#FC5200'],
  ['com.hevyapp', 'Hevy', '#6E91FF'],
  ['com.garmin', 'Garmin', '#48C7C7'],
  ['com.bowery-digital.bend', 'Bend', '#7C5CFF'],
]

export function sourceMeta(source: string | null | undefined): { name: string; color: string } {
  if (!source) return { name: 'Unknown', color: 'var(--text-3)' }
  const lower = source.toLowerCase()
  for (const [prefix, name, color] of SOURCES) {
    if (lower.startsWith(prefix.toLowerCase())) return { name, color }
  }
  const tail = source.split('.').filter(Boolean).pop() ?? source
  return { name: tail, color: 'var(--text-3)' }
}

/** Effort 1-10 → color ramp from the design. */
export function effortColor(effort: number | null | undefined): string {
  if (effort == null) return 'var(--faint)'
  if (effort >= 8) return 'var(--red)'
  if (effort >= 6) return 'var(--amber)'
  if (effort >= 4) return 'var(--green)'
  return 'var(--blue)'
}

/** Status chip colors (queue lifecycle + calendar). */
export function statusChip(status: string | null | undefined): { color: string; bg: string } {
  const k = (status ?? '').toLowerCase()
  if (k === 'done' || k === 'completed') return { color: '#5FB98A', bg: 'rgba(95,185,138,0.14)' }
  if (k === 'synced' || k === 'fetched') return { color: '#6E91FF', bg: 'rgba(110,145,255,0.14)' }
  if (k === 'missed') return { color: '#DC4A3B', bg: 'rgba(220,74,59,0.14)' }
  if (k === 'warn') return { color: '#E8A33D', bg: 'rgba(232,163,61,0.14)' }
  return { color: '#9A9286', bg: 'rgba(245,235,220,0.07)' }
}

export const NOTE_KINDS: Record<string, { color: string; label: string }> = {
  decision: { color: '#6E91FF', label: 'Decision' },
  preference: { color: '#9C86FF', label: 'Preference' },
  constraint: { color: '#E8A33D', label: 'Constraint' },
  life_context: { color: '#48C7C7', label: 'Context' },
  observation: { color: '#5FB98A', label: 'Observation' },
  blocker: { color: '#DC4A3B', label: 'Blocker' },
  feedback: { color: '#D9A93E', label: 'Feedback' },
}

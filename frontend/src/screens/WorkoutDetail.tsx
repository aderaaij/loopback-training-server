import { BracketsCurly, CaretDown, CaretUp, Trash } from '@phosphor-icons/react'
import { Suspense, lazy, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { usePageHeader } from '../components/PageHeader'

// Leaflet is ~150 kB — only fetched when a workout actually has a route.
const RouteMap = lazy(() => import('../components/RouteMap').then((m) => ({ default: m.RouteMap })))
import {
  ChartTooltip,
  Crosshair,
  GridLines,
  HR_ZONE_LEGEND,
  TipRow,
  areaFromLine,
  bucketElapsed,
  downsample,
  linePath,
  useChartHover,
  zoneBands,
} from '../components/charts'
import { ConfirmDialog, ErrorNote, Loading, SectionLabel, StatusPill } from '../components/ui'
import { activityMeta, sourceMeta } from '../lib/activity'
import {
  fmtDayYear,
  fmtDuration,
  fmtPace,
  fmtTime,
  paceOf,
} from '../lib/format'
import {
  useDeleteWorkout,
  useWorkout,
  useWorkoutContext,
  useWorkoutHeartRate,
  useWorkoutSplits,
} from '../lib/queries'
import type {
  CompositionStep,
  RoutePoint,
  TimedSample,
  WorkoutComposition,
  WorkoutContext,
  WorkoutSplit,
} from '../lib/types'
import '../styles/workouts.css'

const ZONE_NAMES: [limit: number, label: string][] = [
  [120, 'Z1 · Recovery'],
  [140, 'Z2 · Aerobic'],
  [155, 'Z3 · Tempo'],
  [170, 'Z4 · Threshold'],
  [999, 'Z5 · Max'],
]

function zoneOf(bpm: number): string {
  for (const [limit, label] of ZONE_NAMES) if (bpm < limit) return label
  return 'Z5 · Max'
}

function HrTrace({ samples }: { samples: TimedSample[] }) {
  const W = 560
  const H = 170
  const values = useMemo(() => downsample(samples.map((s) => s.value), 140), [samples])
  const { path, min, max } = useMemo(() => linePath(values, { w: W, h: H }), [values])
  const bands = useMemo(() => zoneBands(min, max, W, H), [min, max])
  const avg = Math.round(samples.reduce((a, s) => a + s.value, 0) / samples.length)
  const peak = Math.round(Math.max(...samples.map((s) => s.value)))
  const hover = useChartHover(values.length, 'point')
  const px = (i: number) => (values.length > 1 ? (i * W) / (values.length - 1) : W / 2)
  const bpm = hover.index != null ? values[hover.index] : null
  const elapsed = hover.index != null ? bucketElapsed(samples, hover.index, values.length) : null

  return (
    <div className="chart-card">
      <div className="chart-head">
        <SectionLabel>Heart rate</SectionLabel>
        <span className="mono-meta">
          {avg} avg · {peak} max
        </span>
      </div>
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          {bands.map((b) => (
            <rect key={b.key} x={0} y={b.y} width={b.w} height={b.h} fill={b.color} />
          ))}
          <path d={areaFromLine(path, W, H)} fill="color-mix(in srgb, var(--accent) 13%, transparent)" />
          <path
            d={path}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {hover.index != null && bpm != null && (
            <>
              <Crosshair x={px(hover.index)} h={H} />
              <circle cx={px(hover.index)} cy={H - ((bpm - min) / (max - min)) * H} r={4}
                fill="var(--accent)" stroke="var(--card-deep)" strokeWidth="2" />
            </>
          )}
        </svg>
        <ChartTooltip index={hover.index} count={values.length} mode="point">
          {bpm != null && (
            <>
              {elapsed != null && <span className="tip-date">{fmtDuration(elapsed)} in</span>}
              <TipRow color="var(--accent)" label="Heart rate" value={`${Math.round(bpm)} bpm`} />
              <TipRow label="Zone" value={zoneOf(bpm)} />
              {/* The trace is downsampled to ~140 buckets, so a reading is a
                  bucket mean rather than one sample — say so instead of
                  implying instrument precision. */}
              <span className="tip-note">Averaged over ~{Math.max(1, Math.round(samples.length / values.length))} samples</span>
            </>
          )}
        </ChartTooltip>
      </div>
      <div className="chart-legend">
        {HR_ZONE_LEGEND.map((z) => (
          <span className="cl" key={z.name}>
            <span className="sw" style={{ background: z.color }} />
            {z.name}
          </span>
        ))}
      </div>
    </div>
  )
}

function EffortCard({
  actual,
  estimated,
  avgHr,
}: {
  actual: number | null
  estimated: number | null
  avgHr: number | null
}) {
  const shown = actual ?? estimated
  if (shown == null) return null
  const C = 2 * Math.PI * 50
  const frac = Math.max(0, Math.min(1, shown / 10))
  const calibration =
    actual != null && estimated != null && Math.round(actual) !== Math.round(estimated)
      ? `${actual > estimated ? 'Harder' : 'Easier'} than the coach predicted (${Math.abs(
          Math.round(actual - estimated),
        )} point${Math.abs(Math.round(actual - estimated)) === 1 ? '' : 's'}) — logged for plan calibration.`
      : actual != null && estimated != null
        ? 'Matched the coach’s estimate.'
        : null

  return (
    <div className="effort-card">
      <SectionLabel>Effort</SectionLabel>
      <div className="effort-ring-wrap">
        <div className="effort-ring">
          <svg width="120" height="120" viewBox="0 0 120 120" style={{ transform: 'rotate(-90deg)' }}>
            <circle cx="60" cy="60" r="50" fill="none" stroke="#241F18" strokeWidth="10" />
            <circle
              cx="60"
              cy="60"
              r="50"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={`${(frac * C).toFixed(1)} ${C.toFixed(1)}`}
            />
          </svg>
          <div className="ring-center">
            <span className="ring-num">{Math.round(shown)}</span>
            <span className="ring-sub">{actual != null ? 'ACTUAL /10' : 'ESTIMATED /10'}</span>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {actual != null && estimated != null && (
            <div>
              <div className="mono-label">LLM estimated</div>
              <div className="display" style={{ fontSize: 24, fontWeight: 600, color: 'var(--blue)' }}>
                {Math.round(estimated)}
                <span style={{ fontSize: 12, color: 'var(--faint)' }}>/10</span>
              </div>
            </div>
          )}
          {avgHr != null && (
            <div>
              <div className="mono-label">Zone</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--green)' }}>{zoneOf(avgHr)}</div>
            </div>
          )}
        </div>
      </div>
      {calibration && <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.5 }}>{calibration}</div>}
    </div>
  )
}

/** Sum planned seconds/meters out of a queue composition. */
function plannedTotals(comp: WorkoutComposition): { seconds: number; meters: number } {
  let seconds = 0
  let meters = 0
  const addStep = (s: CompositionStep | undefined, times = 1) => {
    const g = s?.goal
    if (!g?.value || !Number.isFinite(g.value)) return
    if (g.type === 'time') {
      const mult = g.unit === 'minutes' ? 60 : g.unit === 'hours' ? 3600 : 1
      seconds += g.value * mult * times
    } else if (g.type === 'distance') {
      const mult = g.unit === 'kilometers' ? 1000 : g.unit === 'miles' ? 1609.34 : 1
      meters += g.value * mult * times
    }
  }
  addStep(comp.warmup)
  addStep(comp.cooldown)
  for (const b of comp.blocks ?? []) {
    for (const s of b.steps ?? []) addStep(s, b.iterations ?? 1)
  }
  return { seconds, meters }
}

function PlannedVsActual({
  comp,
  duration,
  distance,
}: {
  comp: WorkoutComposition
  duration: number | null
  distance: number | null
}) {
  const planned = plannedTotals(comp)
  const rows: { label: string; plan: string; actual: string; delta: string; color: string }[] = []

  if (planned.seconds > 0 && duration != null) {
    const d = duration - planned.seconds
    const within = Math.abs(d) / planned.seconds <= 0.05
    rows.push({
      label: 'Duration',
      plan: fmtDuration(planned.seconds),
      actual: fmtDuration(duration),
      delta: within ? 'on tgt' : `${d > 0 ? '+' : '−'}${fmtDuration(Math.abs(d))}`,
      color: within ? 'var(--green)' : 'var(--amber)',
    })
  }
  if (planned.meters > 0 && distance != null) {
    const d = distance - planned.meters
    const within = Math.abs(d) / planned.meters <= 0.05
    rows.push({
      label: 'Distance',
      plan: `${(planned.meters / 1000).toFixed(2)} km`,
      actual: `${(distance / 1000).toFixed(2)} km`,
      delta: within ? 'on tgt' : `${d > 0 ? '+' : '−'}${(Math.abs(d) / 1000).toFixed(2)}`,
      color: d >= 0 || within ? 'var(--green)' : 'var(--amber)',
    })
  }
  if (rows.length === 0) return null

  return (
    <div className="pva-card">
      <div className="pva-head">
        <span style={{ flex: 1, textAlign: 'left' }}>{comp.displayName ?? 'Planned session'}</span>
        <span className="pva-col">Planned</span>
        <span className="pva-col" style={{ color: 'var(--text)' }}>
          Actual
        </span>
        <span className="pva-delta">Δ</span>
      </div>
      {rows.map((r) => (
        <div className="pva-row" key={r.label}>
          <span className="pva-label">{r.label}</span>
          <span className="pva-col" style={{ color: 'var(--muted)' }}>
            {r.plan}
          </span>
          <span className="pva-col" style={{ fontWeight: 600 }}>
            {r.actual}
          </span>
          <span className="pva-delta" style={{ color: r.color }}>
            {r.delta}
          </span>
        </div>
      ))}
    </div>
  )
}

const FEEDBACK_ACTION_LABEL: Record<string, string> = {
  skip: 'Skipped',
  move: 'Moved',
  adjust: 'Adjusted',
}

function PlanLinkCard({ context }: { context: WorkoutContext }) {
  const qi = context.queue_item
  const fb = context.feedback
  const plan = context.plan
  if (!qi && !fb) return null

  return (
    <div className="chart-card" style={{ background: 'var(--card)' }}>
      <div className="chart-head">
        <SectionLabel>Planned session</SectionLabel>
        {qi && <StatusPill status={qi.status} />}
      </div>
      {qi && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
          <div style={{ fontSize: 14.5, fontWeight: 600 }}>{qi.title}</div>
          {qi.scheduled_date && (
            <div className="mono-meta">
              scheduled {fmtDayYear(qi.scheduled_date)} · {fmtTime(qi.scheduled_date)}
            </div>
          )}
          {plan && (
            <div style={{ fontSize: 13, color: 'var(--muted)' }}>
              Part of{' '}
              <Link to={`/plans/${plan.id}`} style={{ color: 'var(--accent)', fontWeight: 600 }}>
                {plan.name}
              </Link>{' '}
              ({plan.status})
            </div>
          )}
        </div>
      )}
      {fb && !fb.dismissed && (
        <div style={{ fontSize: 13, color: 'var(--amber)', marginTop: qi ? 10 : 4, lineHeight: 1.5 }}>
          {FEEDBACK_ACTION_LABEL[fb.action] ?? fb.action} — {fb.reason}
          {fb.reason_note ? ` · ${fb.reason_note}` : ''}
          {fb.new_date ? ` → ${fmtDayYear(fb.new_date)}` : ''}
        </div>
      )}
    </div>
  )
}

function Splits({ splits }: { splits: WorkoutSplit[] }) {
  const usable = splits.filter((s) => s.pace != null || (s.duration != null && s.distance != null))
  if (usable.length === 0) return null
  const paceOfSplit = (s: WorkoutSplit) =>
    s.pace ?? (s.duration! / (s.distance! / 1000))
  const paces = usable.map(paceOfSplit)
  const fast = Math.min(...paces)
  const slow = Math.max(...paces)
  const avg = paces.reduce((a, b) => a + b, 0) / paces.length

  return (
    <div className="chart-card" style={{ background: 'var(--card)', paddingBottom: 10 }}>
      <div className="chart-head">
        <SectionLabel>1 km splits</SectionLabel>
        <span className="mono-meta">avg {fmtPace(avg)}</span>
      </div>
      {usable.map((s, i) => {
        const pace = paceOfSplit(s)
        const isFast = pace === fast
        const pct = slow === fast ? 100 : Math.round(45 + ((slow - pace) / (slow - fast)) * 55)
        const partial = s.distance != null && s.distance < 950
        const label = partial ? (s.distance! / 1000).toFixed(2) : String(s.index ?? i + 1)
        return (
          <div className="split-row" key={i}>
            <span className="s-km">{label}</span>
            <span className="s-pace" style={{ color: isFast ? 'var(--accent)' : 'var(--text-2)' }}>
              {fmtPace(pace)}
            </span>
            <div className="s-track">
              <div
                className="s-bar"
                style={{
                  width: `${pct}%`,
                  background: isFast
                    ? 'var(--accent)'
                    : 'color-mix(in srgb, var(--accent) 45%, #4A4036)',
                }}
              />
            </div>
            <span className="s-hr">
              {s.averageHeartRate != null ? (
                <>
                  {Math.round(s.averageHeartRate)}
                  <span style={{ color: 'var(--faint)' }}> bpm</span>
                </>
              ) : (
                '—'
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function CadenceChart({ samples }: { samples: TimedSample[] }) {
  const values = useMemo(() => downsample(samples.map((s) => s.value), 26), [samples])
  // Before the early return — the hook count must not depend on the data.
  const hover = useChartHover(values.length)
  if (values.length === 0) return null
  const avg = Math.round(samples.reduce((a, s) => a + s.value, 0) / samples.length)
  const W = 560
  const H = 150
  const min = Math.min(...values)
  const max = Math.max(...values)
  const bw = W / values.length
  const spm = hover.index != null ? values[hover.index] : null
  const elapsed = hover.index != null ? bucketElapsed(samples, hover.index, values.length) : null

  return (
    <div className="chart-card">
      <div className="chart-head">
        <SectionLabel>Cadence</SectionLabel>
        <span className="mono-meta">{avg} avg spm</span>
      </div>
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <GridLines w={W} h={H} rows={2} />
          {values.map((v, i) => {
            const h = max === min ? H * 0.6 : 20 + ((v - min) / (max - min)) * (H - 40)
            return (
              <rect
                key={i}
                x={i * bw + bw * 0.15}
                y={H - h}
                width={bw * 0.7}
                height={h}
                rx={3}
                opacity={hover.index != null && hover.index !== i ? 0.4 : 1}
                fill={
                  i === values.length - 1
                    ? 'var(--accent)'
                    : 'color-mix(in srgb, var(--accent) 40%, #3A332A)'
                }
              />
            )
          })}
        </svg>
        <ChartTooltip index={hover.index} count={values.length}>
          {spm != null && (
            <>
              {elapsed != null && <span className="tip-date">{fmtDuration(elapsed)} in</span>}
              <TipRow color="var(--accent)" label="Cadence" value={`${Math.round(spm)} spm`} />
            </>
          )}
        </ChartTooltip>
      </div>
    </div>
  )
}

export function WorkoutDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data: workout, isLoading, error } = useWorkout(id)
  const { data: splits } = useWorkoutSplits(id)
  const { data: heartRate } = useWorkoutHeartRate(id)
  const { data: context } = useWorkoutContext(id)
  const deleteWorkout = useDeleteWorkout()
  const [rawOpen, setRawOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const meta = activityMeta(workout?.activity_type)
  const src = sourceMeta(workout?.source)
  usePageHeader(
    workout ? meta.label : 'Workout',
    workout
      ? `${fmtDayYear(workout.start_date)} · ${fmtTime(workout.start_date)} · ${src.name}`
      : undefined,
    '/workouts',
  )

  const route = useMemo(() => {
    const r = workout?.data?.route
    return Array.isArray(r) ? (r as RoutePoint[]).filter((p) => p.latitude != null && p.longitude != null) : []
  }, [workout])

  const cadence = useMemo(() => {
    const c = workout?.data?.cadence
    return Array.isArray(c) ? (c as TimedSample[]).filter((s) => typeof s?.value === 'number') : []
  }, [workout])

  const hrSamples = useMemo(
    () => (heartRate ?? []).filter((s) => typeof s?.value === 'number'),
    [heartRate],
  )

  const avgHr = useMemo(() => {
    if (hrSamples.length === 0) return null
    return Math.round(hrSamples.reduce((a, s) => a + s.value, 0) / hrSamples.length)
  }, [hrSamples])

  const queueItem = context?.queue_item

  const rawJson = useMemo(() => {
    if (!workout) return ''
    const summary = Object.fromEntries(
      Object.entries(workout.data ?? {}).map(([k, v]) =>
        Array.isArray(v) ? [k, `[${v.length} items]`] : [k, v],
      ),
    )
    return JSON.stringify(summary, null, 2)
  }, [workout])

  if (isLoading) return <Loading label="Loading workout…" />
  if (error) return <ErrorNote error={error} />
  if (!workout) return null

  const pace = workout.activity_type === 'running' ? paceOf(workout.duration, workout.total_distance) : null

  const stats = [
    workout.total_distance != null && {
      label: 'Distance',
      value: (workout.total_distance / 1000).toFixed(2),
      unit: 'km',
      color: 'var(--text)',
    },
    { label: 'Duration', value: fmtDuration(workout.duration), unit: '', color: 'var(--text)' },
    pace != null && { label: 'Avg pace', value: fmtPace(pace), unit: '/km', color: 'var(--accent)' },
    avgHr != null && { label: 'Avg HR', value: String(avgHr), unit: 'bpm', color: 'var(--text)' },
    workout.total_energy_burned != null && {
      label: 'Energy',
      value: String(Math.round(workout.total_energy_burned)),
      unit: 'kcal',
      color: 'var(--text)',
    },
  ].filter((s): s is { label: string; value: string; unit: string; color: string } => Boolean(s))

  return (
    <div className="screen">
      <div className="det-stats" style={{ gridTemplateColumns: `repeat(${Math.min(stats.length, 5)}, 1fr)` }}>
        {stats.map((s) => (
          <div className="det-stat" key={s.label}>
            <div className="label">{s.label}</div>
            <div className="value" style={{ color: s.color }}>
              {s.value}
              {s.unit && <span className="unit"> {s.unit}</span>}
            </div>
          </div>
        ))}
      </div>

      {(hrSamples.length > 1 || workout.effort_score != null || workout.estimated_effort_score != null) && (
        <div className="det-grid">
          {hrSamples.length > 1 ? (
            <HrTrace samples={hrSamples} />
          ) : (
            <div className="chart-card">
              <SectionLabel>Heart rate</SectionLabel>
              <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 12 }}>
                No heart-rate samples recorded for this session.
              </div>
            </div>
          )}
          <EffortCard
            actual={workout.effort_score}
            estimated={workout.estimated_effort_score}
            avgHr={avgHr}
          />
        </div>
      )}

      {context && <PlanLinkCard context={context} />}

      {queueItem?.workout_data && (
        <PlannedVsActual
          comp={queueItem.workout_data}
          duration={workout.duration}
          distance={workout.total_distance}
        />
      )}

      {((splits && splits.length > 0) || cadence.length > 0) && (
        <div className="det-grid-half">
          {splits && splits.length > 0 && <Splits splits={splits} />}
          {cadence.length > 0 && <CadenceChart samples={cadence} />}
        </div>
      )}

      {route.length > 1 && (
        <div className="route-card">
          <div className="card-head">
            <SectionLabel>Route</SectionLabel>
            <span className="mono-meta">
              GPS · {route.length.toLocaleString()} points · OSM tiles
            </span>
          </div>
          <Suspense fallback={<div className="route-map" />}>
            <RouteMap points={route} />
          </Suspense>
        </div>
      )}

      <button className="raw-toggle" onClick={() => setRawOpen((o) => !o)}>
        <span
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            gap: 9,
            fontSize: 13.5,
            fontWeight: 600,
            color: 'var(--text-2)',
          }}
        >
          <BracketsCurly size={17} color="var(--muted)" />
          Raw metadata JSON
        </span>
        {rawOpen ? <CaretUp size={16} color="var(--muted)" /> : <CaretDown size={16} color="var(--muted)" />}
      </button>
      {rawOpen && <div className="raw-json">{rawJson}</div>}

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 18 }}>
        <button className="btn-danger-outline" onClick={() => setConfirmDelete(true)}>
          <Trash size={16} />
          Delete workout
        </button>
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title="Delete this workout?"
          body="This permanently removes the workout and all its samples from the server. The copy in Apple Health is not affected."
          confirmLabel="Delete"
          busy={deleteWorkout.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => {
            deleteWorkout.mutate(workout.id, {
              onSuccess: () => navigate('/workouts'),
            })
          }}
        />
      )}
    </div>
  )
}

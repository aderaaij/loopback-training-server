import { Heartbeat } from '@phosphor-icons/react'
import { useMemo, useState } from 'react'
import { usePageHeader } from '../components/PageHeader'
import {
  ChartTooltip,
  Crosshair,
  GridLines,
  TipRow,
  areaFromLine,
  groupByWeek,
  linePath,
  useChartHover,
} from '../components/charts'
import { NutritionSection } from '../components/NutritionCards'
import { EmptyState, ErrorNote, Loading, SectionLabel } from '../components/ui'
import { addDays, fmtDay, fmtHoursMinutes, toDateKey } from '../lib/format'
import { useHealthMetrics, useNutrition, useNutritionSummary } from '../lib/queries'
import type { HealthMetricsDay } from '../lib/types'
import '../styles/workouts.css'
import '../styles/health.css'

// `weekly` is what the range toggle actually does to the daily bar charts:
// beyond ~5 weeks a day-per-bar chart is a 3px slot nobody can read or hover,
// so those ranges aggregate into ISO weeks. The line charts keep every day —
// a dense line is still a legible line.
const RANGES = [
  { key: '30', label: '30d', days: 30, weekly: false },
  { key: '90', label: '90d', days: 90, weekly: true },
  { key: '365', label: '1y', days: 365, weekly: true },
] as const

type Range = (typeof RANGES)[number]

const SLEEP_COLORS = { deep: '#3A4A6E', core: '#6E91FF', rem: '#48C7C7' }

const mean = (values: number[]): number | null =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : null

function RecoveryChart({ days }: { days: HealthMetricsDay[] }) {
  const W = 1080
  const H = 180
  const rhr = days.map((d) => d.resting_heart_rate)
  const hrv = days.map((d) => d.hrv_sdnn)
  const rhrLine = useMemo(() => linePath(rhr, { w: W, h: H, connectGaps: true }), [days]) // eslint-disable-line react-hooks/exhaustive-deps
  const hrvLine = useMemo(() => linePath(hrv, { w: W, h: H, connectGaps: true }), [days]) // eslint-disable-line react-hooks/exhaustive-deps

  const lastOf = (vals: (number | null)[]) => {
    for (let i = vals.length - 1; i >= 0; i--) if (vals[i] != null) return vals[i]
    return null
  }
  const lastRhr = lastOf(rhr)
  const lastHrv = lastOf(hrv)
  // Hooks before the early return: a chart that vanishes when its data does
  // must not change the hook count on the way out.
  const hover = useChartHover(days.length, 'point')
  const hovered = hover.index != null ? days[hover.index] : null
  if (!rhrLine.path && !hrvLine.path) return null
  const px = (i: number) => (days.length > 1 ? (i * W) / (days.length - 1) : W / 2)

  return (
    <div className="chart-card" style={{ gridColumn: 'span 2' }}>
      <div className="chart-head">
        <SectionLabel>Recovery · resting HR + HRV</SectionLabel>
        <div className="hm-legend">
          {lastRhr != null && (
            <span style={{ color: 'var(--orange)' }}>
              <span className="line-swatch" style={{ background: 'var(--orange)' }} />
              RHR {Math.round(lastRhr)} bpm
            </span>
          )}
          {lastHrv != null && (
            <span style={{ color: 'var(--green)' }}>
              <span className="line-swatch" style={{ background: 'var(--green)' }} />
              HRV {Math.round(lastHrv)} ms
            </span>
          )}
        </div>
      </div>
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <GridLines w={W} h={H} rows={3} />
          {hover.index != null && <Crosshair x={px(hover.index)} h={H} />}
          {hrvLine.path && (
            <path d={hrvLine.path} fill="none" stroke="var(--green)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          )}
          {rhrLine.path && (
            <path d={rhrLine.path} fill="none" stroke="var(--orange)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          )}
          {/* Markers only on the hovered sample — a dot on all 365 would be a
              solid band, and the line already carries the shape. */}
          {hovered?.hrv_sdnn != null && (
            <circle cx={px(hover.index!)} cy={yFor(hovered.hrv_sdnn, hrvLine, H)} r={4}
              fill="var(--green)" stroke="var(--card-deep)" strokeWidth="2" />
          )}
          {hovered?.resting_heart_rate != null && (
            <circle cx={px(hover.index!)} cy={yFor(hovered.resting_heart_rate, rhrLine, H)} r={4}
              fill="var(--orange)" stroke="var(--card-deep)" strokeWidth="2" />
          )}
        </svg>
        <ChartTooltip index={hover.index} count={days.length} mode="point">
          {hovered && (
            <>
              <span className="tip-date">{fmtDay(hovered.date)}</span>
              <TipRow color="var(--orange)" label="Resting HR"
                value={hovered.resting_heart_rate != null ? `${Math.round(hovered.resting_heart_rate)} bpm` : '—'} />
              <TipRow color="var(--green)" label="HRV"
                value={hovered.hrv_sdnn != null ? `${Math.round(hovered.hrv_sdnn)} ms` : '—'} />
            </>
          )}
        </ChartTooltip>
      </div>
    </div>
  )
}

/** Invert linePath's scaling for one value, so a marker lands on the line. */
function yFor(value: number, line: { min: number; max: number }, h: number): number {
  return h - ((value - line.min) / (line.max - line.min)) * h
}

/** Index of the day nearest `from` that carries a weight, searching outwards. */
function nearestWeighIn(days: HealthMetricsDay[], from: number): number | null {
  for (let r = 0; r < days.length; r++) {
    if (from - r >= 0 && days[from - r].weight != null) return from - r
    if (from + r < days.length && days[from + r].weight != null) return from + r
  }
  return null
}

/** One drawn bar: a night, or a week of nights averaged. */
type SleepBar = {
  key: string
  label: string
  nights: number
  duration: number | null
  deep: number
  core: number
  rem: number
  staged: boolean
}

function sleepBars(days: HealthMetricsDay[], weekly: boolean): SleepBar[] {
  const withSleep = days.filter((d) => d.sleep_duration != null || d.sleep_stages != null)
  const toBar = (rows: HealthMetricsDay[], key: string, label: string): SleepBar => {
    const staged = rows.filter((d) => d.sleep_stages != null)
    const stage = (k: 'deep' | 'core' | 'rem') =>
      // Divided by the number of STAGED nights, not all nights: a night with
      // no breakdown contributes nothing to a stage, and dividing by it would
      // drag every stage down and make the stack fall short of the total.
      mean(staged.map((d) => d.sleep_stages?.[k] ?? 0)) ?? 0
    return {
      key,
      label,
      nights: rows.length,
      duration: mean(rows.filter((d) => d.sleep_duration != null).map((d) => d.sleep_duration!)),
      deep: stage('deep'),
      core: stage('core'),
      rem: stage('rem'),
      staged: staged.length > 0,
    }
  }
  if (!weekly) return withSleep.map((d) => toBar([d], d.date, fmtDay(d.date)))
  return groupByWeek(withSleep, (d) => d.date).map((g) =>
    toBar(g.rows, g.week, `week of ${fmtDay(g.week)}`),
  )
}

function SleepChart({ days, range }: { days: HealthMetricsDay[]; range: Range }) {
  const bars = sleepBars(days, range.weekly)
  // Before the early return — the hook count must not depend on the data.
  const hover = useChartHover(bars.length)
  const hovered = hover.index != null ? bars[hover.index] : null
  if (bars.length === 0) return null
  const W = 480
  const H = 150
  const bw = W / Math.max(bars.length, 1)
  const maxSecs = Math.max(...bars.map((b) => Math.max(b.duration ?? 0, b.deep + b.core + b.rem)), 1)
  // Over the whole selected range, not the drawn window — they are the same
  // set now, which is the point: the toggle used to move the data and leave
  // this number pinned to the last 14 nights.
  const avg = mean(days.filter((d) => d.sleep_duration != null).map((d) => d.sleep_duration!))

  return (
    <div className="chart-card" style={{ background: 'var(--card)' }}>
      <div className="chart-head">
        <SectionLabel>Sleep{range.weekly && ' · weekly'}</SectionLabel>
        <span className="mono-meta">{avg != null ? `${fmtHoursMinutes(avg)} avg` : '—'}</span>
      </div>
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          {bars.map((b, i) => {
            const scale = (v: number) => (v / maxSecs) * (H - 10)
            const deep = scale(b.deep)
            const core = scale(b.core)
            const rem = scale(b.rem)
            const total = deep + core + rem
            const x = i * bw + bw * 0.16
            const width = bw * 0.68
            const op = hover.index != null && hover.index !== i ? 0.4 : 1
            if (total === 0 && b.duration != null) {
              // no stage breakdown — single block
              const h = scale(b.duration)
              return <rect key={b.key} x={x} y={H - h} width={width} height={h} rx={2} fill={SLEEP_COLORS.core} opacity={0.65 * op} />
            }
            const top = H - total
            return (
              <g key={b.key} opacity={op}>
                <rect x={x} y={top} width={width} height={deep} rx={2} fill={SLEEP_COLORS.deep} />
                <rect x={x} y={top + deep} width={width} height={core} fill={SLEEP_COLORS.core} />
                <rect x={x} y={top + deep + core} width={width} height={rem} rx={2} fill={SLEEP_COLORS.rem} />
              </g>
            )
          })}
        </svg>
        <ChartTooltip index={hover.index} count={bars.length}>
          {hovered && (
            <>
              <span className="tip-date">{hovered.label}</span>
              <TipRow label={range.weekly ? 'Asleep · avg' : 'Asleep'}
                value={hovered.duration != null ? fmtHoursMinutes(hovered.duration) : '—'} />
              {hovered.staged ? (
                <>
                  <TipRow color={SLEEP_COLORS.deep} label="Deep" value={fmtHoursMinutes(hovered.deep)} />
                  <TipRow color={SLEEP_COLORS.core} label="Core" value={fmtHoursMinutes(hovered.core)} />
                  <TipRow color={SLEEP_COLORS.rem} label="REM" value={fmtHoursMinutes(hovered.rem)} />
                </>
              ) : (
                <span className="tip-note">No stage breakdown recorded.</span>
              )}
              {range.weekly && (
                <span className="tip-note">
                  {hovered.nights} {hovered.nights === 1 ? 'night' : 'nights'} recorded
                </span>
              )}
            </>
          )}
        </ChartTooltip>
      </div>
      <div className="chart-legend">
        <span className="cl">
          <span className="sw" style={{ background: SLEEP_COLORS.deep }} />
          Deep
        </span>
        <span className="cl">
          <span className="sw" style={{ background: SLEEP_COLORS.core }} />
          Core
        </span>
        <span className="cl">
          <span className="sw" style={{ background: SLEEP_COLORS.rem }} />
          REM
        </span>
      </div>
    </div>
  )
}

function WeightChart({ days }: { days: HealthMetricsDay[] }) {
  const values = days.map((d) => d.weight)
  const present = values.filter((v): v is number => v != null)
  // Hover resolves in the FULL day series — that is the axis the line is drawn
  // on — and then snaps to the nearest day that actually holds a reading.
  // Indexing the weigh-ins directly would space them evenly, which they are
  // not, and the marker would drift off the line it is meant to sit on.
  const hover = useChartHover(days.length, 'point')
  const at = hover.index != null ? nearestWeighIn(days, hover.index) : null
  const hovered = at != null ? days[at] : null
  if (present.length < 2) return null
  const W = 480
  const H = 150
  const line = linePath(values, { w: W, h: H, pad: 0.25, connectGaps: true })
  const last = present[present.length - 1]
  const px = (i: number) => (days.length > 1 ? (i * W) / (days.length - 1) : W / 2)

  return (
    <div className="chart-card">
      <div className="chart-head">
        <SectionLabel>Weight</SectionLabel>
        <span className="mono-meta">{last.toFixed(1)} kg</span>
      </div>
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <GridLines w={W} h={H} rows={2} />
          <path d={areaFromLine(line.path, W, H)} fill="color-mix(in srgb, var(--accent) 10%, transparent)" />
          <path d={line.path} fill="none" stroke="var(--accent)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          {hovered && at != null && (
            <>
              <Crosshair x={px(at)} h={H} />
              <circle cx={px(at)} cy={yFor(hovered.weight!, line, H)} r={4}
                fill="var(--accent)" stroke="var(--card-deep)" strokeWidth="2" />
            </>
          )}
        </svg>
        <ChartTooltip index={at} count={days.length} mode="point">
          {hovered && (
            <>
              <span className="tip-date">{fmtDay(hovered.date)}</span>
              <TipRow color="var(--accent)" label="Weight" value={`${hovered.weight!.toFixed(1)} kg`} />
              {hovered.body_fat_percentage != null && (
                <TipRow label="Body fat" value={`${hovered.body_fat_percentage.toFixed(1)} %`} />
              )}
              {hovered.lean_body_mass != null && (
                <TipRow label="Lean mass" value={`${hovered.lean_body_mass.toFixed(1)} kg`} />
              )}
            </>
          )}
        </ChartTooltip>
      </div>
    </div>
  )
}

type StepBar = { key: string; label: string; days: number; steps: number; active: number | null }

function stepBars(days: HealthMetricsDay[], weekly: boolean): StepBar[] {
  const withSteps = days.filter((d) => d.steps != null)
  const toBar = (rows: HealthMetricsDay[], key: string, label: string): StepBar => ({
    key,
    label,
    days: rows.length,
    steps: mean(rows.map((d) => d.steps!)) ?? 0,
    active: mean(
      rows.filter((d) => d.active_energy_burned != null).map((d) => d.active_energy_burned!),
    ),
  })
  if (!weekly) return withSteps.map((d) => toBar([d], d.date, fmtDay(d.date)))
  return groupByWeek(withSteps, (d) => d.date).map((g) =>
    toBar(g.rows, g.week, `week of ${fmtDay(g.week)}`),
  )
}

function StepsChart({ days, range }: { days: HealthMetricsDay[]; range: Range }) {
  const bars = stepBars(days, range.weekly)
  // Before the early return — the hook count must not depend on the data.
  const hover = useChartHover(bars.length)
  const hovered = hover.index != null ? bars[hover.index] : null
  if (bars.length === 0) return null
  const W = 1080
  const H = 120
  const bw = W / bars.length
  const max = Math.max(...bars.map((b) => b.steps), 10000)
  // Over every day in range. A weekly bar is already a mean, so averaging the
  // bars would weight a 3-day week the same as a 7-day one.
  const avg = mean(days.filter((d) => d.steps != null).map((d) => d.steps!))

  return (
    <div className="chart-card" style={{ gridColumn: 'span 2', background: 'var(--card)' }}>
      <div className="chart-head">
        <SectionLabel>{range.weekly ? 'Steps · weekly average' : 'Daily steps'}</SectionLabel>
        <span className="mono-meta">{avg != null ? `${Math.round(avg).toLocaleString('en-US')} avg` : '—'}</span>
      </div>
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          {bars.map((b, i) => {
            const h = Math.max(2, (b.steps / max) * (H - 10))
            return (
              <rect
                key={b.key}
                x={i * bw + bw * 0.12}
                y={H - h}
                width={bw * 0.76}
                height={h}
                rx={3}
                opacity={hover.index != null && hover.index !== i ? 0.4 : 1}
                fill={b.steps > 10000 ? 'var(--green)' : 'color-mix(in srgb, var(--accent) 40%, #3A332A)'}
              />
            )
          })}
        </svg>
        <ChartTooltip index={hover.index} count={bars.length}>
          {hovered && (
            <>
              <span className="tip-date">{hovered.label}</span>
              <TipRow color={hovered.steps > 10000 ? 'var(--green)' : 'var(--accent)'}
                label={range.weekly ? 'Steps · avg/day' : 'Steps'}
                value={Math.round(hovered.steps).toLocaleString('en-US')} />
              {hovered.active != null && (
                <TipRow label={range.weekly ? 'Active · avg/day' : 'Active energy'}
                  value={`${Math.round(hovered.active)} kcal`} />
              )}
              {range.weekly && (
                <span className="tip-note">
                  {hovered.days} {hovered.days === 1 ? 'day' : 'days'} recorded
                </span>
              )}
            </>
          )}
        </ChartTooltip>
      </div>
    </div>
  )
}

export function Health() {
  const [range, setRange] = useState<Range>(RANGES[0])
  const start = toDateKey(addDays(new Date(), -range.days))
  const { data, isLoading, error } = useHealthMetrics(start)
  const nutrition = useNutrition(start)
  const nutritionSummary = useNutritionSummary(start, 'week')

  // API returns desc by date; charts want chronological order.
  const days = useMemo(() => [...(data ?? [])].reverse(), [data])
  const nutritionDays = useMemo(() => [...(nutrition.data ?? [])].reverse(), [nutrition.data])

  usePageHeader('Health trends', data ? `${data.length} days of metrics in range` : undefined)

  return (
    <div className="screen">
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 18 }}>
        <div className="seg-toggle">
          {RANGES.map((r) => (
            <button key={r.key} className={range.key === r.key ? 'on' : ''} onClick={() => setRange(r)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorNote error={error} />}
      {isLoading && <Loading label="Loading metrics…" />}

      {!isLoading && days.length === 0 && !error && (
        <div className="card">
          <EmptyState icon={Heartbeat} title="No health data in this range">
            Daily metrics (sleep, resting HR, HRV, weight, steps) sync from HealthKit via the iOS
            app. Widen the range or check the app is logged in.
          </EmptyState>
        </div>
      )}

      {days.length > 0 && (
        <div className="health-grid">
          <RecoveryChart days={days} />
          <SleepChart days={days} range={range} />
          <WeightChart days={days} />
          <StepsChart days={days} range={range} />
        </div>
      )}

      {nutrition.error && <ErrorNote error={nutrition.error} />}
      {/* With nothing at all in range the metrics empty state above says it
          once; no need for a second card saying it again. */}
      {!nutrition.isLoading && !nutrition.error && (days.length > 0 || nutritionDays.length > 0) && (
        <NutritionSection
          days={nutritionDays}
          periods={nutritionSummary.data?.periods ?? []}
          // Same range, same fetch as the charts above — the energy balance is
          // a join of these two series on the day, done here rather than
          // server-side because both are already in hand.
          metrics={days}
          rangeDays={range.days}
        />
      )}
    </div>
  )
}

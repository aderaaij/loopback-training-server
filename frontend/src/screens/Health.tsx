import { Heartbeat } from '@phosphor-icons/react'
import { useMemo, useState } from 'react'
import { usePageHeader } from '../components/PageHeader'
import { GridLines, areaFromLine, linePath } from '../components/charts'
import { NutritionSection } from '../components/NutritionCards'
import { EmptyState, ErrorNote, Loading, SectionLabel } from '../components/ui'
import { addDays, fmtHoursMinutes, toDateKey } from '../lib/format'
import { useHealthMetrics, useNutrition, useNutritionSummary } from '../lib/queries'
import type { HealthMetricsDay } from '../lib/types'
import '../styles/workouts.css'
import '../styles/health.css'

const RANGES = [
  { key: '30', label: '30d', days: 30 },
  { key: '90', label: '90d', days: 90 },
  { key: '365', label: '1y', days: 365 },
] as const

const SLEEP_COLORS = { deep: '#3A4A6E', core: '#6E91FF', rem: '#48C7C7' }

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
  if (!rhrLine.path && !hrvLine.path) return null

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
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <GridLines w={W} h={H} rows={3} />
        {hrvLine.path && (
          <path d={hrvLine.path} fill="none" stroke="var(--green)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        )}
        {rhrLine.path && (
          <path d={rhrLine.path} fill="none" stroke="var(--orange)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        )}
      </svg>
    </div>
  )
}

function SleepChart({ days }: { days: HealthMetricsDay[] }) {
  const withSleep = days.filter((d) => d.sleep_duration != null || d.sleep_stages != null).slice(-14)
  if (withSleep.length === 0) return null
  const W = 480
  const H = 150
  const bw = W / Math.max(withSleep.length, 1)
  const maxSecs = Math.max(
    ...withSleep.map((d) => {
      const st = d.sleep_stages
      const stagesTotal = (st?.deep ?? 0) + (st?.core ?? 0) + (st?.rem ?? 0)
      return Math.max(d.sleep_duration ?? 0, stagesTotal)
    }),
  )
  const avg =
    withSleep.reduce((a, d) => a + (d.sleep_duration ?? 0), 0) /
    Math.max(1, withSleep.filter((d) => d.sleep_duration != null).length)

  return (
    <div className="chart-card" style={{ background: 'var(--card)' }}>
      <div className="chart-head">
        <SectionLabel>Sleep</SectionLabel>
        <span className="mono-meta">{fmtHoursMinutes(avg)} avg</span>
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {withSleep.map((d, i) => {
          const st = d.sleep_stages
          const scale = (v: number) => (v / maxSecs) * (H - 10)
          const deep = scale(st?.deep ?? 0)
          const core = scale(st?.core ?? 0)
          const rem = scale(st?.rem ?? 0)
          const total = deep + core + rem
          const x = i * bw + bw * 0.16
          const width = bw * 0.68
          if (total === 0 && d.sleep_duration != null) {
            // no stage breakdown — single block
            const h = scale(d.sleep_duration)
            return <rect key={d.date} x={x} y={H - h} width={width} height={h} rx={2} fill={SLEEP_COLORS.core} opacity={0.65} />
          }
          const top = H - total
          return (
            <g key={d.date}>
              <rect x={x} y={top} width={width} height={deep} rx={2} fill={SLEEP_COLORS.deep} />
              <rect x={x} y={top + deep} width={width} height={core} fill={SLEEP_COLORS.core} />
              <rect x={x} y={top + deep + core} width={width} height={rem} rx={2} fill={SLEEP_COLORS.rem} />
            </g>
          )
        })}
      </svg>
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
  if (present.length < 2) return null
  const W = 480
  const H = 150
  const { path } = linePath(values, { w: W, h: H, pad: 0.25, connectGaps: true })
  const last = present[present.length - 1]

  return (
    <div className="chart-card">
      <div className="chart-head">
        <SectionLabel>Weight</SectionLabel>
        <span className="mono-meta">{last.toFixed(1)} kg</span>
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <GridLines w={W} h={H} rows={2} />
        <path d={areaFromLine(path, W, H)} fill="color-mix(in srgb, var(--accent) 10%, transparent)" />
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  )
}

function StepsChart({ days }: { days: HealthMetricsDay[] }) {
  const withSteps = days.filter((d) => d.steps != null).slice(-30)
  if (withSteps.length === 0) return null
  const W = 1080
  const H = 120
  const bw = W / withSteps.length
  const max = Math.max(...withSteps.map((d) => d.steps!), 10000)
  const avg = Math.round(withSteps.reduce((a, d) => a + d.steps!, 0) / withSteps.length)

  return (
    <div className="chart-card" style={{ gridColumn: 'span 2', background: 'var(--card)' }}>
      <div className="chart-head">
        <SectionLabel>Daily steps</SectionLabel>
        <span className="mono-meta">{avg.toLocaleString('en-US')} avg</span>
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {withSteps.map((d, i) => {
          const h = Math.max(2, (d.steps! / max) * (H - 10))
          return (
            <rect
              key={d.date}
              x={i * bw + bw * 0.12}
              y={H - h}
              width={bw * 0.76}
              height={h}
              rx={3}
              fill={d.steps! > 10000 ? 'var(--green)' : 'color-mix(in srgb, var(--accent) 40%, #3A332A)'}
            />
          )
        })}
      </svg>
    </div>
  )
}

export function Health() {
  const [range, setRange] = useState<(typeof RANGES)[number]>(RANGES[0])
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
          <SleepChart days={days} />
          <WeightChart days={days} />
          <StepsChart days={days} />
        </div>
      )}

      {nutrition.error && <ErrorNote error={nutrition.error} />}
      {/* With nothing at all in range the metrics empty state above says it
          once; no need for a second card saying it again. */}
      {!nutrition.isLoading && !nutrition.error && (days.length > 0 || nutritionDays.length > 0) && (
        <NutritionSection days={nutritionDays} periods={nutritionSummary.data?.periods ?? []} />
      )}
    </div>
  )
}

/**
 * Nutrition cards for the Health screen.
 *
 * Colour: carbs / protein / fat are a fixed categorical triple — assigned by
 * nutrient, never by rank, so filtering a range never repaints a macro. The
 * steps are darker than the app's --amber/--teal/--purple tokens because those
 * sit above the dark-mode lightness band; these were validated for lightness,
 * chroma, CVD separation (worst adjacent ΔE 15.9) and contrast against --card.
 *
 * Deliberately NO dual-axis chart: intake and body weight are different scales,
 * so they get separate cards (weight already has one on this screen) rather
 * than two y-axes on one plot.
 */
import { ForkKnife } from '@phosphor-icons/react'
import { GridLines } from './charts'
import { EmptyState, SectionLabel } from './ui'
import { fmtDay } from '../lib/format'
import type { NutritionDay, NutritionPeriod } from '../lib/types'

const MACROS = [
  { key: 'carbs_g' as const, label: 'Carbs', color: '#c07f28' },
  { key: 'protein_g' as const, label: 'Protein', color: '#00a8a8' },
  { key: 'fat_g' as const, label: 'Fat', color: '#7457f0' },
]

/** Athlete protein target, g per kg bodyweight — the band the chart shades. */
const PROTEIN_BAND = { lo: 1.6, hi: 2.0 }

const round = (v: number, d = 0) => Number(v.toFixed(d))

function mean(values: number[]): number | null {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null
}

/** Complete days only: a partial day holds a fraction of its real intake. */
function complete(days: NutritionDay[]): NutritionDay[] {
  return days.filter((d) => !d.partial)
}

function MacroChart({ days }: { days: NutritionDay[] }) {
  const withMacros = days
    .filter((d) => MACROS.some((m) => d[m.key] != null))
    .slice(-21)
  if (withMacros.length === 0) return null

  const W = 1080
  const H = 190
  const GAP = 2 // surface gap between stacked segments
  const bw = W / withMacros.length
  const totals = withMacros.map((d) => MACROS.reduce((a, m) => a + (d[m.key] ?? 0), 0))
  const max = Math.max(...totals, 1)
  const avgTotal = mean(totals)

  return (
    <div className="chart-card" style={{ gridColumn: 'span 2' }}>
      <div className="chart-head">
        <SectionLabel>Macros · grams per day</SectionLabel>
        <div className="hm-legend">
          {MACROS.map((m) => {
            const avg = mean(withMacros.map((d) => d[m.key]).filter((v): v is number => v != null))
            return (
              <span key={m.key}>
                <span className="line-swatch" style={{ background: m.color }} />
                {m.label}
                {avg != null && <span style={{ color: 'var(--muted)' }}> {round(avg)}g</span>}
              </span>
            )
          })}
        </div>
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label={`Daily macronutrient grams for the last ${withMacros.length} logged days`}>
        <GridLines w={W} h={H} rows={3} />
        {withMacros.map((d, i) => {
          const x = i * bw + bw * 0.16
          const width = bw * 0.68
          let y = H
          return (
            <g key={d.date} opacity={d.partial ? 0.45 : 1}>
              <title>
                {`${fmtDay(d.date)}${d.partial ? ' (partial)' : ''} — ` +
                  MACROS.map((m) => `${m.label} ${d[m.key] != null ? round(d[m.key]!) + 'g' : '—'}`).join(', ')}
              </title>
              {MACROS.map((m) => {
                const grams = d[m.key]
                if (grams == null || grams <= 0) return null
                const h = (grams / max) * (H - 12)
                if (h <= 0) return null
                y -= h
                const seg = <rect key={m.key} x={x} y={y} width={width} height={Math.max(h - GAP, 1)} rx={2} fill={m.color} />
                y -= GAP
                return seg
              })}
            </g>
          )
        })}
      </svg>
      {avgTotal != null && (
        <div className="chart-legend">
          <span className="cl" style={{ color: 'var(--muted)' }}>
            {round(avgTotal)}g total per day on average · {withMacros.length} days shown
          </span>
        </div>
      )}
    </div>
  )
}

function EnergyChart({ days }: { days: NutritionDay[] }) {
  const withEnergy = days.filter((d) => d.energy_kcal != null).slice(-21)
  if (withEnergy.length === 0) return null

  const W = 480
  const H = 150
  const bw = W / withEnergy.length
  const max = Math.max(...withEnergy.map((d) => d.energy_kcal!), 1)
  const avg = mean(complete(withEnergy).map((d) => d.energy_kcal!))

  return (
    <div className="chart-card" style={{ background: 'var(--card)' }}>
      <div className="chart-head">
        <SectionLabel>Energy intake</SectionLabel>
        <span className="mono-meta">{avg != null ? `${round(avg)} kcal avg` : '—'}</span>
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label="Daily energy intake in kilocalories">
        <GridLines w={W} h={H} rows={2} />
        {withEnergy.map((d, i) => {
          const h = Math.max(2, (d.energy_kcal! / max) * (H - 10))
          return (
            <rect
              key={d.date}
              x={i * bw + bw * 0.14}
              y={H - h}
              width={bw * 0.72}
              height={h}
              rx={3}
              fill="var(--accent)"
              // Partial days stay visible but are dimmed — the value is real,
              // just incomplete, and hiding it would read as "ate nothing".
              opacity={d.partial ? 0.35 : 0.85}
            >
              <title>{`${fmtDay(d.date)}${d.partial ? ' (partial)' : ''} — ${round(d.energy_kcal!)} kcal`}</title>
            </rect>
          )
        })}
      </svg>
      {withEnergy.some((d) => d.partial) && (
        <div className="chart-legend">
          <span className="cl" style={{ color: 'var(--muted)' }}>Dimmed bars are days still being logged</span>
        </div>
      )}
    </div>
  )
}

function ProteinPerKgChart({ periods }: { periods: NutritionPeriod[] }) {
  const withProtein = periods.filter((p) => p.protein_g_per_kg != null).slice(0, 12).reverse()
  if (withProtein.length === 0) return null

  const W = 480
  const H = 150
  const values = withProtein.map((p) => p.protein_g_per_kg!)
  // Dots on a non-zero scale, not bars: the interesting range is ~1.5-2.2 g/kg,
  // and bars (which must start at zero) would render every week the same
  // height. The target band supplies the reference a zero baseline would.
  const lo = Math.min(...values, PROTEIN_BAND.lo) - 0.25
  const hi = Math.max(...values, PROTEIN_BAND.hi) + 0.25
  const y = (v: number) => H - 8 - ((v - lo) / (hi - lo)) * (H - 26)
  const x = (i: number) => (withProtein.length === 1 ? W / 2 : 14 + (i * (W - 28)) / (withProtein.length - 1))
  const last = values[values.length - 1]

  return (
    <div className="chart-card">
      <div className="chart-head">
        <SectionLabel>Protein per kg · weekly</SectionLabel>
        <span className="mono-meta">{last.toFixed(2)} g/kg</span>
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label="Average protein intake per kilogram of bodyweight, by week">
        {/* Endurance-athlete target band, 1.6–2.0 g/kg */}
        <rect x={0} y={y(PROTEIN_BAND.hi)} width={W} height={Math.max(y(PROTEIN_BAND.lo) - y(PROTEIN_BAND.hi), 1)}
          fill="color-mix(in srgb, var(--green) 12%, transparent)" />
        <path d={`M0 ${y(PROTEIN_BAND.lo).toFixed(1)} H${W} M0 ${y(PROTEIN_BAND.hi).toFixed(1)} H${W}`}
          stroke="color-mix(in srgb, var(--green) 40%, transparent)" strokeWidth="1" strokeDasharray="3 3" fill="none" />
        <path
          d={values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join('')}
          fill="none"
          stroke="color-mix(in srgb, var(--green) 55%, transparent)"
          strokeWidth="2"
          strokeLinecap="round"
        />
        {withProtein.map((p, i) => {
          const v = p.protein_g_per_kg!
          return (
            <circle key={p.period_start} cx={x(i)} cy={y(v)} r={4.5}
              fill={v >= PROTEIN_BAND.lo ? 'var(--green)' : 'var(--steel)'}
              // 2px surface ring so overlapping dots stay countable.
              stroke="var(--card)" strokeWidth="2">
              <title>{`week of ${fmtDay(p.period_start)} — ${v.toFixed(2)} g/kg (${p.days_logged} days logged)`}</title>
            </circle>
          )
        })}
      </svg>
      <div className="chart-legend">
        <span className="cl" style={{ color: 'var(--muted)' }}>
          Shaded band = {PROTEIN_BAND.lo}–{PROTEIN_BAND.hi} g/kg, the usual range for an athlete in training
        </span>
      </div>
    </div>
  )
}

/** The numbers behind the charts — and the table view the charts need. */
function WeeklyTable({ periods }: { periods: NutritionPeriod[] }) {
  const rows = periods.filter((p) => p.days_logged > 0).slice(0, 8)
  if (rows.length === 0) return null

  return (
    <div className="chart-card" style={{ gridColumn: 'span 2' }}>
      <div className="chart-head">
        <SectionLabel>Week by week</SectionLabel>
        <span className="mono-meta">intake · body · load</span>
      </div>
      <div className="nut-table" role="table" aria-label="Weekly nutrition, body weight and training load">
        <div className="nut-row nut-head" role="row">
          <span role="columnheader">Week</span>
          <span role="columnheader">Logged</span>
          <span role="columnheader">kcal</span>
          <span role="columnheader">C / P / F</span>
          <span role="columnheader">g/kg</span>
          <span role="columnheader">Weight</span>
          <span role="columnheader">Training</span>
        </div>
        {rows.map((p) => {
          const n = p.nutrition
          const macros = MACROS.map((m) => (n[m.key] != null ? round(n[m.key]!) : '—')).join(' / ')
          const change = p.body.weight_change
          return (
            <div className="nut-row" role="row" key={p.period_start}>
              <span role="cell" className="mono-meta">{fmtDay(p.period_start)}</span>
              <span role="cell" className="mono-meta" style={{ color: p.days_logged < 4 ? 'var(--amber)' : undefined }}>
                {p.days_logged}/{p.days_in_period}
              </span>
              <span role="cell">{n.energy_kcal != null ? round(n.energy_kcal) : '—'}</span>
              <span role="cell">{macros}</span>
              <span role="cell">{p.protein_g_per_kg != null ? p.protein_g_per_kg.toFixed(2) : '—'}</span>
              <span role="cell">
                {p.body.weight_avg != null ? `${p.body.weight_avg.toFixed(1)} kg` : '—'}
                {change != null && (
                  <span style={{ color: change < 0 ? 'var(--green)' : 'var(--text-3)' }}>
                    {' '}
                    {change > 0 ? '+' : ''}
                    {change.toFixed(1)}
                  </span>
                )}
              </span>
              <span role="cell" className="mono-meta">
                {p.training.workouts > 0
                  ? `${p.training.workouts}× · ${p.training.distance_km != null ? `${p.training.distance_km.toFixed(1)} km` : '—'}`
                  : '—'}
              </span>
            </div>
          )
        })}
      </div>
      <div className="chart-legend">
        <span className="cl" style={{ color: 'var(--muted)' }}>
          Averages are per logged day; a low "Logged" count means the week is a sample, not a summary.
          Self-reported intake usually under-reports — read the trend, not the absolute total.
        </span>
      </div>
    </div>
  )
}

export function NutritionSection({
  days,
  periods,
}: {
  days: NutritionDay[]
  periods: NutritionPeriod[]
}) {
  const hasAny = days.length > 0

  return (
    <>
      <div style={{ margin: '26px 0 14px' }}>
        <SectionLabel>Nutrition</SectionLabel>
      </div>
      {!hasAny ? (
        <div className="card">
          <EmptyState icon={ForkKnife} title="No nutrition data in this range">
            Dietary energy and macros sync from HealthKit via the iOS app, written there by
            whichever food-logging app you use. Nothing has arrived for these dates yet.
          </EmptyState>
        </div>
      ) : (
        <div className="health-grid">
          <MacroChart days={days} />
          <EnergyChart days={days} />
          <ProteinPerKgChart periods={periods} />
          <WeeklyTable periods={periods} />
        </div>
      )}
    </>
  )
}

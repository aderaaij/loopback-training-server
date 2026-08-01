/**
 * Nutrition cards for the Health screen.
 *
 * Colour: carbs / protein / fat are a fixed categorical triple — assigned by
 * nutrient, never by rank, so filtering a range never repaints a macro. The
 * steps are darker than the app's --amber/--teal/--purple tokens because those
 * sit above the dark-mode lightness band; these were validated for lightness,
 * chroma, CVD separation (worst adjacent ΔE 15.9) and contrast against --card.
 * ENERGY_IN / ENERGY_OUT are a second validated pair (worst ΔE 22.6 deutan,
 * 28.4 normal) — warm/cool on purpose, so the two sides of the balance read as
 * opposites rather than as two members of one series.
 *
 * Deliberately NO dual-axis chart: intake and body weight are different scales,
 * so they get separate cards (weight already has one on this screen) rather
 * than two y-axes on one plot. Intake and expenditure ARE the same scale
 * (kcal), which is exactly why they belong on one axis in one card.
 */
import { ForkKnife } from '@phosphor-icons/react'
import { ChartTooltip, Crosshair, GridLines, TipRow, useChartHover } from './charts'
import { EmptyState, SectionLabel } from './ui'
import { fmtDay, todayKey } from '../lib/format'
import type { HealthMetricsDay, NutritionDay, NutritionPeriod } from '../lib/types'

const MACROS = [
  { key: 'carbs_g' as const, label: 'Carbs', color: '#c07f28' },
  { key: 'protein_g' as const, label: 'Protein', color: '#00a8a8' },
  { key: 'fat_g' as const, label: 'Fat', color: '#7457f0' },
]

/** The two sides of the energy balance. Warm = in, cool = out. */
const ENERGY_IN = '#cc5f2e'
const ENERGY_OUT = '#2f80cc'

/** Athlete protein target, g per kg bodyweight — the band the chart shades. */
const PROTEIN_BAND = { lo: 1.6, hi: 2.0 }

const round = (v: number, d = 0) => Number(v.toFixed(d))
const signed = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(round(v))}`

function mean(values: number[]): number | null {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null
}

function MacroChart({ days }: { days: NutritionDay[] }) {
  const withMacros = days
    .filter((d) => MACROS.some((m) => d[m.key] != null))
    .slice(-21)
  // Before the early return — the hook count must not depend on the data.
  const hover = useChartHover(withMacros.length)
  const hovered = hover.index != null ? withMacros[hover.index] : null
  if (withMacros.length === 0) return null

  const W = 1080
  const H = 190
  const GAP = 2 // surface gap between stacked segments
  const bw = W / withMacros.length
  const totals = withMacros.map((d) => MACROS.reduce((a, m) => a + (d[m.key] ?? 0), 0))
  const max = Math.max(...totals, 1)
  const avgTotal = mean(totals)

  // Half width: the balance chart above owns the full-width slot now, and the
  // macro stack survives the squeeze (21 slots at ~25px) better than the
  // protein dots beside it would.
  return (
    <div className="chart-card">
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
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
          aria-label={`Daily macronutrient grams for the last ${withMacros.length} logged days`}>
          <GridLines w={W} h={H} rows={3} />
          {withMacros.map((d, i) => {
            const x = i * bw + bw * 0.16
            const width = bw * 0.68
            const dim = hover.index != null && hover.index !== i
            let y = H
            return (
              <g key={d.date} opacity={(d.partial ? 0.45 : 1) * (dim ? 0.4 : 1)}>
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
        <ChartTooltip index={hover.index} count={withMacros.length}>
          {hovered && (
            <>
              <span className="tip-date">
                {fmtDay(hovered.date)}
                {hovered.partial && ' · partial'}
              </span>
              {MACROS.map((m) => (
                <TipRow key={m.key} color={m.color} label={m.label}
                  value={hovered[m.key] != null ? `${round(hovered[m.key]!)} g` : '—'} />
              ))}
              <TipRow label="Total"
                value={`${round(MACROS.reduce((a, m) => a + (hovered[m.key] ?? 0), 0))} g`} />
            </>
          )}
        </ChartTooltip>
      </div>
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

type EnergyRow = {
  day: NutritionDay
  intake: number
  active: number | null
  basal: number | null
  /** active + basal, or null when either is missing or the day isn't closed. */
  tdee: number | null
}

/**
 * Pair each logged day's intake against that day's expenditure.
 *
 * TDEE is active + basal and nothing else: active energy already includes
 * workout burn, so adding a session's own calories on top counts it twice.
 * A day missing basal gets no TDEE at all rather than falling back to active
 * alone — active is ~a third of the total here, so that fallback would invent
 * a ~2000 kcal deficit out of a missing column.
 *
 * Health metrics carry no `partial` flag (unlike nutrition), so a day still in
 * progress stores only the hours elapsed and reads as a genuinely low-burn day.
 * Today is therefore excluded from the expenditure side — its intake bar still
 * shows, it just gets no burn line to be measured against.
 */
function pairEnergy(days: NutritionDay[], metrics: HealthMetricsDay[]): EnergyRow[] {
  const today = todayKey()
  const byDate = new Map(metrics.map((m) => [m.date, m]))
  return days
    .filter((d) => d.energy_kcal != null)
    .map((day) => {
      const m = byDate.get(day.date)
      const active = m?.active_energy_burned ?? null
      const basal = m?.basal_energy_burned ?? null
      const closed = day.date < today
      return {
        day,
        intake: day.energy_kcal!,
        active,
        basal,
        tdee: closed && active != null && basal != null ? active + basal : null,
      }
    })
}

/**
 * Energy in against energy out, day by day — the "how much leeway did I have?"
 * chart.
 *
 * Bars are food logged, ticks are energy burned, and the shaded gap between
 * them is the balance. The gap wears the colour of whichever side is larger,
 * so direction is encoded twice (position AND hue) and neither colour has to
 * carry a verdict: for a runner a deficit is not automatically good news, so
 * green/red would editorialise a number the athlete has to interpret in
 * context.
 *
 * Degrades to a plain intake chart when nothing has a TDEE — which is the
 * state of any install whose app build predates basal-energy sync.
 */
function EnergyBalanceChart({ days, metrics }: { days: NutritionDay[]; metrics: HealthMetricsDay[] }) {
  const rows = pairEnergy(days, metrics).slice(-21)
  // Before the early return — the hook count must not depend on the data.
  const hover = useChartHover(rows.length)
  const hovered = hover.index != null ? rows[hover.index] : null
  if (rows.length === 0) return null

  const W = 1080
  const H = 200
  const bw = W / rows.length
  const max = Math.max(...rows.flatMap((r) => [r.intake, r.tdee ?? 0]), 1)
  const y = (v: number) => H - 10 - (v / max) * (H - 26)

  // Averaged over days that hold BOTH a complete intake and a complete TDEE —
  // never by differencing an intake average against a TDEE average, which
  // silently compares a 5-day mean against a 21-day one.
  const paired = rows.filter((r) => !r.day.partial && r.tdee != null)
  const avgBalance = mean(paired.map((r) => r.intake - r.tdee!))
  const hasBurn = rows.some((r) => r.tdee != null)

  return (
    <div className="chart-card" style={{ gridColumn: 'span 2' }}>
      <div className="chart-head">
        <SectionLabel>Energy in vs out · kcal per day</SectionLabel>
        <div className="hm-legend">
          <span>
            <span className="line-swatch" style={{ background: ENERGY_IN }} />
            Food logged
          </span>
          {hasBurn && (
            <span>
              <span className="line-swatch" style={{ background: ENERGY_OUT }} />
              Burned · active + resting
            </span>
          )}
          {avgBalance != null && (
            <span style={{ color: 'var(--text-3)' }}>
              {signed(avgBalance)} kcal/day over {paired.length} paired {paired.length === 1 ? 'day' : 'days'}
            </span>
          )}
        </div>
      </div>
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
          aria-label="Daily energy intake compared with energy burned, in kilocalories">
          <GridLines w={W} h={H} rows={3} />
          {/* A bullet chart, not a stacked one: the burn is the container and the
              food is how much of it got filled. Shading the in-between as its own
              block instead made the gap read as a second stacked segment, i.e. as
              something ADDED to intake rather than the room left above it. */}
          {rows.map((r, i) => {
            const ghostW = bw * 0.72
            const ghostX = i * bw + (bw - ghostW) / 2
            const barW = ghostW * 0.56
            const barX = i * bw + (bw - barW) / 2
            const base = H - 10
            const yIntake = y(r.intake)
            const yTdee = r.tdee != null ? y(r.tdee) : null
            const dim = hover.index != null && hover.index !== i
            return (
              <g key={r.day.date} opacity={(r.day.partial ? 0.45 : 1) * (dim ? 0.4 : 1)}>
                {yTdee != null && (
                  <>
                    <rect x={ghostX} y={yTdee} width={ghostW} height={base - yTdee} rx={4}
                      fill={ENERGY_OUT} opacity={0.22} />
                    {/* Crisp cap so the burn level itself stays readable, not just
                        the block's rough height. */}
                    <rect x={ghostX} y={yTdee} width={ghostW} height={3} rx={1.5} fill={ENERGY_OUT} />
                  </>
                )}
                {/* 2px surface ring so the bar separates from the block behind it. */}
                <rect x={barX} y={yIntake} width={barW} height={base - yIntake} rx={4}
                  fill={ENERGY_IN} stroke="var(--card-deep)" strokeWidth={2} />
              </g>
            )
          })}
        </svg>
        <ChartTooltip index={hover.index} count={rows.length}>
          {hovered && (
            <>
              <span className="tip-date">
                {fmtDay(hovered.day.date)}
                {hovered.day.partial && ' · still logging'}
              </span>
              <TipRow color={ENERGY_IN} label="Food logged" value={`${round(hovered.intake)} kcal`} />
              {hovered.tdee != null ? (
                <>
                  <TipRow color={ENERGY_OUT} label="Burned" value={`${round(hovered.tdee)} kcal`} />
                  <TipRow label="· active" value={`${round(hovered.active!)}`} />
                  <TipRow label="· resting" value={`${round(hovered.basal!)}`} />
                  <TipRow label="Balance" value={`${signed(hovered.intake - hovered.tdee)} kcal`} />
                </>
              ) : (
                <span className="tip-note">
                  {hovered.day.date >= todayKey()
                    ? "Today's burn is only the hours elapsed so far, so it isn't paired."
                    : hovered.basal == null
                      ? 'Resting energy never synced for this day, so there is no total to compare against.'
                      : 'No energy data for this day.'}
                </span>
              )}
            </>
          )}
        </ChartTooltip>
      </div>
      <div className="chart-legend">
        <span className="cl" style={{ color: 'var(--muted)' }}>
          {hasBurn ? (
            <>
              Self-reported intake under-reports and resting burn is an estimate, and both errors push
              the gap the same way — read the direction, not the number. Today is left out: its burn is
              only the hours elapsed so far.
            </>
          ) : (
            <>
              Showing intake only — resting energy hasn't synced for these days, and active energy alone
              is about a third of the real total, so pairing against it would invent a deficit.
            </>
          )}
          {rows.some((r) => r.day.partial) && ' Dimmed days were still being logged.'}
        </span>
      </div>
    </div>
  )
}

function ProteinPerKgChart({ periods }: { periods: NutritionPeriod[] }) {
  const withProtein = periods.filter((p) => p.protein_g_per_kg != null).slice(0, 12).reverse()
  // Before the early return — the hook count must not depend on the data.
  const hover = useChartHover(withProtein.length, 'point')
  const hovered = hover.index != null ? withProtein[hover.index] : null
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
      <div className="chart-hover" {...hover.bind}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img"
          aria-label="Average protein intake per kilogram of bodyweight, by week">
          {/* Endurance-athlete target band, 1.6–2.0 g/kg */}
          <rect x={0} y={y(PROTEIN_BAND.hi)} width={W} height={Math.max(y(PROTEIN_BAND.lo) - y(PROTEIN_BAND.hi), 1)}
            fill="color-mix(in srgb, var(--green) 12%, transparent)" />
          <path d={`M0 ${y(PROTEIN_BAND.lo).toFixed(1)} H${W} M0 ${y(PROTEIN_BAND.hi).toFixed(1)} H${W}`}
            stroke="color-mix(in srgb, var(--green) 40%, transparent)" strokeWidth="1" strokeDasharray="3 3" fill="none" />
          {hover.index != null && <Crosshair x={x(hover.index)} h={H} />}
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
              <circle key={p.period_start} cx={x(i)} cy={y(v)} r={hover.index === i ? 6 : 4.5}
                fill={v >= PROTEIN_BAND.lo ? 'var(--green)' : 'var(--steel)'}
                // 2px surface ring so overlapping dots stay countable.
                stroke="var(--card-deep)" strokeWidth="2" />
            )
          })}
        </svg>
        <ChartTooltip index={hover.index} count={withProtein.length} mode="point">
          {hovered && (
            <>
              <span className="tip-date">week of {fmtDay(hovered.period_start)}</span>
              <TipRow color={hovered.protein_g_per_kg! >= PROTEIN_BAND.lo ? 'var(--green)' : 'var(--steel)'}
                label="Protein" value={`${hovered.protein_g_per_kg!.toFixed(2)} g/kg`} />
              {hovered.nutrition.protein_g != null && (
                <TipRow label="· per day" value={`${round(hovered.nutrition.protein_g)} g`} />
              )}
              {hovered.body.weight_avg != null && (
                <TipRow label="· weight" value={`${hovered.body.weight_avg.toFixed(1)} kg`} />
              )}
              <span className="tip-note">
                {hovered.days_logged} of {hovered.days_in_period} days logged
                {hovered.days_logged < 4 && ' — a sample, not a summary'}
              </span>
            </>
          )}
        </ChartTooltip>
      </div>
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
        <span className="mono-meta">intake · burn · body · load</span>
      </div>
      <div className="nut-table" role="table" aria-label="Weekly nutrition, energy balance, body weight and training load">
        <div className="nut-row nut-head" role="row">
          <span role="columnheader">Week</span>
          <span role="columnheader">Logged</span>
          <span role="columnheader">In</span>
          <span role="columnheader">Out</span>
          <span role="columnheader">Balance</span>
          <span role="columnheader">C / P / F</span>
          <span role="columnheader">g/kg</span>
          <span role="columnheader">Weight</span>
          <span role="columnheader">Training</span>
        </div>
        {rows.map((p) => {
          const n = p.nutrition
          const macros = MACROS.map((m) => (n[m.key] != null ? round(n[m.key]!) : '—')).join(' / ')
          const change = p.body.weight_change
          const exp = p.expenditure
          return (
            <div className="nut-row" role="row" key={p.period_start}>
              <span role="cell" className="mono-meta">{fmtDay(p.period_start)}</span>
              <span role="cell" className="mono-meta" style={{ color: p.days_logged < 4 ? 'var(--amber)' : undefined }}>
                {p.days_logged}/{p.days_in_period}
              </span>
              <span role="cell">{n.energy_kcal != null ? round(n.energy_kcal) : '—'}</span>
              <span role="cell" title={
                exp.tdee_kcal_avg != null
                  ? `${round(exp.active_kcal_avg ?? 0)} active + ${round(exp.basal_kcal_avg ?? 0)} resting, over ${exp.days_with_tdee} days`
                  : 'No day this week has both active and resting energy'
              }>
                {exp.tdee_kcal_avg != null ? round(exp.tdee_kcal_avg) : '—'}
              </span>
              {/* Averaged over paired days only, so it is not `In − Out` of the
                  two cells beside it whenever those cover different day sets —
                  the day count says how many days actually back it. */}
              <span role="cell" className="mono-meta" title={
                exp.days_with_balance > 0
                  ? `Averaged over the ${exp.days_with_balance} day(s) with both a complete intake and a complete burn`
                  : 'No day this week has both a complete intake and a complete burn'
              }>
                {exp.balance_kcal_avg != null ? (
                  <>
                    {signed(exp.balance_kcal_avg)}
                    <span style={{ color: 'var(--faint)' }}> ·{exp.days_with_balance}d</span>
                  </>
                ) : (
                  '—'
                )}
              </span>
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
          "Out" is active + resting energy, which already includes workout burn.
        </span>
      </div>
    </div>
  )
}

export function NutritionSection({
  days,
  periods,
  metrics,
}: {
  days: NutritionDay[]
  periods: NutritionPeriod[]
  metrics: HealthMetricsDay[]
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
          <EnergyBalanceChart days={days} metrics={metrics} />
          <MacroChart days={days} />
          <ProteinPerKgChart periods={periods} />
          <WeeklyTable periods={periods} />
        </div>
      )}
    </>
  )
}

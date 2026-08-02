import { Check, Info, Warning } from '@phosphor-icons/react'
import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { usePageHeader } from '../components/PageHeader'
import { FinishBanner } from '../components/PlanCelebration'
import { ConflictPill, ErrorNote, Loading, SectionLabel, StatusPill } from '../components/ui'
import { activityMeta } from '../lib/activity'
import { fmtDay, fmtDayYear, fmtDowDayTime, todayKey } from '../lib/format'
import { usePlan, usePlanSchedule, usePlanValidation, usePlanWorkouts } from '../lib/queries'
import type { Plan, PlanPhase, ValidationWarning } from '../lib/types'
import '../styles/plans.css'
import '../styles/screens.css'

const KNOWN_KEYS = new Set(['goals', 'guardrails', 'phases', 'athlete_context', 'background', 'schedule'])
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

const GOAL_KEYS = new Set(['type', 'target', 'unit', 'by_week', 'description', 'detail', 'note'])

/**
 * Goals/guardrails are LLM-authored with an open schema — usually strings or
 * {type, target?, unit?, by_week?, detail?|description?} objects. Compose a
 * readable line from the known keys ("Weekly volume: 20 km by week 4") and
 * never let an object hit String() ("[object Object]").
 */
function fmtGoal(g: unknown): string {
  if (typeof g === 'string') return g
  if (typeof g !== 'object' || g == null) return String(g)
  const o = g as Record<string, unknown>

  const bits: string[] = []
  const target =
    o.target !== undefined ? String(o.target) + (typeof o.unit === 'string' ? ` ${o.unit}` : '') : null
  const numeric = [target, o.by_week !== undefined ? `by week ${String(o.by_week)}` : null]
    .filter(Boolean)
    .join(' ')
  if (numeric) bits.push(numeric)
  for (const key of ['description', 'detail', 'note']) {
    if (typeof o[key] === 'string') bits.push(o[key] as string)
  }
  // Unknown keys still show up rather than getting silently dropped.
  for (const [key, value] of Object.entries(o)) {
    if (!GOAL_KEYS.has(key)) bits.push(`${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
  }

  const type = typeof o.type === 'string' ? o.type.replace(/_/g, ' ') : null
  const title = type ? type.charAt(0).toUpperCase() + type.slice(1) : null
  if (title && bits.length > 0) return `${title}: ${bits.join(' · ')}`
  if (title) return title
  if (bits.length > 0) return bits.join(' · ')
  return JSON.stringify(g)
}

function phaseWeekLabel(phase: PlanPhase, index: number): string {
  if (phase.weeks != null) return typeof phase.weeks === 'number' ? `W${phase.weeks}` : String(phase.weeks)
  return `W${index + 1}`
}

function ratioColor(ratio: number | null): string {
  if (ratio == null) return 'var(--muted)'
  if (ratio > 1.5) return 'var(--red)'
  if (ratio > 1.3) return 'var(--amber)'
  return 'var(--muted)'
}

function WarningIcon({ severity }: { severity: ValidationWarning['severity'] }) {
  const style = { flexShrink: 0, marginTop: 1 } as const
  if (severity === 'info') return <Info size={16} color="var(--muted)" style={style} />
  return (
    <Warning size={16} weight="fill" color={severity === 'critical' ? 'var(--red)' : 'var(--amber)'} style={style} />
  )
}

/** Which phase is current, assuming phases split the plan window evenly. */
function currentPhaseIndex(plan: Plan, phaseCount: number): number {
  if (phaseCount === 0) return -1
  if (plan.status !== 'active') return -1
  const start = new Date(plan.start_date).getTime()
  const end = plan.end_date ? new Date(plan.end_date).getTime() : null
  if (!end || end <= start) return -1
  const frac = (Date.now() - start) / (end - start)
  if (frac < 0 || frac > 1) return -1
  return Math.min(phaseCount - 1, Math.floor(frac * phaseCount))
}

export function PlanDetail() {
  const { id } = useParams()
  const { data: plan, isLoading, error } = usePlan(id)
  const { data: schedule } = usePlanSchedule(id)
  const { data: planWorkouts } = usePlanWorkouts(id)
  // Upcoming blocks get the schedule check too — reviewing a block before it
  // starts is when the warnings are actually actionable.
  const { data: validation } = usePlanValidation(
    id,
    plan?.status === 'active' || plan?.status === 'upcoming',
  )

  usePageHeader(
    plan?.name ?? 'Plan',
    plan
      ? `${activityMeta(plan.activity_type).label} · ${fmtDayYear(plan.start_date)} — ${
          plan.end_date ? fmtDayYear(plan.end_date) : 'open'
        } · ${plan.status}`
      : undefined,
    '/plans',
  )

  const unknownEntries = useMemo(() => {
    if (!plan) return []
    return Object.entries(plan.metadata ?? {}).filter(([k]) => !KNOWN_KEYS.has(k))
  }, [plan])

  if (isLoading) return <Loading label="Loading plan…" />
  if (error) return <ErrorNote error={error} />
  if (!plan) return null

  const md = plan.metadata ?? {}
  const phases = Array.isArray(md.phases) ? md.phases : []
  const goals = Array.isArray(md.goals) ? md.goals : []
  // Guardrails come in two LLM-authored shapes: legacy array of goal-like
  // entries, or the validator-readable dict ({max_weekly_km: 30}).
  const guardrails: unknown[] = Array.isArray(md.guardrails)
    ? md.guardrails
    : md.guardrails && typeof md.guardrails === 'object'
      ? Object.entries(md.guardrails).map(
          ([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'string' || typeof v === 'number' ? v : JSON.stringify(v)}`,
        )
      : []
  const curPhase = currentPhaseIndex(plan, phases.length)
  const weekSchedule = schedule?.schedule
  const upcomingSessions = (schedule?.sessions ?? []).filter((s) => s.date >= todayKey()).slice(0, 5)

  return (
    <div className="screen">
      <FinishBanner plan={plan} />
      {plan.description && (
        <div className="prose-card" style={{ marginBottom: 18 }}>
          <div className="prose">{plan.description}</div>
        </div>
      )}

      {phases.length > 0 && (
        <div className="phases-card">
          <div style={{ marginBottom: 18 }}>
            <SectionLabel>Phases</SectionLabel>
          </div>
          <div className="phases-track">
            {phases.map((ph, i) => (
              <div className={`phase-cell${i === curPhase ? ' current' : ''}`} key={i}>
                <div className="ph-wk">{phaseWeekLabel(ph, i)}</div>
                <div className="ph-name">{String(ph.name ?? `Phase ${i + 1}`)}</div>
                {typeof ph.focus === 'string' && (
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5, lineHeight: 1.4 }}>{ph.focus}</div>
                )}
                {i === curPhase && (
                  <div className="ph-current">
                    <span className="dot" />
                    CURRENT
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {(goals.length > 0 || guardrails.length > 0) && (
        <div className="plan-two">
          {goals.length > 0 && (
            <div className="card" style={{ padding: 20 }}>
              <div style={{ marginBottom: 14 }}>
                <SectionLabel>Goals</SectionLabel>
              </div>
              {goals.map((g, i) => (
                <div className="goal-row" key={i}>
                  <span className="g-check">
                    <Check size={12} weight="bold" />
                  </span>
                  <span className="g-text">{fmtGoal(g)}</span>
                </div>
              ))}
            </div>
          )}
          {guardrails.length > 0 && (
            <div className="card" style={{ padding: 20 }}>
              <div style={{ marginBottom: 14 }}>
                <SectionLabel>Guardrails</SectionLabel>
              </div>
              {guardrails.map((g, i) => (
                <div className="guardrail-row" key={i}>
                  <Warning size={16} weight="fill" color="var(--amber)" style={{ flexShrink: 0, marginTop: 1 }} />
                  <span className="g-text">{fmtGoal(g)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {(plan.status === 'active' || plan.status === 'upcoming') && validation && (validation.warnings.length > 0 || validation.weeks.length > 0) && (
        <div className="card" style={{ padding: 20, marginBottom: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
            <SectionLabel>Schedule check</SectionLabel>
            {validation.warnings.length === 0 ? (
              <span className="mono-meta" style={{ color: 'var(--green)', display: 'flex', alignItems: 'center', gap: 5 }}>
                <Check size={12} weight="bold" /> sound
              </span>
            ) : (
              <span className="mono-meta">
                {(() => {
                  const crit = validation.warnings.filter((w) => w.severity === 'critical').length
                  return crit > 0
                    ? `${crit} critical · ${validation.warnings.length} total`
                    : `${validation.warnings.length} finding${validation.warnings.length === 1 ? '' : 's'}`
                })()}
              </span>
            )}
          </div>

          {validation.warnings.map((w, i) => (
            <div className="guardrail-row" key={i}>
              <WarningIcon severity={w.severity} />
              <span className="g-text">
                {w.message}
                {w.estimated && <span style={{ color: 'var(--muted)' }}> · pace-estimated</span>}
              </span>
            </div>
          ))}

          {validation.weeks.length > 0 && (
            <div style={{ marginTop: validation.warnings.length > 0 ? 14 : 0 }}>
              <div className="mono-label" style={{ marginBottom: 8 }}>
                Upcoming weeks
              </div>
              {validation.weeks.map((wk) => (
                <div
                  key={wk.week_start}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderTop: '1px solid var(--row-line)' }}
                >
                  <span className="mono-meta" style={{ width: 84, flexShrink: 0 }}>
                    wk {fmtDay(wk.week_start)}
                  </span>
                  <span style={{ flex: 1, fontSize: 13, minWidth: 0 }}>
                    <strong>{wk.planned_km} km</strong> planned
                    {wk.actual_km > 0 ? ` (+${wk.actual_km} done)` : ''}
                    {wk.hard_days > 0 ? ` · ${wk.hard_days} hard` : ''}
                    {wk.longest_km > 0 ? ` · long ${wk.longest_km} km` : ''}
                    {wk.estimated ? ' ≈' : ''}
                  </span>
                  <span className="mono-meta" style={{ color: ratioColor(wk.ratio), flexShrink: 0 }}>
                    {wk.ratio != null ? `${wk.ratio.toFixed(2)}× base` : 'no baseline'}
                  </span>
                </div>
              ))}
              <div className="mono-meta" style={{ marginTop: 10, fontSize: 10 }}>
                Deterministic checks vs your last 4 weeks of training · ≈ volumes rest on a pace estimate
              </div>
            </div>
          )}
        </div>
      )}

      {weekSchedule && (
        <div className="phases-card">
          <div className="chart-head" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
            <SectionLabel>Weekly schedule</SectionLabel>
            <span className="mono-meta">
              {weekSchedule.weeks} wk from {fmtDay(weekSchedule.startDate)}
              {weekSchedule.time ? ` · ${weekSchedule.time}` : ''}
            </span>
          </div>
          <div className="week-sched">
            {WEEKDAYS.map((d) => {
              const slot = weekSchedule.days[d]
              const meta = activityMeta(plan.activity_type === 'running' && slot ? 'strength' : plan.activity_type)
              return (
                <div className={`ws-day${slot ? '' : ' off'}`} key={d}>
                  <div className="ws-dow">{d}</div>
                  {slot && (
                    <div className="ws-body">
                      <meta.icon size={18} color={meta.color} />
                      <div className="ws-title">{slot.title}</div>
                      {slot.routineId && (
                        <div className="mono-meta" style={{ fontSize: 9, marginTop: 3 }}>
                          Hevy routine
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          {(schedule?.warnings.length ?? 0) > 0 && (
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {schedule!.warnings.map((w, i) => (
                <div className="guardrail-row" key={i} style={{ marginBottom: 0 }}>
                  <Warning size={16} weight="fill" color="var(--amber)" style={{ flexShrink: 0, marginTop: 1 }} />
                  <span className="g-text">{w}</span>
                </div>
              ))}
            </div>
          )}
          {upcomingSessions.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="mono-label" style={{ marginBottom: 8 }}>
                Next sessions
              </div>
              {upcomingSessions.map((s) => (
                <div
                  key={s.date + s.title}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderTop: '1px solid var(--row-line)' }}
                >
                  <span className="mono-meta" style={{ width: 110, flexShrink: 0 }}>
                    {fmtDowDayTime(s.date)}
                  </span>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{s.title}</span>
                  {s.conflict && <ConflictPill />}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {(typeof md.athlete_context === 'string' || typeof md.background === 'string' || unknownEntries.length > 0) && (
        <div className="prose-card">
          {typeof md.athlete_context === 'string' && (
            <>
              <div style={{ marginBottom: 12 }}>
                <SectionLabel>Athlete context</SectionLabel>
              </div>
              <div className="prose">{md.athlete_context}</div>
            </>
          )}
          {typeof md.background === 'string' && (
            <div style={{ marginTop: typeof md.athlete_context === 'string' ? 18 : 0 }}>
              <div style={{ marginBottom: 12 }}>
                <SectionLabel>Background</SectionLabel>
              </div>
              <div className="prose">{md.background}</div>
            </div>
          )}
          {unknownEntries.map(([key, value]) => (
            <div className="unknown-key" key={key}>
              <div className="uk-label">
                metadata.{key} <span style={{ color: 'var(--muted)' }}>· unrecognised key</span>
              </div>
              <div className="uk-value">{JSON.stringify(value, null, 2)}</div>
            </div>
          ))}
        </div>
      )}

      {(planWorkouts?.length ?? 0) > 0 && (
        <div className="card" style={{ overflow: 'hidden' }}>
          <div className="card-head">
            <SectionLabel>Queued sessions from this plan</SectionLabel>
            <span className="mono-meta">{planWorkouts!.length}</span>
          </div>
          {planWorkouts!.slice(0, 10).map((q) => (
            <div className="row-item" key={q.id} style={{ cursor: 'default' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row-title" style={{ fontSize: 14 }}>
                  {q.title}
                </div>
                <div className="row-meta">{q.scheduled_date ? fmtDowDayTime(q.scheduled_date) : 'unscheduled'}</div>
              </div>
              <StatusPill status={q.status} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

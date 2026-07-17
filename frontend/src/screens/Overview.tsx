import {
  Brain,
  CaretRight,
  Heartbeat,
  Moon,
  PersonSimpleRun,
  Pulse,
  Scales,
  WarningCircle,
  Watch,
} from '@phosphor-icons/react'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePageHeader } from '../components/PageHeader'
import { ConflictPill, IconTile, SectionLabel, StatusPill } from '../components/ui'
import { activityMeta, effortColor } from '../lib/activity'
import { useAuth } from '../lib/auth'
import {
  fmtDay,
  fmtDowDayTime,
  fmtDuration,
  fmtHoursMinutes,
  fmtKm,
  paceOf,
  fmtPace,
  toDateKey,
  addDays,
  todayKey,
} from '../lib/format'
import {
  useFeedback,
  useHealthMetrics,
  useNoteContext,
  usePlans,
  useQueue,
  useUpcoming,
  useWorkouts,
} from '../lib/queries'
import type { CalendarEntry, HealthMetricsDay } from '../lib/types'
import '../styles/screens.css'

function latest<T>(days: HealthMetricsDay[] | undefined, pick: (d: HealthMetricsDay) => T | null): { value: T; date: string } | null {
  if (!days) return null
  for (const d of days) {
    const v = pick(d)
    if (v != null) return { value: v, date: d.date }
  }
  return null
}

function HealthTiles() {
  const start = toDateKey(addDays(new Date(), -14))
  const { data, isSuccess } = useHealthMetrics(start)

  const sleep = latest(data, (d) => d.sleep_duration)
  const rhr = latest(data, (d) => d.resting_heart_rate)
  const hrv = latest(data, (d) => d.hrv_sdnn)
  const weight = latest(data, (d) => d.weight)

  const dayLabel = (iso: string | undefined) => {
    if (!iso) return isSuccess ? 'no recent data' : '…'
    if (iso === todayKey()) return 'today'
    if (iso === toDateKey(addDays(new Date(), -1))) return 'yesterday'
    return fmtDay(iso)
  }

  const tiles = [
    {
      icon: Moon,
      color: 'var(--blue)',
      label: 'Sleep',
      value: sleep ? fmtHoursMinutes(sleep.value) : '—',
      unit: '',
      sub: sleep && sleep.date === todayKey() ? 'last night' : dayLabel(sleep?.date),
    },
    {
      icon: Heartbeat,
      color: 'var(--orange)',
      label: 'Resting HR',
      value: rhr ? String(Math.round(rhr.value)) : '—',
      unit: 'bpm',
      sub: dayLabel(rhr?.date),
    },
    {
      icon: Pulse,
      color: 'var(--green)',
      label: 'HRV',
      value: hrv ? String(Math.round(hrv.value)) : '—',
      unit: 'ms',
      sub: dayLabel(hrv?.date),
    },
    {
      icon: Scales,
      color: 'var(--text)',
      label: 'Weight',
      value: weight ? weight.value.toFixed(1) : '—',
      unit: 'kg',
      sub: dayLabel(weight?.date),
    },
  ]

  return (
    <div className="tile-grid">
      {tiles.map((t) => (
        <div className="stat-tile" key={t.label}>
          <div className="tile-head" style={{ color: t.color }}>
            <t.icon size={16} />
            <span className="tile-label">{t.label}</span>
          </div>
          <div className="tile-value">
            {t.value}
            {t.unit && <span className="tile-unit"> {t.unit}</span>}
          </div>
          <div className="tile-sub">{t.sub}</div>
        </div>
      ))}
    </div>
  )
}

function NextUp() {
  const navigate = useNavigate()
  const { data, isSuccess } = useUpcoming()

  const upcoming = useMemo(() => {
    const today = todayKey()
    return (data?.entries ?? [])
      .filter((e) => e.date >= today && !e.completed && e.status !== 'completed')
      .slice(0, 3)
  }, [data])

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div className="card-head">
        <SectionLabel>Next up</SectionLabel>
        <button className="card-link" onClick={() => navigate('/calendar')}>
          Calendar →
        </button>
      </div>
      {isSuccess && upcoming.length === 0 && (
        <div style={{ padding: '6px 20px 20px', fontSize: 13, color: 'var(--muted)' }}>
          Nothing scheduled in the next 4 weeks — ask your coach to queue a session.
        </div>
      )}
      {upcoming.map((e: CalendarEntry, i) => {
        const meta = activityMeta(e.kind === 'strength' ? 'strength' : e.activityType)
        return (
          <button className="row-item" key={`${e.date}-${e.title}-${i}`} onClick={() => navigate('/calendar')}>
            <IconTile icon={meta.icon} color={meta.color} />
            <div style={{ flex: 1, minWidth: 0, textAlign: 'left' }}>
              <div className="row-title">{e.title}</div>
              <div className="row-meta">
                {fmtDowDayTime(e.date)}
                {e.planName ? ` · ${e.planName}` : ''}
              </div>
            </div>
            {e.conflict && <ConflictPill />}
            <StatusPill status={e.status ?? (e.kind === 'strength' ? 'planned' : null)} />
          </button>
        )
      })}
    </div>
  )
}

function RecentWorkouts() {
  const navigate = useNavigate()
  const { data, isSuccess } = useWorkouts({ limit: 5 })

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div className="card-head">
        <SectionLabel>Recent workouts</SectionLabel>
        <button className="card-link" onClick={() => navigate('/workouts')}>
          All →
        </button>
      </div>
      {isSuccess && data.length === 0 && (
        <div style={{ padding: '6px 20px 20px', fontSize: 13, color: 'var(--muted)' }}>
          No workouts yet. Install the iOS app and log in — synced sessions land here.
        </div>
      )}
      {(data ?? []).map((w) => {
        const meta = activityMeta(w.activity_type)
        const pace = w.activity_type === 'running' ? paceOf(w.duration, w.total_distance) : null
        const parts = [
          fmtDay(w.start_date),
          w.total_distance ? fmtKm(w.total_distance) : fmtDuration(w.duration),
          pace ? `${fmtPace(pace)}/km` : null,
        ].filter(Boolean)
        return (
          <button className="row-item" key={w.id} onClick={() => navigate(`/workouts/${w.id}`)}>
            <IconTile icon={meta.icon} color={meta.color} size={38} iconSize={20} />
            <div style={{ flex: 1, minWidth: 0, textAlign: 'left' }}>
              <div className="row-title" style={{ fontSize: 14.5 }}>
                {meta.label}
              </div>
              <div className="row-meta">{parts.join(' · ')}</div>
            </div>
            <div style={{ textAlign: 'right', flexShrink: 0 }}>
              <div
                className="display"
                style={{ fontSize: 17, fontWeight: 600, color: effortColor(w.effort_score) }}
              >
                {w.effort_score != null ? Math.round(w.effort_score) : '—'}
              </div>
              <div style={{ fontSize: 9, color: 'var(--faint)', letterSpacing: 0.5 }}>EFFORT</div>
            </div>
          </button>
        )
      })}
    </div>
  )
}

function ActivePlanCard() {
  const navigate = useNavigate()
  const { data: plans, isSuccess } = usePlans('active')
  const plan = plans?.[0]

  if (!plan) {
    return (
      <div className="card" style={{ padding: 20 }}>
        <SectionLabel>Active plan</SectionLabel>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 10, lineHeight: 1.5 }}>
          {isSuccess ? 'No active plan. Your LLM coach creates one from a conversation.' : '…'}
        </div>
      </div>
    )
  }

  // progress through startDate → endDate
  const start = new Date(plan.start_date).getTime()
  const end = plan.end_date ? new Date(plan.end_date).getTime() : null
  const now = Date.now()
  const totalWeeks = end ? Math.max(1, Math.round((end - start) / (7 * 86400_000))) : null
  const week = Math.max(1, Math.floor((now - start) / (7 * 86400_000)) + 1)
  const frac = end ? Math.min(1, Math.max(0, (now - start) / (end - start))) : 0

  const phases = plan.metadata.phases
  const currentPhase =
    Array.isArray(phases) && phases.length > 0 && totalWeeks
      ? phases[Math.min(phases.length - 1, Math.floor(frac * phases.length))]
      : null

  const SEGS = 12
  const done = Math.floor(frac * SEGS)

  return (
    <button className="plan-hero" onClick={() => navigate(`/plans/${plan.id}`)}>
      <span className="hero-glow" />
      <div style={{ position: 'relative', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', letterSpacing: 0.4, textTransform: 'uppercase' }}>
            Active plan
          </div>
          <div className="display" style={{ fontSize: 20, fontWeight: 600, marginTop: 6, letterSpacing: -0.3 }}>
            {plan.name}
          </div>
        </div>
        {totalWeeks && (
          <span className="mono-meta">
            W{Math.min(week, totalWeeks)}/{totalWeeks}
          </span>
        )}
      </div>
      <div className="seg-track">
        {Array.from({ length: SEGS }, (_, i) => (
          <span
            key={i}
            style={{
              background: i < done ? 'var(--green)' : i === done ? 'var(--accent)' : '#2A2520',
              boxShadow: i === done ? '0 0 10px color-mix(in srgb, var(--accent) 60%, transparent)' : 'none',
            }}
          />
        ))}
      </div>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 8 }}>
        <PersonSimpleRun size={15} weight="bold" color="var(--accent)" />
        {currentPhase?.name ? (
          <>
            <span style={{ fontSize: 13, color: 'var(--muted)' }}>Current phase ·</span>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{String(currentPhase.name)}</span>
          </>
        ) : (
          <span style={{ fontSize: 13, color: 'var(--muted)' }}>
            {plan.end_date ? `Ends ${fmtDay(plan.end_date)}` : 'Open-ended'}
          </span>
        )}
      </div>
    </button>
  )
}

function Attention() {
  const navigate = useNavigate()
  const { data: pending } = useQueue('pending')
  const { data: feedback } = useFeedback()

  const pendingCount = pending?.length ?? 0
  const unacked = (feedback ?? []).filter((f) => !f.acknowledgedAt && !f.dismissed)

  const items: { icon: typeof Watch; color: string; title: string; meta: string }[] = []
  if (pendingCount > 0) {
    items.push({
      icon: Watch,
      color: 'var(--blue)',
      title: `${pendingCount} watch item${pendingCount === 1 ? '' : 's'} pending sync`,
      meta: 'Waiting for the iPhone to fetch them',
    })
  }
  if (unacked.length > 0) {
    items.push({
      icon: WarningCircle,
      color: 'var(--amber)',
      title: `${unacked.length} missed workout${unacked.length === 1 ? ' needs' : 's need'} review`,
      meta: unacked[0].workoutName,
    })
  }

  if (items.length === 0) return null

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div style={{ padding: '17px 20px 13px' }}>
        <SectionLabel>Needs attention</SectionLabel>
      </div>
      {items.map((a) => (
        <button className="row-item" key={a.title} onClick={() => navigate('/queue')}>
          <a.icon size={26} weight="fill" color={a.color} style={{ flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0, textAlign: 'left' }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{a.title}</div>
            <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>{a.meta}</div>
          </div>
          <CaretRight size={15} color="var(--faint)" />
        </button>
      ))}
    </div>
  )
}

function CoachTeaser() {
  const navigate = useNavigate()
  const { data } = useNoteContext()
  const count = data?.notes.length ?? 0

  return (
    <button className="coach-teaser" onClick={() => navigate('/notes')}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <Brain size={19} weight="bold" color="var(--accent)" />
        <span style={{ fontSize: 13, fontWeight: 700 }}>What your coach knows</span>
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text-3)', lineHeight: 1.5, marginTop: 9, textAlign: 'left' }}>
        {data
          ? `${count} active note${count === 1 ? '' : 's'} · ${data.continuity_hint} Inspect exactly what the LLM sees →`
          : 'Inspect exactly what the LLM sees →'}
      </div>
    </button>
  )
}

export function Overview() {
  const { user } = useAuth()
  const now = new Date()
  const dows = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const subtitle = `${dows[now.getDay()]} ${now.getDate()} ${months[now.getMonth()]} ${now.getFullYear()}`

  usePageHeader(`Hey ${user?.displayName?.split(' ')[0] || 'there'}`, subtitle)

  return (
    <div className="screen">
      <HealthTiles />
      <div className="two-col">
        <div className="col-stack">
          <NextUp />
          <RecentWorkouts />
        </div>
        <div className="col-stack">
          <ActivePlanCard />
          <Attention />
          <CoachTeaser />
        </div>
      </div>
    </div>
  )
}

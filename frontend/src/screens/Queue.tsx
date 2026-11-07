import { CheckCircle, Trash, Watch, WarningCircle } from '@phosphor-icons/react'
import { useMemo, useState } from 'react'
import { usePageHeader } from '../components/PageHeader'
import {
  ConfirmDialog,
  EmptyState,
  ErrorNote,
  IconTile,
  Loading,
  SectionLabel,
  StatusPill,
} from '../components/ui'
import { activityMeta } from '../lib/activity'
import { distanceShortUnit, distanceValue, fmtDay, fmtDowDayTime, fmtDuration, goalMeters } from '../lib/format'
import {
  useAcknowledgeFeedback,
  useDeleteQueueItem,
  useFeedback,
  usePlans,
  useQueue,
} from '../lib/queries'
import { type Units, useUnits } from '../lib/units'
import type { CompositionStep, QueueItem, WorkoutComposition } from '../lib/types'
import '../styles/queue.css'

const REASON_LABELS: Record<string, string> = {
  busy: 'Too busy',
  tired: 'Tired',
  weather: 'Weather',
  soreness: 'Soreness',
  motivation: 'Motivation',
  other: 'Other',
}

function stepsOf(comp: WorkoutComposition, units: Units): { label: string; flex: number }[] {
  const out: { label: string; flex: number }[] = []
  const secondsOf = (s: CompositionStep | undefined) => {
    const g = s?.goal
    if (!g?.value) return 60
    if (g.type === 'time') return g.unit === 'minutes' ? g.value * 60 : g.value
    return 300 // distance goals get a nominal width
  }
  const nameOf = (s: CompositionStep | undefined, fallback: string) => {
    const p = s?.purpose
    if (!p) return fallback
    return p.charAt(0).toUpperCase() + p.slice(1)
  }
  const labelWithGoal = (s: CompositionStep | undefined, fallback: string) => {
    const g = s?.goal
    const name = nameOf(s, fallback)
    if (g?.type === 'time' && g.value) {
      return `${name} ${fmtDuration(g.unit === 'minutes' ? g.value * 60 : g.value)}`
    }
    if (g?.type === 'distance' && g.value) {
      const dist = distanceValue(goalMeters(g.value, g.unit), units)
      return `${name} ${dist.toFixed(dist < 10 ? 1 : 0)}${distanceShortUnit(units)}`
    }
    return name
  }
  if (comp.warmup) out.push({ label: labelWithGoal(comp.warmup, 'Warm-up'), flex: secondsOf(comp.warmup) })
  for (const b of comp.blocks ?? []) {
    for (const s of b.steps ?? []) {
      const iter = b.iterations ?? 1
      out.push({
        label: `${iter > 1 ? `${iter}× ` : ''}${labelWithGoal(s, 'Work')}`,
        flex: secondsOf(s) * iter,
      })
    }
  }
  if (comp.cooldown) out.push({ label: labelWithGoal(comp.cooldown, 'Cooldown'), flex: secondsOf(comp.cooldown) })
  return out
}

export function Queue() {
  const units = useUnits()
  const { data: queue, isLoading, error } = useQueue(undefined, 200)
  const { data: feedback } = useFeedback()
  const { data: plans } = usePlans()
  const ack = useAcknowledgeFeedback()
  const del = useDeleteQueueItem()
  const [deleting, setDeleting] = useState<QueueItem | null>(null)

  const planName = useMemo(() => {
    const map = new Map<string, string>()
    for (const p of plans ?? []) map.set(p.id, p.name)
    return map
  }, [plans])

  const pendingCount = (queue ?? []).filter((q) => q.status === 'pending').length
  usePageHeader(
    'Watch queue',
    queue ? `${queue.length} items · ${pendingCount} pending · ${feedback?.length ?? 0} feedback` : undefined,
  )

  return (
    <div className="screen">
      <div className="queue-grid">
        <div>
          <div style={{ marginBottom: 13 }}>
            <SectionLabel>Watch queue</SectionLabel>
          </div>

          {error && <ErrorNote error={error} />}
          {isLoading && <Loading label="Loading queue…" />}

          {!isLoading && (queue ?? []).length === 0 && !error && (
            <div className="card">
              <EmptyState icon={Watch} title="Queue is empty">
                Your LLM coach queues structured workouts here; the iOS app syncs them to the
                Apple Watch. Nothing is waiting right now.
              </EmptyState>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {(queue ?? []).map((q) => {
              const meta = activityMeta(q.activity_type)
              const steps = q.workout_data ? stepsOf(q.workout_data, units) : []
              const metaParts = [
                q.scheduled_date ? fmtDowDayTime(q.scheduled_date) : 'unscheduled',
                q.plan_id ? planName.get(q.plan_id) : null,
              ].filter(Boolean)
              return (
                <div className="queue-card" key={q.id}>
                  <div className="q-top">
                    <IconTile icon={meta.icon} color={meta.color} size={40} iconSize={20} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="q-title">{q.title}</div>
                      <div className="q-meta">{metaParts.join(' · ')}</div>
                    </div>
                    <StatusPill status={q.status} />
                    <button className="q-del" title="Delete queue item" onClick={() => setDeleting(q)}>
                      <Trash size={16} />
                    </button>
                  </div>
                  {steps.length > 0 && (
                    <div className="q-steps">
                      {steps.slice(0, 6).map((s, i) => (
                        <div className="q-step" key={i} style={{ flex: s.flex }}>
                          <div className="st-label">{s.label}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        <div>
          <div style={{ marginBottom: 13 }}>
            <SectionLabel>Missed-workout feedback</SectionLabel>
          </div>

          {(feedback ?? []).length === 0 && (
            <div className="card">
              <EmptyState icon={CheckCircle} title="No missed workouts">
                When a scheduled session is missed, the iOS app records why — those show up here
                for review.
              </EmptyState>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {(feedback ?? []).map((f) => {
              const acked = f.acknowledgedAt != null
              const actionLabel =
                f.action === 'move' && f.newDate
                  ? `Rescheduled → ${fmtDay(f.newDate)}`
                  : f.action === 'move'
                    ? 'Rescheduled'
                    : f.action === 'skip'
                      ? 'Skipped'
                      : 'Adjusted'
              return (
                <div className={`fb-card${acked ? ' done' : ''}`} key={f.id}>
                  <div className="fb-top">
                    <WarningCircle size={26} weight="fill" color="var(--amber)" style={{ flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="fb-title">{f.workoutName}</div>
                      <div className="fb-date">{fmtDowDayTime(f.scheduledDate)}</div>
                    </div>
                  </div>
                  <div className="fb-facts">
                    <span style={{ color: 'var(--muted)' }}>Reason</span>
                    <span style={{ fontWeight: 600 }}>{REASON_LABELS[f.reason] ?? f.reason}</span>
                    <span style={{ color: 'var(--faint)' }}>·</span>
                    <span style={{ color: 'var(--muted)' }}>Action</span>
                    <span style={{ fontWeight: 600, color: 'var(--accent)' }}>{actionLabel}</span>
                  </div>
                  {f.reasonNote && (
                    <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 8, lineHeight: 1.5 }}>
                      “{f.reasonNote}”
                    </div>
                  )}
                  {acked ? (
                    <div className="fb-acked">
                      <CheckCircle size={16} weight="bold" />
                      Acknowledged
                    </div>
                  ) : (
                    <button className="fb-ack" disabled={ack.isPending} onClick={() => ack.mutate(f)}>
                      {ack.isPending ? 'Saving…' : 'Acknowledge'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {deleting && (
        <ConfirmDialog
          title="Delete this queue item?"
          body={
            <>
              “{deleting.title}” will be removed from the watch queue.
              {deleting.status === 'pending' ? ' The watch will never receive it.' : ''}
            </>
          }
          confirmLabel="Delete"
          busy={del.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() =>
            del.mutate(deleting.id, {
              onSuccess: () => setDeleting(null),
            })
          }
        />
      )}
    </div>
  )
}

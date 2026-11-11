import { PersonSimpleRun } from '@phosphor-icons/react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePageHeader } from '../components/PageHeader'
import { EmptyState, ErrorNote, Loading } from '../components/ui'
import { ACTIVITY_FILTERS, activityMeta, effortColor, sourceMeta } from '../lib/activity'
import { fmtDay, fmtDistance, fmtDuration, fmtKcal, fmtPaceWithUnit } from '../lib/format'
import { useInfiniteWorkouts, useWorkoutSummary } from '../lib/queries'
import { useUnits } from '../lib/units'
import '../styles/workouts.css'

function SummaryStrip() {
  const units = useUnits()
  const { data } = useWorkoutSummary('month')

  const tiles = useMemo(() => {
    if (!data || data.length === 0) return null
    // Rows are grouped by (period, activity_type); the newest period is "this month".
    const latestPeriod = data.reduce((max, r) => (r.period > max ? r.period : max), data[0].period)
    const rows = data.filter((r) => r.period === latestPeriod)
    const count = rows.reduce((n, r) => n + r.count, 0)
    const energy = rows.reduce((n, r) => n + (r.total_energy_burned ?? 0), 0)
    const run = rows.find((r) => r.activity_type === 'running')
    const pace =
      run?.total_duration && run.total_distance && run.total_distance > 0
        ? run.total_duration / (run.total_distance / 1000)
        : null
    return [
      { label: 'This month', value: `${count} workout${count === 1 ? '' : 's'}` },
      { label: 'Run distance', value: run?.total_distance ? fmtDistance(run.total_distance, units, 1) : '—' },
      { label: 'Avg run pace', value: pace ? fmtPaceWithUnit(pace, units) : '—' },
      { label: 'Energy', value: energy > 0 ? fmtKcal(energy) : '—' },
    ]
  }, [data, units])

  if (!tiles) return null
  return (
    <div className="wo-summary-grid">
      {tiles.map((t) => (
        <div className="wo-summary-tile" key={t.label}>
          <div className="label">{t.label}</div>
          <div className="value">{t.value}</div>
        </div>
      ))}
    </div>
  )
}

export function Workouts() {
  const units = useUnits()
  const navigate = useNavigate()
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined)

  const query = useInfiniteWorkouts(typeFilter)
  const workouts = useMemo(() => (query.data?.pages ?? []).flat(), [query.data])

  usePageHeader('Workouts', typeFilter ? activityMeta(typeFilter).label.toLowerCase() : 'all activity types')

  return (
    <div className="screen">
      <SummaryStrip />

      <div className="wo-filters">
        <button
          className={`filter-chip${typeFilter === undefined ? ' on' : ''}`}
          onClick={() => setTypeFilter(undefined)}
        >
          All
        </button>
        {ACTIVITY_FILTERS.map((t) => {
          const meta = activityMeta(t)
          return (
            <button
              key={t}
              className={`filter-chip${typeFilter === t ? ' on' : ''}`}
              style={{ ['--chip-color' as string]: meta.color }}
              onClick={() => setTypeFilter(t)}
            >
              {meta.label}
            </button>
          )
        })}
      </div>

      {query.error && <ErrorNote error={query.error} />}
      {query.isLoading && <Loading label="Loading workouts…" />}

      {!query.isLoading && workouts.length === 0 && !query.error && (
        <div className="card">
          <EmptyState icon={PersonSimpleRun} title="No workouts yet">
            Workouts arrive automatically once the iOS app is installed and logged in — every
            HealthKit session (Apple Watch, Strava, Hevy, Garmin, Bend) syncs here.
          </EmptyState>
        </div>
      )}

      {workouts.length > 0 && (
        <div className="wo-table">
          <div className="wo-head">
            <span>Activity</span>
            <span>Date</span>
            <span className="hide-sm">Duration</span>
            <span className="hide-sm">Distance</span>
            <span className="hide-sm">Source</span>
            <span style={{ textAlign: 'right' }}>Effort</span>
          </div>
          {workouts.map((w) => {
            const meta = activityMeta(w.activity_type)
            const src = sourceMeta(w.source)
            return (
              <button className="wo-row" key={w.id} onClick={() => navigate(`/workouts/${w.id}`)}>
                <span className="wo-activity">
                  <span className="icon-tile" style={{ width: 36, height: 36, color: meta.color }}>
                    <meta.icon size={19} />
                  </span>
                  <span className="wo-name">{meta.label}</span>
                </span>
                <span className="wo-cell">{fmtDay(w.start_date)}</span>
                <span className="wo-cell hide-sm">{fmtDuration(w.duration)}</span>
                <span className="wo-cell hide-sm">{w.total_distance ? fmtDistance(w.total_distance, units) : '—'}</span>
                <span className="wo-src hide-sm">
                  <span className="src-dot" style={{ background: src.color }} />
                  <span className="src-name">{src.name}</span>
                </span>
                <span className="wo-effort" style={{ color: effortColor(w.effort_score) }}>
                  {w.effort_score != null ? Math.round(w.effort_score) : '—'}
                </span>
              </button>
            )
          })}
        </div>
      )}

      {query.hasNextPage && (
        <div className="wo-loadmore">
          <button className="btn-ghost" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            {query.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  )
}

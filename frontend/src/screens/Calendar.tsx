import { CaretLeft, CaretRight } from '@phosphor-icons/react'
import { useMemo, useState } from 'react'
import { usePageHeader } from '../components/PageHeader'
import { ConflictPill, ErrorNote, Loading, SectionLabel, StatusPill } from '../components/ui'
import { addDays, startOfWeek, toDateKey, todayKey } from '../lib/format'
import { useCalendar } from '../lib/queries'
import type { CalendarEntry } from '../lib/types'
import { useWeekStart } from '../lib/weekStart'
import '../styles/screens.css'

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]
// Monday-first; rotated to Sunday-first when the athlete's week starts on Sunday.
const DOW_SHORT = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
const DOW_LONG = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
const sundayFirst = (days: string[]) => [days[6], ...days.slice(0, 6)]

function eventStyle(e: CalendarEntry): { bg: string; col: string } {
  if (e.kind === 'run') {
    return { bg: 'color-mix(in srgb, var(--accent) 18%, transparent)', col: 'var(--accent)' }
  }
  return { bg: 'rgba(124,92,255,0.16)', col: 'var(--purple-light)' }
}

export function Calendar() {
  usePageHeader('Calendar', 'runs from the watch queue · strength from plan schedules')

  const [view, setView] = useState<'month' | 'week'>('month')
  const [anchor, setAnchor] = useState(() => new Date())
  const weekStart = useWeekStart()
  const dowShort = weekStart === 'sunday' ? sundayFirst(DOW_SHORT) : DOW_SHORT
  const dowLong = weekStart === 'sunday' ? sundayFirst(DOW_LONG) : DOW_LONG

  // Visible range: month grid (starts on the athlete's week start, 6 rows max) or single week.
  const range = useMemo(() => {
    if (view === 'week') {
      const start = startOfWeek(anchor, weekStart)
      return { start, end: addDays(start, 6) }
    }
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
    const gridStart = startOfWeek(first, weekStart)
    const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0)
    const gridEnd = addDays(startOfWeek(last, weekStart), 6)
    return { start: gridStart, end: gridEnd }
  }, [view, anchor, weekStart])

  const { data, isLoading, error } = useCalendar(toDateKey(range.start), toDateKey(range.end))

  const byDate = useMemo(() => {
    const map = new Map<string, CalendarEntry[]>()
    for (const e of data?.entries ?? []) {
      const list = map.get(e.date) ?? []
      list.push(e)
      map.set(e.date, list)
    }
    return map
  }, [data])

  const cells = useMemo(() => {
    const out: { date: Date; key: string; muted: boolean }[] = []
    for (let d = new Date(range.start); d <= range.end; d = addDays(d, 1)) {
      out.push({ date: d, key: toDateKey(d), muted: d.getMonth() !== anchor.getMonth() })
    }
    return out
  }, [range, anchor])

  const weekDays = useMemo(() => {
    const start = startOfWeek(view === 'week' ? anchor : new Date(), weekStart)
    return Array.from({ length: 7 }, (_, i) => {
      const date = addDays(start, i)
      return { date, key: toDateKey(date) }
    })
  }, [view, anchor, weekStart])

  const step = (dir: 1 | -1) => {
    setAnchor((a) =>
      view === 'month' ? new Date(a.getFullYear(), a.getMonth() + dir, 1) : addDays(a, dir * 7),
    )
  }

  const today = todayKey()

  return (
    <div className="screen">
      <div className="cal-toolbar">
        <div className="seg-toggle">
          <button className={view === 'month' ? 'on' : ''} onClick={() => setView('month')}>
            Month
          </button>
          <button className={view === 'week' ? 'on' : ''} onClick={() => setView('week')}>
            Week
          </button>
        </div>
        <div className="cal-legend">
          <span className="lg">
            <span className="swatch" style={{ background: 'var(--accent)' }} />
            Run
          </span>
          <span className="lg">
            <span className="swatch" style={{ background: 'var(--purple)' }} />
            Strength
          </span>
          <span className="lg">
            <span className="swatch" style={{ background: 'transparent', border: '2px solid var(--amber)' }} />
            Conflict
          </span>
        </div>
      </div>

      {error && <ErrorNote error={error} />}
      {isLoading && <Loading label="Loading schedule…" />}

      {view === 'month' && !isLoading && (
        <div className="cal-month-card">
          <div className="cal-month-head">
            <span className="month-name">
              {MONTH_NAMES[anchor.getMonth()]} {anchor.getFullYear()}
            </span>
            <div className="month-btns">
              <button aria-label="Previous month" onClick={() => step(-1)}>
                <CaretLeft size={14} weight="bold" />
              </button>
              <button aria-label="Next month" onClick={() => step(1)}>
                <CaretRight size={14} weight="bold" />
              </button>
            </div>
          </div>
          <div className="cal-dow-row">
            {dowShort.map((d, i) => (
              <span key={i}>{d}</span>
            ))}
          </div>
          <div className="cal-grid">
            {cells.map((c) => {
              const events = byDate.get(c.key) ?? []
              const conflict = events.some((e) => e.conflict)
              const cls = [
                'cal-cell',
                c.muted ? 'muted' : '',
                c.key === today ? 'today' : '',
                conflict ? 'conflict' : '',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                <div className={cls} key={c.key}>
                  <span className="cell-day">{c.date.getDate()}</span>
                  <div className="cell-events">
                    {events.slice(0, 3).map((e, i) => {
                      const st = eventStyle(e)
                      return (
                        <span
                          key={i}
                          className={`cal-event${e.completed ? ' done' : ''}`}
                          style={{ background: st.bg, color: st.col }}
                          title={e.title}
                        >
                          {e.title}
                        </span>
                      )
                    })}
                    {events.length > 3 && (
                      <span className="mono-meta" style={{ fontSize: 9 }}>
                        +{events.length - 3} more
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {view === 'week' && !isLoading && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 14 }}>
          <div className="month-btns" style={{ display: 'flex', gap: 8 }}>
            <button className="btn-ghost" style={{ padding: '7px 12px' }} onClick={() => step(-1)}>
              <CaretLeft size={13} weight="bold" /> Prev
            </button>
            <button className="btn-ghost" style={{ padding: '7px 12px' }} onClick={() => step(1)}>
              Next <CaretRight size={13} weight="bold" />
            </button>
          </div>
        </div>
      )}

      {!isLoading && (
        <div className="card" style={{ overflow: 'hidden' }}>
          <div style={{ padding: '16px 20px 12px' }}>
            <SectionLabel>{view === 'week' ? 'Week' : 'This week'}</SectionLabel>
          </div>
          {weekDays.map(({ date, key }, i) => {
            const events = byDate.get(key) ?? []
            const isToday = key === today
            if (events.length === 0) {
              return (
                <div className="week-row" key={key} style={{ cursor: 'default' }}>
                  <div className="wr-date">
                    <div className="wr-dow">{dowLong[i]}</div>
                    <div className="wr-day" style={{ color: isToday ? 'var(--accent)' : 'var(--disabled)' }}>
                      {date.getDate()}
                    </div>
                  </div>
                  <span className="wr-bar" style={{ background: '#2A2520' }} />
                  <div style={{ flex: 1 }}>
                    <div className="row-title" style={{ color: 'var(--faint)' }}>
                      Rest
                    </div>
                    <div className="row-meta">recovery day</div>
                  </div>
                </div>
              )
            }
            return events.map((e, j) => {
              const st = eventStyle(e)
              return (
                <div className="week-row" key={`${key}-${j}`} style={{ cursor: 'default' }}>
                  <div className="wr-date" style={{ visibility: j === 0 ? 'visible' : 'hidden' }}>
                    <div className="wr-dow">{dowLong[i]}</div>
                    <div className="wr-day" style={{ color: isToday ? 'var(--accent)' : 'var(--text)' }}>
                      {date.getDate()}
                    </div>
                  </div>
                  <span className="wr-bar" style={{ background: st.col }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="row-title">{e.title}</div>
                    <div className="row-meta">
                      {e.kind === 'strength'
                        ? [e.planName, e.routineId ? 'Hevy routine' : null].filter(Boolean).join(' · ') || 'strength'
                        : e.planName || 'watch queue'}
                    </div>
                  </div>
                  {e.conflict && <ConflictPill />}
                  <StatusPill status={e.completed ? 'completed' : (e.status ?? 'planned')} />
                </div>
              )
            })
          })}
        </div>
      )}
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import {
  Bell,
  Brain,
  CalendarDots,
  CaretLeft,
  FlagBanner,
  Heartbeat,
  HardDrives,
  List,
  PersonSimpleRun,
  SignOut,
  SquaresFour,
  UsersThree,
  Watch,
} from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useQueue } from '../lib/queries'
import { LogoMark } from './LogoMark'
import { usePageHeaderValue } from './PageHeader'
import '../styles/layout.css'

const NAV: { to: string; label: string; icon: Icon }[] = [
  { to: '/', label: 'Overview', icon: SquaresFour },
  { to: '/calendar', label: 'Calendar', icon: CalendarDots },
  { to: '/workouts', label: 'Workouts', icon: PersonSimpleRun },
  { to: '/plans', label: 'Plans', icon: FlagBanner },
  { to: '/notes', label: 'Notes', icon: Brain },
  { to: '/health', label: 'Health', icon: Heartbeat },
  { to: '/queue', label: 'Queue', icon: Watch },
]

// Admins manage accounts, they aren't athletes — no workout data behind the athlete screens.
const ADMIN_NAV: { to: string; label: string; icon: Icon }[] = [
  { to: '/users', label: 'Users', icon: UsersThree },
  { to: '/system', label: 'System', icon: HardDrives },
]

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const header = usePageHeaderValue()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const isAdmin = user?.role === 'admin'

  const pending = useQueue('pending', 100, !isAdmin)
  const pendingCount = pending.data?.length ?? 0

  const health = useQuery({
    queryKey: ['liveness'],
    queryFn: () => api.get<{ service: string; database: string }>('/api/health'),
    refetchInterval: 60_000,
    retry: false,
  })
  const online = health.isSuccess && health.data.database === 'ok'
  const probing = health.isPending

  const initial = (user?.displayName || user?.username || '?').charAt(0).toUpperCase()

  return (
    <div className="app-frame">
      {drawerOpen && <div className="sidebar-scrim" onClick={() => setDrawerOpen(false)} />}
      <aside className={`sidebar${drawerOpen ? ' open' : ''}`}>
        <div className="sidebar-logo">
          <LogoMark />
          <span className="logo-name">Loopback</span>
        </div>

        <nav className="sidebar-nav">
          {(isAdmin ? ADMIN_NAV : NAV).map(({ to, label, icon: IconCmp }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              onClick={() => setDrawerOpen(false)}
            >
              <IconCmp size={19} />
              <span className="nav-label">{label}</span>
              {to === '/queue' && pendingCount > 0 && <span className="nav-badge">{pendingCount}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="server-chip">
            <span className={`dot ${probing ? 'idle' : online ? 'ok' : 'err'}`} />
            <span className="server-name">
              {window.location.hostname.split('.')[0]} · {probing ? 'checking…' : online ? 'online' : 'unreachable'}
            </span>
          </div>
          <div className="sidebar-user">
            <button
              style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}
              title="Settings"
              onClick={() => {
                setDrawerOpen(false)
                navigate('/settings')
              }}
            >
              <span className="avatar">{initial}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="u-name">{user?.displayName || user?.username}</div>
                <div className="u-role">{user?.role === 'admin' ? 'Admin' : 'Member'}</div>
              </div>
            </button>
            <button className="signout" title="Log out" onClick={() => void logout()}>
              <SignOut size={18} />
            </button>
          </div>
        </div>
      </aside>

      <div className="main-col">
        <header className="topbar">
          <div className="topbar-left">
            <button className="menu-btn" aria-label="Menu" onClick={() => setDrawerOpen(true)}>
              <List size={18} weight="bold" />
            </button>
            {header.backTo && (
              <button className="back-btn" aria-label="Back" onClick={() => navigate(header.backTo!)}>
                <CaretLeft size={17} weight="bold" />
              </button>
            )}
            <div style={{ minWidth: 0 }}>
              <div className="page-title">{header.title}</div>
              {header.subtitle && <div className="page-subtitle">{header.subtitle}</div>}
            </div>
          </div>
          {!isAdmin && (
            <button className="bell-btn" aria-label="Attention items" onClick={() => navigate('/queue')}>
              <Bell size={18} />
              {pendingCount > 0 && <span className="bell-dot" />}
            </button>
          )}
        </header>

        <div className="scroll-region">
          <div className="page-pad">
            <Outlet />
          </div>
        </div>
      </div>
    </div>
  )
}

import {
  Archive,
  Database,
  Key,
  Prohibit,
  ShieldCheck,
  ShieldWarning,
  SignIn,
  UserCircleMinus,
  UserCirclePlus,
  UserPlus,
} from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { Navigate } from 'react-router-dom'
import { usePageHeader } from '../components/PageHeader'
import { ErrorNote, Loading, SectionLabel } from '../components/ui'
import { useAuth } from '../lib/auth'
import { fmtBytes, relTime } from '../lib/format'
import { useAuthEvents, useBackupNow, useSystemStatus } from '../lib/queries'
import type { AuthEventRow } from '../lib/types'
import '../styles/settings.css'
import '../styles/system.css'

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)

function eventView(e: AuthEventRow): { icon: Icon; text: string; tone: 'ok' | 'warn' | 'bad' } {
  const who = e.username ?? 'unknown'
  const actor = e.actorUsername ?? 'admin'
  const byOther = e.actorUsername != null && e.actorUsername !== e.username
  const tokenName = str(e.detail?.name)
  const device = str(e.detail?.device)
  switch (e.event) {
    case 'login_success':
      return { icon: SignIn, text: `${who} signed in${device ? ` (${device})` : ''}`, tone: 'ok' }
    case 'login_failed':
      return { icon: ShieldWarning, text: `Failed login for “${who}”`, tone: 'bad' }
    case 'login_rate_limited':
      return { icon: Prohibit, text: 'Login rate limit tripped', tone: 'bad' }
    case 'password_changed':
      return { icon: Key, text: `${who} changed their password`, tone: 'ok' }
    case 'password_reset':
      return { icon: Key, text: `${actor} reset ${who}'s password`, tone: 'warn' }
    case 'token_created':
      return { icon: Key, text: `${who} created token${tokenName ? ` “${tokenName}”` : ''}`, tone: 'ok' }
    case 'token_revoked':
      return {
        icon: Key,
        text: byOther
          ? `${actor} revoked ${who}'s token${tokenName ? ` “${tokenName}”` : ''}`
          : `${who} revoked token${tokenName ? ` “${tokenName}”` : ''}`,
        tone: 'warn',
      }
    case 'user_created':
      return { icon: UserPlus, text: `${actor} created account ${who}${str(e.detail?.role) === 'admin' ? ' (admin)' : ''}`, tone: 'ok' }
    case 'user_deactivated':
      return { icon: UserCircleMinus, text: `${actor} deactivated ${who}`, tone: 'bad' }
    case 'user_reactivated':
      return { icon: UserCirclePlus, text: `${actor} reactivated ${who}`, tone: 'ok' }
    case 'setup_completed':
      return { icon: ShieldCheck, text: `First-run setup — admin account “${who}” created`, tone: 'ok' }
    case 'token_rejected': {
      // A device still presenting a dead token. Expired/inactive resolve to a
      // user (stranded household device, warn); unknown tokens don't (bad).
      const reason = str(e.detail?.reason)
      const hint = str(e.detail?.token_hint)
      if (reason === 'scope') {
        // A coach token used for something no coach tool does: the athlete's
        // own client pointed at the wrong token, or a leaked one being tried.
        const what = [str(e.detail?.method), str(e.detail?.path)].filter(Boolean).join(' ')
        return {
          icon: ShieldWarning,
          text: `${who}'s coach token${tokenName ? ` “${tokenName}”` : ''} was refused outside the coach${
            what ? ` (${what})` : ''
          }`,
          tone: 'warn',
        }
      }
      if (reason === 'expired' || reason === 'inactive') {
        return {
          icon: Key,
          text: `${who}'s token${tokenName ? ` “${tokenName}”` : ''} rejected — ${
            reason === 'expired' ? 'expired' : 'account inactive'
          }`,
          tone: 'warn',
        }
      }
      return {
        icon: ShieldWarning,
        text: `Rejected unknown token${hint ? ` (…${hint})` : ''}`,
        tone: 'bad',
      }
    }
    default:
      return { icon: ShieldWarning, text: `${e.event}${who !== 'unknown' ? ` — ${who}` : ''}`, tone: 'warn' }
  }
}

const TONE: Record<'ok' | 'warn' | 'bad', string> = {
  ok: 'var(--green)',
  warn: 'var(--amber)',
  bad: 'var(--red)',
}

export function System() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const system = useSystemStatus(isAdmin)
  const events = useAuthEvents(isAdmin)
  const backupNow = useBackupNow()

  usePageHeader('System', 'backups · database · auth activity')

  if (!isAdmin) return <Navigate to="/" replace />

  const s = system.data
  const backupAgeH = s?.backup ? (Date.now() - new Date(s.backup.completedAt).getTime()) / 3_600_000 : null
  // Nightly cadence: fresh under ~26h, stale under two missed nights, dead after.
  const backupTone = backupAgeH == null ? 'bad' : backupAgeH < 26 ? 'ok' : backupAgeH < 50 ? 'warn' : 'bad'

  return (
    <div className="system-wrap screen">
      {system.error != null && <ErrorNote error={system.error} />}
      {system.isLoading && <Loading label="Loading system status…" />}

      {s && (
        <div className="sys-grid">
          <div className="sys-card">
            <div className="sys-card-head">
              <span className="icon-tile" style={{ width: 34, height: 34, color: TONE[backupTone] }}>
                <Archive size={18} />
              </span>
              <SectionLabel>Database backup</SectionLabel>
            </div>
            {s.backup ? (
              <>
                <div className="sys-big" style={{ color: TONE[backupTone] }}>
                  {relTime(s.backup.completedAt)}
                </div>
                <div className="mono-meta sys-meta">
                  {s.backup.file} · {fmtBytes(s.backup.sizeBytes)} · {s.backupCount} kept
                </div>
              </>
            ) : (
              <>
                <div className="sys-big" style={{ color: 'var(--red)' }}>
                  none found
                </div>
                <div className="mono-meta sys-meta">no dumps in the mounted backup directory — see the README's Backups section</div>
              </>
            )}
            <button
              className="btn-ghost"
              style={{ marginTop: 12, padding: '7px 14px', fontSize: 12, alignSelf: 'flex-start' }}
              disabled={backupNow.isPending}
              onClick={() => backupNow.mutate()}
            >
              {backupNow.isPending ? 'Backing up…' : 'Back up now'}
            </button>
            {backupNow.error != null && <ErrorNote error={backupNow.error} />}
          </div>

          <div className="sys-card">
            <div className="sys-card-head">
              <span className="icon-tile" style={{ width: 34, height: 34, color: 'var(--blue)' }}>
                <Database size={18} />
              </span>
              <SectionLabel>Database</SectionLabel>
            </div>
            <div className="sys-big">{fmtBytes(s.dbSizeBytes)}</div>
            <div className="mono-meta sys-meta">
              {s.counts.workouts ?? 0} workouts · {s.counts.healthDays ?? 0} health days · {s.counts.users ?? 0} users
              <br />
              v{s.appVersion} · migration {s.migrationHead ?? 'unknown'}
            </div>
          </div>
        </div>
      )}

      <div style={{ margin: '26px 0 12px' }}>
        <SectionLabel>Auth activity</SectionLabel>
      </div>
      {events.error != null && <ErrorNote error={events.error} />}
      {events.isLoading && <Loading label="Loading activity…" />}
      {events.data && events.data.length === 0 && (
        <div className="mono-meta" style={{ padding: '14px 2px' }}>
          No auth events recorded yet.
        </div>
      )}
      {events.data && events.data.length > 0 && (
        <div className="token-list">
          {events.data.map((e) => {
            const v = eventView(e)
            const EIcon = v.icon
            return (
              <div className="token-row" key={e.id}>
                <span className="icon-tile" style={{ width: 34, height: 34, color: TONE[v.tone] }}>
                  <EIcon size={17} />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="t-name" style={{ fontSize: 13.5 }}>
                    {v.text}
                  </div>
                  <div className="t-meta">
                    {relTime(e.createdAt)}
                    {e.ip ? ` · from ${e.ip}` : ''}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

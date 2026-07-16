import { Brain, Check, Copy, Desktop, DeviceMobile, Key, Plus, SignOut } from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { useState } from 'react'
import { usePageHeader } from '../components/PageHeader'
import { ConfirmDialog, ErrorNote, Loading, Modal, SectionLabel } from '../components/ui'
import { useAuth } from '../lib/auth'
import { fmtDayYear, relTime } from '../lib/format'
import { useChangePassword, useMe, useMintToken, useRevokeToken } from '../lib/queries'
import type { ApiTokenInfo } from '../lib/types'
import '../styles/settings.css'

const MIN_PASSWORD = 8

function tokenIcon(name: string): Icon {
  const n = name.toLowerCase()
  if (n.includes('iphone') || n.includes('phone') || n.includes('ios')) return DeviceMobile
  if (n.includes('mcp') || n.includes('coach')) return Brain
  if (n.includes('web') || n.includes('dashboard') || n.includes('browser')) return Desktop
  return Key
}

function tokenMeta(t: ApiTokenInfo): string {
  const parts = [`created ${fmtDayYear(t.createdAt)}`, `last used ${relTime(t.lastUsedAt)}`]
  if (t.expiresAt) {
    const expired = new Date(t.expiresAt).getTime() < Date.now()
    parts.push(`${expired ? 'expired' : 'expires'} ${fmtDayYear(t.expiresAt)}`)
  } else {
    parts.push('no expiry')
  }
  return parts.join(' · ')
}

function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')

  const mismatch = confirm.length > 0 && next !== confirm
  const valid = current.length > 0 && next.length >= MIN_PASSWORD && next === confirm

  if (change.isSuccess) {
    const revoked = change.data.revokedTokens
    return (
      <Modal onClose={onClose} width={420}>
        <div className="display" style={{ fontSize: 20, fontWeight: 600 }}>
          Password changed
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-3)', lineHeight: 1.55, margin: '10px 0 22px' }}>
          {revoked > 0
            ? `${revoked} other ${revoked === 1 ? 'session was' : 'sessions were'} signed out. This device stays logged in.`
            : 'No other sessions existed. This device stays logged in.'}
        </div>
        <button className="btn-accent" style={{ width: '100%' }} onClick={onClose}>
          Done
        </button>
      </Modal>
    )
  }

  return (
    <Modal onClose={onClose} width={420}>
      <div className="display" style={{ fontSize: 20, fontWeight: 600 }}>
        Change password
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', margin: '5px 0 20px' }}>
        Changing it signs out every other session; this device stays logged in.
      </div>

      <div className="field-label">Current password</div>
      <input
        className="field-input"
        style={{ marginBottom: 14 }}
        type="password"
        autoComplete="current-password"
        autoFocus
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
      />

      <div className="field-label">New password (min {MIN_PASSWORD} characters)</div>
      <input
        className="field-input"
        style={{ marginBottom: 14 }}
        type="password"
        autoComplete="new-password"
        value={next}
        onChange={(e) => setNext(e.target.value)}
      />

      <div className="field-label">Confirm new password</div>
      <input
        className="field-input"
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
      />
      {mismatch && (
        <div style={{ fontSize: 12, color: 'var(--red)', marginTop: 6 }}>Passwords don't match.</div>
      )}

      {change.error != null && (
        <div style={{ marginTop: 12 }}>
          <ErrorNote error={change.error} />
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 22 }}>
        <button className="btn-ghost" style={{ flex: 1 }} onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn-accent"
          style={{ flex: 1 }}
          disabled={!valid || change.isPending}
          onClick={() => change.mutate({ currentPassword: current, newPassword: next })}
        >
          {change.isPending ? 'Saving…' : 'Change password'}
        </button>
      </div>
    </Modal>
  )
}

const EXPIRY_CHOICES: { label: string; days: number | null }[] = [
  { label: 'Never', days: null },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: '1 year', days: 365 },
]

function NewTokenModal({ onClose }: { onClose: () => void }) {
  const mint = useMintToken()
  const [name, setName] = useState('')
  const [expiryDays, setExpiryDays] = useState<number | null>(null)
  const [copied, setCopied] = useState(false)

  const submit = () => {
    const expiresAt =
      expiryDays == null ? undefined : new Date(Date.now() + expiryDays * 24 * 60 * 60 * 1000).toISOString()
    mint.mutate({ name: name.trim(), expiresAt })
  }

  if (mint.isSuccess) {
    return (
      <Modal onClose={onClose} width={460}>
        <div className="display" style={{ fontSize: 20, fontWeight: 600 }}>
          Token created
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--muted)', margin: '5px 0 14px' }}>
          Copy it now — it's shown <strong style={{ color: 'var(--amber)' }}>only this once</strong> and can't be
          retrieved later. Use it as <span style={{ fontFamily: 'var(--font-mono)' }}>Authorization: Bearer …</span>
        </div>
        <div className="cli-box" style={{ marginTop: 0, wordBreak: 'break-all', whiteSpace: 'pre-wrap', userSelect: 'all' }}>
          {mint.data.token}
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
          <button className="btn-ghost" style={{ flex: 1 }} onClick={onClose}>
            Done
          </button>
          <button
            className="btn-accent"
            style={{ flex: 1 }}
            onClick={() => {
              void navigator.clipboard?.writeText(mint.data.token)
              setCopied(true)
            }}
          >
            {copied ? <Check size={15} weight="bold" /> : <Copy size={15} />}
            {copied ? 'Copied' : 'Copy token'}
          </button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal onClose={onClose} width={460}>
      <div className="display" style={{ fontSize: 20, fontWeight: 600 }}>
        New token
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', margin: '5px 0 20px' }}>
        For hooking up a device or integration (e.g. a personal MCP) without logging in there.
      </div>

      <div className="field-label">Name</div>
      <input
        className="field-input"
        style={{ marginBottom: 14 }}
        placeholder="Coach MCP"
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
      />

      <div className="field-label">Expires</div>
      <div style={{ display: 'flex', gap: 6 }}>
        {EXPIRY_CHOICES.map((c) => (
          <button
            key={c.label}
            className={`filter-chip${expiryDays === c.days ? ' on' : ''}`}
            style={{ flex: 1 }}
            onClick={() => setExpiryDays(c.days)}
          >
            {c.label}
          </button>
        ))}
      </div>

      {mint.error != null && (
        <div style={{ marginTop: 12 }}>
          <ErrorNote error={mint.error} />
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 22 }}>
        <button className="btn-ghost" style={{ flex: 1 }} onClick={onClose}>
          Cancel
        </button>
        <button className="btn-accent" style={{ flex: 1 }} disabled={!name.trim() || mint.isPending} onClick={submit}>
          {mint.isPending ? 'Creating…' : 'Create token'}
        </button>
      </div>
    </Modal>
  )
}

export function Settings() {
  const { user, tokenId, logout } = useAuth()
  const { data, isLoading, error } = useMe()
  const revoke = useRevokeToken()
  const [revoking, setRevoking] = useState<ApiTokenInfo | null>(null)
  const [confirmLogout, setConfirmLogout] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)
  const [mintingToken, setMintingToken] = useState(false)

  usePageHeader('Settings', data ? `${data.tokens.length} active tokens` : undefined)

  const me = data?.user ?? user
  const initial = (me?.displayName || me?.username || '?').charAt(0).toUpperCase()

  return (
    <div className="settings-wrap screen">
      <div style={{ marginBottom: 12 }}>
        <SectionLabel>Profile</SectionLabel>
      </div>
      <div className="profile-card">
        <span className="avatar-lg">{initial}</span>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div className="display" style={{ fontSize: 18, fontWeight: 600 }}>
            {me?.displayName || me?.username}
          </div>
          <div className="mono-meta" style={{ marginTop: 3 }}>
            {me?.username} · {me?.role === 'admin' ? 'Admin' : 'Member'}
          </div>
        </div>
        <button className="btn-ghost" style={{ padding: '9px 16px', fontSize: 13 }} onClick={() => setChangingPassword(true)}>
          Change password
        </button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <SectionLabel>Devices &amp; tokens</SectionLabel>
        <button
          className="btn-accent"
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 13px', fontSize: 12 }}
          onClick={() => setMintingToken(true)}
        >
          <Plus size={14} />
          New token
        </button>
      </div>

      {error && <ErrorNote error={error} />}
      {isLoading && <Loading label="Loading tokens…" />}

      {data && (
        <div className="token-list">
          {data.tokens.map((t) => {
            const TIcon = tokenIcon(t.name)
            const isCurrent = t.id === tokenId
            const expired = t.expiresAt != null && new Date(t.expiresAt).getTime() < Date.now()
            return (
              <div className="token-row" key={t.id}>
                <span
                  className="icon-tile"
                  style={{ width: 36, height: 36, color: expired ? 'var(--faint)' : isCurrent ? 'var(--accent)' : 'var(--text-3)' }}
                >
                  <TIcon size={19} />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="t-name">
                    {t.name || 'Unnamed token'}
                    {isCurrent && <span className="t-this">This device</span>}
                  </div>
                  <div className="t-meta">{tokenMeta(t)}</div>
                </div>
                <button
                  className="t-action"
                  style={{ color: isCurrent ? 'var(--amber)' : 'var(--red)' }}
                  onClick={() => (isCurrent ? setConfirmLogout(true) : setRevoking(t))}
                >
                  {isCurrent ? 'Log out' : expired ? 'Remove' : 'Revoke'}
                </button>
              </div>
            )
          })}
        </div>
      )}

      <div style={{ marginTop: 26 }}>
        <button className="btn-danger-outline" style={{ padding: '12px 22px', fontSize: 14 }} onClick={() => setConfirmLogout(true)}>
          <SignOut size={17} />
          Log out · revoke this session
        </button>
      </div>

      {changingPassword && <ChangePasswordModal onClose={() => setChangingPassword(false)} />}
      {mintingToken && <NewTokenModal onClose={() => setMintingToken(false)} />}

      {revoking && (
        <ConfirmDialog
          title={`Revoke “${revoking.name || 'this token'}”?`}
          body="The device using this token stops authenticating immediately. It can be re-added by logging in again on that device."
          confirmLabel="Revoke"
          busy={revoke.isPending}
          onCancel={() => setRevoking(null)}
          onConfirm={() =>
            revoke.mutate(revoking.id, {
              onSuccess: () => setRevoking(null),
            })
          }
        />
      )}

      {confirmLogout && (
        <ConfirmDialog
          title="Log out?"
          body="This revokes the web dashboard's token on the server and clears it from this browser."
          confirmLabel="Log out"
          onCancel={() => setConfirmLogout(false)}
          onConfirm={() => void logout()}
        />
      )}
    </div>
  )
}

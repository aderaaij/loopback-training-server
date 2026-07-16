import { Plus, UsersThree } from '@phosphor-icons/react'
import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { usePageHeader } from '../components/PageHeader'
import { ConfirmDialog, ErrorNote, Loading, Modal, SectionLabel } from '../components/ui'
import { useAuth } from '../lib/auth'
import { relTime } from '../lib/format'
import { useAdminUsers, useCreateUser, useResetUserPassword, useSetUserActive } from '../lib/queries'
import type { AdminUserRow } from '../lib/types'
import '../styles/settings.css'

const MIN_PASSWORD = 8

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const create = useCreateUser()
  const [displayName, setDisplayName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)

  const uname = username.trim().toLowerCase()
  const valid = uname.length > 0 && !/\s/.test(uname) && password.length >= MIN_PASSWORD

  const submit = () =>
    create.mutate(
      {
        username: uname,
        password,
        displayName: displayName.trim() || undefined,
        role: isAdmin ? 'admin' : 'user',
      },
      { onSuccess: onClose },
    )

  return (
    <Modal onClose={onClose} width={460}>
      <div className="display" style={{ fontSize: 20, fontWeight: 600 }}>
        Create member
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', margin: '5px 0 20px' }}>
        They log in with this username and password; devices get their own tokens from there.
      </div>

      <div className="field-label">Display name</div>
      <input
        className="field-input"
        style={{ marginBottom: 14 }}
        placeholder="Sam Rivera"
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
      />

      <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
        <div style={{ flex: 1 }}>
          <div className="field-label">Username</div>
          <input
            className="field-input"
            placeholder="sam"
            autoCapitalize="none"
            autoCorrect="off"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div style={{ flex: 1 }}>
          <div className="field-label">Role</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className={`filter-chip${!isAdmin ? ' on' : ''}`} style={{ flex: 1 }} onClick={() => setIsAdmin(false)}>
              Member
            </button>
            <button className={`filter-chip${isAdmin ? ' on' : ''}`} style={{ flex: 1 }} onClick={() => setIsAdmin(true)}>
              Admin
            </button>
          </div>
        </div>
      </div>

      <div className="field-label">Password (min {MIN_PASSWORD} characters)</div>
      <input
        className="field-input"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />

      {create.error != null && (
        <div style={{ marginTop: 12 }}>
          <ErrorNote error={create.error} />
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 22 }}>
        <button className="btn-ghost" style={{ flex: 1 }} onClick={onClose}>
          Cancel
        </button>
        <button className="btn-accent" style={{ flex: 1 }} disabled={!valid || create.isPending} onClick={submit}>
          {create.isPending ? 'Creating…' : 'Create member'}
        </button>
      </div>
    </Modal>
  )
}

function ResetPasswordModal({ user, onClose }: { user: AdminUserRow; onClose: () => void }) {
  const reset = useResetUserPassword()
  const [password, setPassword] = useState('')

  return (
    <Modal onClose={onClose} width={420}>
      <div className="display" style={{ fontSize: 20, fontWeight: 600 }}>
        Reset password
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', margin: '5px 0 20px' }}>
        Set a new password for <strong style={{ color: 'var(--text-3)' }}>{user.displayName || user.username}</strong>.
        Their devices stay logged in — only the password changes.
      </div>

      <div className="field-label">New password (min {MIN_PASSWORD} characters)</div>
      <input
        className="field-input"
        type="password"
        autoComplete="new-password"
        autoFocus
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />

      {reset.error != null && (
        <div style={{ marginTop: 12 }}>
          <ErrorNote error={reset.error} />
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 22 }}>
        <button className="btn-ghost" style={{ flex: 1 }} onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn-accent"
          style={{ flex: 1 }}
          disabled={password.length < MIN_PASSWORD || reset.isPending}
          onClick={() => reset.mutate({ id: user.id, password }, { onSuccess: onClose })}
        >
          {reset.isPending ? 'Saving…' : 'Set password'}
        </button>
      </div>
    </Modal>
  )
}

export function Users() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const adminUsers = useAdminUsers(isAdmin)
  const setActive = useSetUserActive()
  const [createOpen, setCreateOpen] = useState(false)
  const [resetting, setResetting] = useState<AdminUserRow | null>(null)
  const [deactivating, setDeactivating] = useState<AdminUserRow | null>(null)

  usePageHeader('User management', 'household accounts')

  if (!isAdmin) return <Navigate to="/" replace />

  const rows = adminUsers.data ?? []

  return (
    <div className="users-wrap screen">
      <div className="users-head">
        <SectionLabel>Household members</SectionLabel>
        <button className="btn-accent" style={{ padding: '9px 16px', fontSize: 13 }} onClick={() => setCreateOpen(true)}>
          <Plus size={15} weight="bold" />
          Create user
        </button>
      </div>

      {adminUsers.error != null && <ErrorNote error={adminUsers.error} />}
      {adminUsers.isLoading && <Loading label="Loading members…" />}

      {adminUsers.data && (
        <div className="users-table">
          <div className="u-head">
            <span>Member</span>
            <span className="hide-sm">Role</span>
            <span className="hide-sm">Tokens</span>
            <span className="hide-sm">Last seen</span>
            <span>Status</span>
            <span style={{ textAlign: 'right' }}>Actions</span>
          </div>
          {rows.map((u) => {
            const isSelf = u.id === user?.id
            return (
              <div className="u-row" key={u.id} style={u.isActive ? undefined : { opacity: 0.55 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
                  <span
                    className="avatar-lg"
                    style={{ width: 38, height: 38, fontSize: 15, borderRadius: 11, color: u.role === 'admin' ? 'var(--accent)' : 'var(--blue)' }}
                  >
                    {(u.displayName || u.username).charAt(0).toUpperCase()}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 14.5, fontWeight: 600 }}>
                      {u.displayName || u.username}
                      {isSelf && <span className="t-this" style={{ marginLeft: 8 }}>You</span>}
                    </div>
                    <div className="mono-meta" style={{ fontSize: 10.5 }}>
                      {u.username}
                    </div>
                  </div>
                </div>
                <span
                  className="hide-sm"
                  style={{ fontSize: 12.5, fontWeight: 600, color: u.role === 'admin' ? 'var(--accent)' : 'var(--text-3)' }}
                >
                  {u.role === 'admin' ? 'Admin' : 'Member'}
                </span>
                <span className="mono-meta hide-sm" style={{ fontSize: 12.5 }}>
                  {u.tokenCount}
                </span>
                <span className="mono-meta hide-sm" style={{ fontSize: 11.5 }}>
                  {u.lastSeenAt ? relTime(u.lastSeenAt) : 'never'}
                </span>
                <span>
                  <span
                    className="status-pill"
                    style={{
                      color: u.isActive ? 'var(--green)' : 'var(--muted)',
                      background: u.isActive ? 'rgba(95,185,138,0.14)' : 'rgba(245,235,220,0.06)',
                    }}
                  >
                    {u.isActive ? 'Active' : 'Off'}
                  </span>
                </span>
                <span className="u-actions">
                  <button className="t-action" style={{ color: 'var(--amber)' }} onClick={() => setResetting(u)}>
                    Reset password
                  </button>
                  {!isSelf &&
                    (u.isActive ? (
                      <button className="t-action" style={{ color: 'var(--red)' }} onClick={() => setDeactivating(u)}>
                        Deactivate
                      </button>
                    ) : (
                      <button
                        className="t-action"
                        style={{ color: 'var(--green)' }}
                        disabled={setActive.isPending}
                        onClick={() => setActive.mutate({ id: u.id, isActive: true })}
                      >
                        Reactivate
                      </button>
                    ))}
                </span>
              </div>
            )
          })}
        </div>
      )}

      <div style={{ marginTop: 14, fontSize: 12, color: 'var(--faint)', lineHeight: 1.5, display: 'flex', gap: 8, alignItems: 'center' }}>
        <UsersThree size={15} />
        Deactivating a member revokes all their tokens — their devices stop authenticating immediately. No self-service
        registration exists by design.
      </div>

      {createOpen && <CreateUserModal onClose={() => setCreateOpen(false)} />}
      {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />}
      {deactivating && (
        <ConfirmDialog
          title={`Deactivate ${deactivating.displayName || deactivating.username}?`}
          body="All their tokens are revoked — every device stops authenticating immediately. Their data is kept and the account can be reactivated later."
          confirmLabel="Deactivate"
          busy={setActive.isPending}
          onCancel={() => setDeactivating(null)}
          onConfirm={() =>
            setActive.mutate(
              { id: deactivating.id, isActive: false },
              { onSuccess: () => setDeactivating(null) },
            )
          }
        />
      )}
    </div>
  )
}

import { LockKey, WarningCircle } from '@phosphor-icons/react'
import { LogoMark } from '../components/LogoMark'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { LoginResponse, SetupStatus } from '../lib/types'
import '../styles/login.css'

/** 'checking' until GET /api/auth/setup answers — avoids flashing the wrong form. */
type Mode = 'checking' | 'login' | 'setup'

export function Login() {
  const { user, login, adoptSession } = useAuth()
  const navigate = useNavigate()
  // Set by RequireAuth when it sent someone here from a page that needs a
  // session. Only ever a path on this site, so signing in cannot be turned
  // into a way of sending someone elsewhere.
  const from = (useLocation().state as { from?: unknown } | null)?.from
  const target = typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') ? from : '/'
  const [mode, setMode] = useState<Mode>('checking')
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .get<SetupStatus>('/api/auth/setup')
      .then((s) => {
        if (cancelled) return
        setMode(s.required ? 'setup' : 'login')
        if (s.required) setUsername('admin')
      })
      .catch(() => {
        if (!cancelled) setMode('login')
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (user) return <Navigate to={target} replace />

  async function onSubmitLogin(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Invalid username or password')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
      navigate(target, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError('Too many attempts — wait a minute and try again')
      } else {
        // The backend deliberately returns one indistinguishable message.
        setError('Invalid username or password')
      }
    } finally {
      setBusy(false)
    }
  }

  async function onSubmitSetup(e: FormEvent) {
    e.preventDefault()
    if (!username.trim()) {
      setError('Pick a username')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const res = await api.post<LoginResponse>(
        '/api/auth/setup',
        { username: username.trim(), password, displayName: displayName.trim() || undefined },
        { auth: false },
      )
      adoptSession(res)
      navigate(target, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Bootstrap (or another browser) beat us to it — fall back to sign-in.
        setMode('login')
        setPassword('')
        setConfirm('')
        setError('Setup is already complete — sign in instead')
      } else if (err instanceof ApiError && err.status === 429) {
        setError('Too many attempts — wait a minute and try again')
      } else if (err instanceof ApiError) {
        setError(err.detail)
      } else {
        setError('Setup failed — is the server reachable?')
      }
    } finally {
      setBusy(false)
    }
  }

  const errorNote = error && (
    <div className="login-error">
      <WarningCircle size={15} weight="fill" />
      {error}
    </div>
  )

  return (
    <div className="login-wrap">
      <div className="login-glow" />
      <svg className="login-trace" viewBox="0 0 900 80" preserveAspectRatio="none">
        <path
          d="M0 40 H210 l14 0 l10 -30 l14 54 l12 -26 H460 l16 0 l10 -26 l14 40 l10 -12 H900"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>

      <form className="login-card" onSubmit={mode === 'setup' ? onSubmitSetup : onSubmitLogin}>
        <span className="corner tl" />
        <span className="corner tr" />
        <span className="corner bl" />
        <span className="corner br" />

        <div className="login-brand">
          <LogoMark
            height={28}
            style={{ filter: 'drop-shadow(0 0 6px color-mix(in srgb, var(--accent) 50%, transparent))' }}
          />
          <div>
            <div className="brand-name">Loopback</div>
            <div className="brand-sub">SELF-HOSTED TRAINING</div>
          </div>
        </div>

        {mode === 'setup' && (
          <>
            <div className="login-heading">Create your admin account</div>
            <div className="login-note">
              Fresh install — this account manages members and settings. Athlete accounts are
              created by the admin afterwards.
            </div>

            <div className="login-field-label">Username</div>
            <input
              className="login-input"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <div className="login-field-label">Display name (optional)</div>
            <input
              className="login-input"
              type="text"
              autoComplete="name"
              placeholder="Admin"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
            <div className="login-field-label">Password</div>
            <input
              className="login-input"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <div className="login-field-label">Confirm password</div>
            <input
              className="login-input"
              type="password"
              autoComplete="new-password"
              style={{ marginBottom: 8 }}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />

            {errorNote}

            <button className="login-submit" type="submit" disabled={busy}>
              {busy ? 'Creating account…' : 'Create admin account'}
            </button>

            <div className="login-foot">
              <LockKey size={14} />
              This screen closes for good once the admin account exists
            </div>
          </>
        )}

        {mode === 'login' && (
          <>
            <div className="login-field-label">Username</div>
            <input
              className="login-input"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <div className="login-field-label">Password</div>
            <input
              className="login-input"
              type="password"
              autoComplete="current-password"
              style={{ marginBottom: 8 }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />

            {errorNote}

            <button className="login-submit" type="submit" disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>

            <div className="login-foot">
              <LockKey size={14} />
              Accounts are created by your household admin
            </div>
          </>
        )}
      </form>
    </div>
  )
}

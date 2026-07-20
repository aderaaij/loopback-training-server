import { LockKey, WarningCircle } from '@phosphor-icons/react'
import { LogoMark } from '../components/LogoMark'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import '../styles/login.css'

export function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Invalid username or password')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
      navigate('/', { replace: true })
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

      <form className="login-card" onSubmit={onSubmit}>
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

        {error && (
          <div className="login-error">
            <WarningCircle size={15} weight="fill" />
            {error}
          </div>
        )}

        <button className="login-submit" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <div className="login-foot">
          <LockKey size={14} />
          Accounts are created by your household admin
        </div>
      </form>
    </div>
  )
}

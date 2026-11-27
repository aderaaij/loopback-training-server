import { LockKey, WarningCircle } from '@phosphor-icons/react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { LogoMark } from '../components/LogoMark'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useAnswerOAuthRequest, useOAuthRequest } from '../lib/queries'
import '../styles/login.css'

/** https anywhere, or http to this computer: the only places an answer may go. */
function isSafeReturn(address: string): boolean {
  try {
    const url = new URL(address)
    if (url.protocol === 'https:') return true
    return url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  } catch {
    return false
  }
}

/**
 * Where an assistant sends the athlete to approve its connection to the coach
 * (OAuth; the server side is backend/app/oauth.py). It sits outside the
 * dashboard's layout on purpose: the athlete arrives here from another app, in
 * the middle of that app's setup, and goes straight back.
 *
 * Whoever sent the link chose what it says about the app, so the page leads
 * with the one thing they could not choose: the host the answer goes to.
 */
export function OAuthConsent() {
  const { user, logout } = useAuth()
  const [params] = useSearchParams()
  const requestId = params.get('request')
  const request = useOAuthRequest(requestId)
  const answer = useAnswerOAuthRequest(requestId)
  // Kept after the answer is sent: the browser takes a moment to leave, and
  // the buttons must not come back to life in it.
  const [leaving, setLeaving] = useState(false)

  const [refused, setRefused] = useState(false)

  function send(decision: 'approve' | 'deny') {
    answer.mutate(decision, {
      onSuccess: ({ redirectTo }) => {
        // The server only ever stores such an address (redirect_allowed in
        // backend/app/oauth.py). Checked again here because this line is
        // where it would hurt: an address like `javascript:` handed to the
        // browser runs as this page, with the athlete's token in reach.
        if (!isSafeReturn(redirectTo)) {
          setRefused(true)
          return
        }
        setLeaving(true)
        window.location.assign(redirectTo)
      },
    })
  }

  const data = request.data
  const isAdmin = user?.role === 'admin'
  const busy = answer.isPending || leaving || refused
  // The app's own name only where the server vouches for the host behind it.
  const name = data ? (data.recognised && data.clientName ? data.clientName : data.clientHost) : ''
  const gone = !requestId || (request.error instanceof ApiError && request.error.status === 404)

  return (
    <div className="login-wrap">
      <div className="login-glow" />
      <div className="login-card consent-card">
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

        {request.isPending && requestId && <div className="login-note">Loading…</div>}

        {gone && (
          <>
            <div className="login-heading">This request is no longer open</div>
            <div className="login-note" style={{ marginBottom: 0 }}>
              It has expired or was already answered. Go back to your assistant and connect again.
            </div>
          </>
        )}

        {request.error != null && !gone && (
          <div className="login-error" style={{ margin: 0 }}>
            <WarningCircle size={15} weight="fill" />
            Could not load the request. Is the server reachable?
          </div>
        )}

        {data && isAdmin && (
          <>
            <div className="login-heading">Sign in as the athlete</div>
            <div className="login-note">
              You are signed in as <strong>{user?.username}</strong>, an admin account. Admins manage members and have
              no training data, so there is nothing here for {name} to read.
            </div>
            <button className="login-submit" type="button" onClick={() => void logout()}>
              Sign out and switch account
            </button>
          </>
        )}

        {data && !isAdmin && (
          <>
            <div className="login-heading">Connect {name} to your coach?</div>
            <div className="login-note">
              <strong>{name}</strong> is asking to act as your coach, as <strong>{user?.displayName || user?.username}</strong>.
            </div>

            <ul className="consent-list">
              <li>Read your workouts, plans and notes, and the health data you share with your coach in the app</li>
              <li>Create and change plans, workouts for your watch and notes</li>
            </ul>

            {!data.recognised && (
              <div className="consent-warn">
                <WarningCircle size={15} weight="fill" />
                <span>
                  Loopback does not know <strong>{data.clientHost}</strong>
                  {data.clientName ? <> (it calls itself “{data.clientName}”)</> : null}. Continue only if this is the
                  app you are setting up.
                </span>
              </div>
            )}

            <div className="login-note" style={{ marginBottom: 0 }}>
              Allow this only if you started it yourself a moment ago. You will be sent back to{' '}
              <strong>{data.loopback ? 'an app on this computer' : data.redirectHost}</strong>, and can disconnect it
              at any time under Settings.
            </div>

            {answer.error != null && (
              <div className="login-error" style={{ margin: '14px 2px 0' }}>
                <WarningCircle size={15} weight="fill" />
                {answer.error instanceof ApiError ? answer.error.detail : 'Something went wrong. Try again.'}
              </div>
            )}
            {refused && (
              <div className="login-error" style={{ margin: '14px 2px 0' }}>
                <WarningCircle size={15} weight="fill" />
                This app asked to be answered at an address Loopback will not open. Nothing was sent.
              </div>
            )}

            <div className="consent-actions">
              <button className="consent-cancel" type="button" disabled={busy} onClick={() => send('deny')}>
                Cancel
              </button>
              <button className="login-submit" type="button" disabled={busy} onClick={() => send('approve')}>
                {leaving ? 'Returning…' : 'Allow'}
              </button>
            </div>

            <div className="login-foot">
              <LockKey size={14} />
              {name} never sees your password
            </div>
          </>
        )}
      </div>
    </div>
  )
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, authStorage, setUnauthorizedHandler } from './api'
import type { AuthUser, LoginResponse } from './types'
import { clearUnits, syncUnits } from './units'

interface AuthState {
  user: AuthUser | null
  tokenId: string | null
  login: (username: string, password: string) => Promise<void>
  /** Store an already-minted session (e.g. the first-run setup response). */
  adoptSession: (res: LoginResponse) => void
  logout: () => Promise<void>
  /** Clear local state without calling the API (used on 401). */
  reset: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() =>
    authStorage.token ? authStorage.getUser<AuthUser>() : null,
  )
  const [tokenId, setTokenId] = useState<string | null>(() => authStorage.tokenId)

  const reset = useCallback(() => {
    authStorage.clear()
    clearUnits()
    setUser(null)
    setTokenId(null)
  }, [])

  // Units belong to the account: fetch them whenever a session appears, on
  // page load or after login.
  const userId = user?.id
  useEffect(() => {
    if (userId) void syncUnits()
  }, [userId])

  useEffect(() => {
    setUnauthorizedHandler(reset)
  }, [reset])

  const adoptSession = useCallback((res: LoginResponse) => {
    authStorage.save(res.token, res.tokenId, res.user)
    setUser(res.user)
    setTokenId(res.tokenId)
  }, [])

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api.post<LoginResponse>(
        '/api/auth/login',
        { username, password, deviceName: 'Web dashboard' },
        { auth: false },
      )
      adoptSession(res)
    },
    [adoptSession],
  )

  const logout = useCallback(async () => {
    const id = authStorage.tokenId
    try {
      if (id) await api.delete(`/api/auth/tokens/${id}`)
    } catch {
      // Token already dead server-side — local cleanup below is what matters.
    }
    reset()
  }, [reset])

  const value = useMemo(
    () => ({ user, tokenId, login, adoptSession, logout, reset }),
    [user, tokenId, login, adoptSession, logout, reset],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}

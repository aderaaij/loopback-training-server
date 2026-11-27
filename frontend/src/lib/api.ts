/**
 * Thin typed fetch wrapper. Bearer auth, JSON, and the 401 contract:
 * any 401 means the token is dead (revoked/expired) — wipe local auth
 * and land on /login.
 */

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

const TOKEN_KEY = 'loopback.token'
const TOKEN_ID_KEY = 'loopback.tokenId'
const USER_KEY = 'loopback.user'

export const authStorage = {
  get token(): string | null {
    return localStorage.getItem(TOKEN_KEY)
  },
  get tokenId(): string | null {
    return localStorage.getItem(TOKEN_ID_KEY)
  },
  getUser<T>(): T | null {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    try {
      return JSON.parse(raw) as T
    } catch {
      return null
    }
  },
  save(token: string, tokenId: string, user: unknown) {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(TOKEN_ID_KEY, tokenId)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(TOKEN_ID_KEY)
    localStorage.removeItem(USER_KEY)
  },
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

type Query = Record<string, string | number | boolean | undefined | null>

function buildUrl(path: string, query?: Query): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

async function request<T>(
  method: string,
  path: string,
  opts: { query?: Query; body?: unknown; auth?: boolean; blob?: boolean } = {},
): Promise<T> {
  const { query, body, auth = true, blob = false } = opts
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth) {
    const token = authStorage.token
    if (token) headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(buildUrl(path, query), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401) {
    if (auth) onUnauthorized?.()
    let detail = 'Unauthorized'
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* keep default */
    }
    throw new ApiError(401, detail)
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      /* keep default */
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  if (blob) return (await res.blob()) as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  /** A file behind the bearer token, which a plain link could not send. */
  blob: (path: string, query?: Query) => request<Blob>('GET', path, { query, blob: true }),
  post: <T>(path: string, body?: unknown, opts?: { auth?: boolean }) =>
    request<T>('POST', path, { body, auth: opts?.auth }),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, { body }),
  delete: <T = void>(path: string) => request<T>('DELETE', path),
}

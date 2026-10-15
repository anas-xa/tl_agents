/** Typed fetch wrapper. The session is an httpOnly cookie set by the backend callback. */

export class ApiError extends Error {
  status: number
  code: string
  reference?: string
  details?: Record<string, unknown>
  constructor(status: number, body: { error?: string; message?: string; reference?: string; details?: Record<string, unknown> }) {
    super(body?.message || `HTTP ${status}`)
    this.status = status
    this.code = body?.error || 'ERROR'
    this.reference = body?.reference
    this.details = body?.details
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init
  const res = await fetch(path, {
    credentials: 'include',
    headers: { Accept: 'application/json', ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(headers || {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    ...rest,
  })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = { message: text }
  }
  if (!res.ok) throw new ApiError(res.status, (body || {}) as never)
  return body as T
}

export const get = <T,>(path: string) => api<T>(path)
export const post = <T,>(path: string, json?: unknown) => api<T>(path, { method: 'POST', json })
export const put = <T,>(path: string, json?: unknown) => api<T>(path, { method: 'PUT', json })
export const patch = <T,>(path: string, json?: unknown) => api<T>(path, { method: 'PATCH', json })
export const del = <T,>(path: string, json?: unknown) => api<T>(path, { method: 'DELETE', json })

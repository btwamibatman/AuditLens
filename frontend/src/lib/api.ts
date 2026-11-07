/**
 * Единый HTTP-клиент. Все запросы к бэкенду идут через него.
 *
 *   const items = await api.get<Page<Item>>('/items', { query: { q: 'demo' } })
 *   await api.post<Item>('/items', { title: 'New' })
 */

const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api'
const TOKEN_KEY = 'hs_token'

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string | null) => {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  },
}

type Query = Record<string, string | number | boolean | null | undefined>

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  query?: Query
}

function buildUrl(path: string, query?: Query) {
  const url = `${BASE_URL}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

function errorMessage(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  // Ошибки валидации FastAPI: [{loc, msg}, ...]
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`).join('; ')
  }
  return `Request failed (${status})`
}

export async function request<T>(path: string, { body, query, headers, ...init }: RequestOptions = {}): Promise<T> {
  const h = new Headers(headers)
  const token = tokenStore.get()
  if (token) h.set('Authorization', `Bearer ${token}`)

  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    h.set('Content-Type', 'application/json')
    payload = JSON.stringify(body)
  }

  let res: Response
  try {
    res = await fetch(buildUrl(path, query), { ...init, headers: h, body: payload })
  } catch {
    throw new ApiError('Бэкенд недоступен. Запущен ли сервер?', 0)
  }

  if (res.status === 204) return undefined as T
  const isJson = res.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await res.json() : await res.text()

  if (!res.ok) {
    if (res.status === 401 && token) {
      tokenStore.set(null)
      window.dispatchEvent(new Event('auth:logout'))
    }
    throw new ApiError(errorMessage(data, res.status), res.status, data)
  }
  return data as T
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts, method: 'GET' }),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>(path, { ...opts, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>(path, { ...opts, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>(path, { ...opts, method: 'PATCH', body }),
  delete: <T = void>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts, method: 'DELETE' }),
  upload: <T>(path: string, file: File, field = 'file') => {
    const form = new FormData()
    form.append(field, file)
    return request<T>(path, { method: 'POST', body: form })
  },
}

/** Ответ бэкенда для списков (app/core/schemas.py → Page). */
export interface Page<T> {
  items: T[]
  total: number
}

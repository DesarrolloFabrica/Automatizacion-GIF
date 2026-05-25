export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export const BACKEND_CONNECTION_ERROR =
  'No se pudo conectar con el backend. Verifica que FastAPI esté activo.'

export class ApiHttpError extends Error {
  status: number
  response: Response

  constructor(response: Response, message?: string) {
    super(message ?? `Error HTTP ${response.status}`)
    this.name = 'ApiHttpError'
    this.status = response.status
    this.response = response
  }
}

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}${normalizedPath}`
}

export function isMissingJobResponse(response: Response): boolean {
  return response.status === 404 || response.status === 410
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(buildApiUrl(path), init)
  } catch (error) {
    if (error instanceof TypeError) throw new Error(BACKEND_CONNECTION_ERROR, { cause: error })
    throw error
  }
}

export async function readApiErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    return typeof payload.detail === 'string' ? payload.detail : fallback
  } catch {
    return fallback
  }
}

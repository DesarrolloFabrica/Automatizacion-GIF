export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export const BACKEND_CONNECTION_ERROR =
  'No se pudo conectar con el backend. Verifica que FastAPI esté activo.'

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, init)
  } catch (error) {
    if (error instanceof TypeError) throw new Error(BACKEND_CONNECTION_ERROR)
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

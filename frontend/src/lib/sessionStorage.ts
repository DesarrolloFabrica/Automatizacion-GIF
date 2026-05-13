const LOCAL_PACKAGE_SESSION_KEY = 'localPackageJobSession.v2'
const DRIVE_PACKAGE_SESSION_KEY = 'drivePackageJobSession.v2'
const SESSION_TTL_MS = 24 * 60 * 60 * 1000

export type FlowType = 'local' | 'drive'

export interface SessionData {
  jobId: string
  flow: FlowType
  createdAt: number
  updatedAt: number
  prompt?: string
  driveFolderId?: string
}

function isExpired(session: SessionData): boolean {
  return Date.now() - session.updatedAt > SESSION_TTL_MS
}

function loadSession(key: string): SessionData | null {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const session = JSON.parse(raw) as SessionData
    if (!session?.jobId?.trim()) return null
    if (isExpired(session)) return null
    return session
  } catch {
    return null
  }
}

function saveSession(key: string, data: SessionData) {
  const now = Date.now()
  const entry: SessionData = { ...data, createdAt: data.createdAt || now, updatedAt: now }
  sessionStorage.setItem(key, JSON.stringify(entry))
}

function clearSession(key: string) {
  sessionStorage.removeItem(key)
}

export function loadLocalSession(): SessionData | null {
  return loadSession(LOCAL_PACKAGE_SESSION_KEY)
}

export function saveLocalSession(jobId: string, prompt?: string) {
  saveSession(LOCAL_PACKAGE_SESSION_KEY, { jobId, flow: 'local', prompt, createdAt: 0, updatedAt: 0 })
}

export function clearLocalSession() {
  clearSession(LOCAL_PACKAGE_SESSION_KEY)
}

export function loadDriveSession(): SessionData | null {
  return loadSession(DRIVE_PACKAGE_SESSION_KEY)
}

export function saveDriveSession(jobId: string, driveFolderId?: string, prompt?: string) {
  saveSession(DRIVE_PACKAGE_SESSION_KEY, { jobId, flow: 'drive', prompt, driveFolderId, createdAt: 0, updatedAt: 0 })
}

export function clearDriveSession() {
  clearSession(DRIVE_PACKAGE_SESSION_KEY)
}

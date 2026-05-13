const LOCAL_PACKAGE_SESSION_KEY = 'localPackageJobSession.v3'
const DRIVE_PACKAGE_SESSION_KEY = 'drivePackageJobSession.v3'
const SESSION_TTL_MS = 24 * 60 * 60 * 1000

export type FlowType = 'local' | 'drive'

export interface DetectedGranule {
  id: string
  label: string
}

export interface LocalSessionData {
  jobId: string
  flow: 'local'
  createdAt: number
  updatedAt: number
  prompt?: string
  subjectName?: string
  programName?: string
  detectedGranules?: DetectedGranule[]
  previewMessage?: string
  syllabusFileName?: string
}

export interface DriveSessionData {
  jobId: string
  flow: 'drive'
  createdAt: number
  updatedAt: number
  prompt?: string
  driveFolderId?: string
  subjectName?: string
  programName?: string
  detectedGranules?: DetectedGranule[]
  previewMessage?: string
  syllabusFileName?: string
}

export type SessionData = LocalSessionData | DriveSessionData

function isExpired(data: SessionData): boolean {
  return Date.now() - data.updatedAt > SESSION_TTL_MS
}

function loadSession<T extends SessionData>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const data = JSON.parse(raw) as T
    if (!data?.jobId?.trim()) return null
    if (isExpired(data)) return null
    return data
  } catch {
    return null
  }
}

function saveSession(key: string, data: SessionData) {
  const now = Date.now()
  const entry: SessionData = {
    ...data,
    createdAt: data.createdAt || now,
    updatedAt: now,
  }
  sessionStorage.setItem(key, JSON.stringify(entry))
}

function clearSession(key: string) {
  sessionStorage.removeItem(key)
}

export function loadLocalSession(): LocalSessionData | null {
  return loadSession<LocalSessionData>(LOCAL_PACKAGE_SESSION_KEY)
}

export function saveLocalSession(data: Partial<LocalSessionData> & { jobId: string }) {
  const existing = loadLocalSession()
  saveSession(LOCAL_PACKAGE_SESSION_KEY, {
    jobId: data.jobId,
    flow: 'local',
    createdAt: existing?.createdAt ?? Date.now(),
    updatedAt: 0,
    prompt: data.prompt ?? existing?.prompt,
    subjectName: data.subjectName ?? existing?.subjectName,
    programName: data.programName ?? existing?.programName,
    detectedGranules: data.detectedGranules ?? existing?.detectedGranules,
    previewMessage: data.previewMessage ?? existing?.previewMessage,
    syllabusFileName: data.syllabusFileName ?? existing?.syllabusFileName,
  })
}

export function clearLocalSession() {
  clearSession(LOCAL_PACKAGE_SESSION_KEY)
}

export function loadDriveSession(): DriveSessionData | null {
  return loadSession<DriveSessionData>(DRIVE_PACKAGE_SESSION_KEY)
}

export function saveDriveSession(data: Partial<DriveSessionData> & { jobId: string }) {
  const existing = loadDriveSession()
  saveSession(DRIVE_PACKAGE_SESSION_KEY, {
    jobId: data.jobId,
    flow: 'drive',
    createdAt: existing?.createdAt ?? Date.now(),
    updatedAt: 0,
    prompt: data.prompt ?? existing?.prompt,
    driveFolderId: data.driveFolderId ?? existing?.driveFolderId,
    subjectName: data.subjectName ?? existing?.subjectName,
    programName: data.programName ?? existing?.programName,
    detectedGranules: data.detectedGranules ?? existing?.detectedGranules,
    previewMessage: data.previewMessage ?? existing?.previewMessage,
    syllabusFileName: data.syllabusFileName ?? existing?.syllabusFileName,
  })
}

export function clearDriveSession() {
  clearSession(DRIVE_PACKAGE_SESSION_KEY)
}

/** Pipeline Drive (guiones / materiales desde carpeta Drive). */

export type ScriptsJobStatus = 'queued' | 'running' | 'completed' | 'failed'

export type ScriptsProgressStep =
  | 'pendiente'
  | 'validando datos'
  | 'conectando con drive'
  | 'leyendo granulo'
  | 'generando materiales'
  | 'subiendo archivos'
  | 'finalizado'
  | 'error'

export const SCRIPTS_PIPELINE_STEPS: ScriptsProgressStep[] = [
  'pendiente',
  'validando datos',
  'conectando con drive',
  'leyendo granulo',
  'generando materiales',
  'subiendo archivos',
  'finalizado',
]

export interface DriveUploadLink {
  name: string
  link: string
  kind: 'txt' | 'docx'
}

export interface ScriptsJobStatusResponse {
  jobId: string
  status: ScriptsJobStatus
  progressStep: ScriptsProgressStep | string
  logs: string[]
  driveLinks: DriveUploadLink[]
}

export type ScriptsLocalProgressStep =
  | 'pendiente'
  | 'cargando granulos'
  | 'validando estructura'
  | 'leyendo granulos'
  | 'generando txt'
  | 'generando docx'
  | 'preparando descargas'
  | 'finalizado'
  | 'error'

export const SCRIPTS_LOCAL_PIPELINE_STEPS: ScriptsLocalProgressStep[] = [
  'pendiente',
  'cargando granulos',
  'validando estructura',
  'leyendo granulos',
  'generando txt',
  'generando docx',
  'preparando descargas',
  'finalizado',
]

export interface LocalGeneratedFile {
  name: string
  kind: 'txt' | 'docx'
  sizeBytes: number
}

export interface ScriptsLocalJobStatusResponse {
  jobId: string
  status: ScriptsJobStatus
  progressStep: ScriptsLocalProgressStep | string
  logs: string[]
  files: LocalGeneratedFile[]
}

/** Regex: link de carpeta o open?id= */
const DRIVE_FOLDER_IN_LINK_REGEX = /(?:\/folders\/|id=)([A-Za-z0-9_-]{10,})/
const PURE_DRIVE_ID_REGEX = /^[A-Za-z0-9_-]{10,}$/

export function isValidDriveFolderInput(value: string): boolean {
  const v = value.trim()
  if (!v) return false
  if (PURE_DRIVE_ID_REGEX.test(v)) return true
  return DRIVE_FOLDER_IN_LINK_REGEX.test(v)
}

/** Devuelve el ID detectado o null si el formato no es válido. */
export function extractFolderId(value: string): string | null {
  const v = value.trim()
  if (!v) return null
  const m = v.match(DRIVE_FOLDER_IN_LINK_REGEX)
  if (m) return m[1]
  if (PURE_DRIVE_ID_REGEX.test(v)) return v
  return null
}

export function isDocxFileName(name: string): boolean {
  return name.trim().toLowerCase().endsWith('.docx')
}

export function validateLocalGranulesSelection(files: File[]): { ok: boolean; reason?: string; level?: 'error' | 'warning' | 'success' } {
  if (files.length === 0) {
    return { ok: false, reason: 'Sube los gránulos del curso (4 o 5 archivos .docx).' }
  }
  const hasNonDocx = files.some((file) => !isDocxFileName(file.name))
  if (hasNonDocx) {
    return { ok: false, reason: 'Todos los archivos deben ser .docx.', level: 'error' }
  }
  if (files.length < 4) {
    return { ok: false, reason: 'Faltan archivos. Selecciona al menos 4 gránulos .docx.', level: 'error' }
  }
  if (files.length > 5) {
    return { ok: false, reason: 'Demasiados archivos. Selecciona máximo 5 gránulos .docx.', level: 'error' }
  }
  if (files.length === 4) {
    return { ok: true, reason: 'Tienes 4 gránulos. Es válido, pero lo ideal son 5.', level: 'warning' }
  }
  return { ok: true, reason: 'Estado ideal: 5 gránulos detectados.', level: 'success' }
}

/* --- Tipos antiguos del mock de guiones (referencia) ---
export type ScriptType = 'video' | 'podcast' | 'interactive' | 'guided-class'
export type ScriptGenerationStatus = ...
export const SCRIPT_TYPES = ...
export const SCRIPT_PIPELINE_STEPS = ...
*/

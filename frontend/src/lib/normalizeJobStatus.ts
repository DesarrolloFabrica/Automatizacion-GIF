import type { JobPhaseStatus, JobStatusResponse, PhaseStatus } from '../types/granules'

export type NormalizedJobStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'missing_job'
  | 'recoverable_error'

export type NormalizedPhase =
  | 'syllabus'
  | 'granules'
  | 'txt_docx'
  | 'materials'
  | 'zip'
  | 'drive_upload'

export interface NormalizedPhaseDetails {
  status: PhaseStatus
  files: string[]
  startedAt: string | null
  finishedAt: string | null
}

export interface NormalizedJob {
  jobId: string
  status: NormalizedJobStatus
  currentPhase: NormalizedPhase | 'pending' | 'completed'
  phases: Record<NormalizedPhase, NormalizedPhaseDetails | null>
  availableNextAction: string
  progress: number
  logs: string[]
  outputs: string[]
  errors: string[]
  canContinue: boolean
  canRetry: boolean
  canCancel: boolean
  canDownload: boolean
}

function normalizeBackendStatus(backendStatus: string | undefined): NormalizedJobStatus {
  switch (backendStatus) {
    case 'queued':
      return 'queued'
    case 'running':
      return 'running'
    case 'completed':
      return 'completed'
    case 'failed':
      return 'failed'
    case 'cancelled':
      return 'cancelled'
    case 'missing_job':
      return 'missing_job'
    case 'recoverable_error':
      return 'recoverable_error'
    default:
      return 'idle'
  }
}

function mapCurrentPhase(raw: string | undefined): NormalizedPhase | 'pending' | 'completed' {
  switch (raw) {
    case 'granules':
      return 'granules'
    case 'pipelineLocal':
      return 'txt_docx'
    case 'specializationMaterials':
      return 'materials'
    case 'uploadDrive':
      return 'drive_upload'
    case 'completed':
      return 'completed'
    case 'pending':
    default:
      return 'pending'
  }
}

function extractPhaseDetails(ps: JobPhaseStatus | null, key: string): NormalizedPhaseDetails | null {
  if (!ps) return null
  const entry = (ps as unknown as Record<string, unknown>)[key]
  if (!entry || typeof entry !== 'object') return null
  const e = entry as Record<string, unknown>
  return {
    status: (e.status as PhaseStatus) ?? 'pending',
    files: Array.isArray(e.files) ? (e.files as string[]) : [],
    startedAt: (e.startedAt as string | null) ?? null,
    finishedAt: (e.finishedAt as string | null) ?? null,
  }
}

function calculateProgress(job: NormalizedJob): number {
  if (job.status === 'completed') return 100
  if (job.status === 'failed') return 100
  if (job.status === 'idle') return 0

  const phases = job.phases
  const granules = phases.granules?.status
  const txtDocx = phases.txt_docx?.status
  const materials = phases.materials?.status

  if (granules === 'completed' && txtDocx === 'completed' && materials === 'completed') return 95
  if (materials === 'running') return 70
  if (materials === 'completed') return 85
  if (txtDocx === 'running') return 50
  if (txtDocx === 'completed') return 60
  if (granules === 'running') return 30
  if (granules === 'completed') return 45
  return 10
}

export function normalizeJobStatus(payload: JobStatusResponse): NormalizedJob {
  const status = normalizeBackendStatus(payload.status)
  const currentPhase = mapCurrentPhase(payload.currentPhase)

  const phases: NormalizedJob['phases'] = {
    syllabus: null,
    granules: extractPhaseDetails(payload.phaseStatus, 'granules'),
    txt_docx: extractPhaseDetails(payload.phaseStatus, 'pipelineLocal'),
    materials: extractPhaseDetails(payload.phaseStatus, 'specializationMaterials'),
    zip: null,
    drive_upload: extractPhaseDetails(payload.phaseStatus, 'uploadDrive'),
  }

  const canContinue = status === 'running' || status === 'queued'
  const canRetry = status === 'failed' || status === 'recoverable_error'
  const canCancel = status === 'running' || status === 'queued'
  const canDownload = status === 'completed' || payload.availableNextAction === 'download_package'

  const normalized: NormalizedJob = {
    jobId: payload.jobId,
    status,
    currentPhase,
    phases,
    availableNextAction: payload.availableNextAction ?? 'none',
    progress: 0,
    logs: payload.logs ?? [],
    outputs: payload.files ?? [],
    errors: [],
    canContinue,
    canRetry,
    canCancel,
    canDownload,
  }

  normalized.progress = calculateProgress(normalized)
  return normalized
}

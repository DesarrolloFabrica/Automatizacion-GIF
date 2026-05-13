export type PromptType = 'curso_rapido' | 'pregrado' | 'especializacion' | 'maestria' | 'diplomado' | 'curso_externos_profesional'
export type ScriptType = 'analistas' | 'presentadoras'

export type GenerationStatus =
  | 'pendiente'
  | 'leyendo syllabus'
  | 'detectando estructura temática'
  | 'preparando prompts'
  | 'generando documentos'
  | 'generando gránulos'
  | 'generando txt'
  | 'generando docx'
  | 'generando materiales especialización'
  | 'generando materiales'
  | 'organizando archivos'
  | 'finalizado'
  | 'error'
  | 'cancelado'
  | 'missing_job'
  | 'recoverable_error'

export interface GranuleTopic {
  id: string
  label: string
}

export interface PreviewTopicResponse {
  index: number
  title: string
}

export interface DetectedCourse {
  asignatura: string
  programa: string
  escuela: string
  semestre: string
  temas: string[]
}

export interface SyllabusPreviewResponse {
  fileName: string
  subjectName: string
  programName: string
  detectedTopics: PreviewTopicResponse[]
  totalGranules: number
  coursesDetected: DetectedCourse[]
  selectedCourse?: DetectedCourse | null
}

export type BackendJobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type PhaseStatus = 'pending' | 'ready' | 'running' | 'completed' | 'failed' | 'cancelled' | 'stale' | 'skipped'
export type AvailableNextAction =
  | 'generate_granules'
  | 'generate_pipeline_local'
  | 'generate_specialization_materials'
  | 'download_package'
  | 'retry_current_phase'
  | 'none'

export interface PhaseStatusDetails {
  status: PhaseStatus
  startedAt: string | null
  finishedAt: string | null
  files: string[]
}

export interface JobPhaseStatus {
  jobId: string
  granules: PhaseStatusDetails
  pipelineLocal: PhaseStatusDetails
  specializationMaterials: PhaseStatusDetails
  materials?: PhaseStatusDetails
  uploadDrive?: PhaseStatusDetails
}

export interface DrivePhaseSyncEntry {
  status: PhaseStatus
  error?: string | null
  updatedAt?: string | null
}

export interface DriveSyncSnapshot {
  drivePhasedSync: boolean
  driveParentFolderId?: string | null
  driveWorkspaceFolderId?: string | null
  driveRootFolderId?: string | null
  drivePackageFolderId?: string | null
  drivePackageUrl?: string | null
  driveFoldersCreated: number
  driveFoldersReused: number
  driveFilesUploaded: number
  driveFilesOverwritten: number
  drivePhaseStatus: Record<string, DrivePhaseSyncEntry> | null
  driveLastError?: string | null
}

export interface CategoryDeliverable {
  nn: string
  name: string
  section: string
}

export interface CategoryConfig {
  key: PromptType
  label: string
  enabledForPackage: boolean
  disabledReason: string
  materialsDir: string
  materialsRoute: string
  expectedGranules: number
  expectedMaterialsPerGranule: number
  deliverables: CategoryDeliverable[]
  reservedDeliverables: CategoryDeliverable[]
}

export interface JobStatusResponse {
  jobId: string
  status: BackendJobStatus
  progressStep: GenerationStatus
  logs: string[]
  files: string[]
  granulesStatus: PhaseStatus
  pipelineLocalStatus: PhaseStatus
  specializationMaterialsStatus: PhaseStatus
  uploadDriveStatus?: PhaseStatus
  currentPhase: string
  availableNextAction: AvailableNextAction
  phaseStatus: JobPhaseStatus | null
  driveSync?: DriveSyncSnapshot | null
  categoryKey?: PromptType | string | null
}

export interface DriveUploadResponse {
  jobId: string
  status: string
  folderId: string
  folderLink: string
  filesUploaded: number
  filesOverwritten: number
  filesSkipped: number
  foldersCreated: number
  foldersReused: number
}

export interface MaterialFile {
  granule: string
  name: string
  relativePath: string
}

export interface GranuleMaterials {
  granuleCode: string
  granuleFolder: string
  files: MaterialFile[]
  totalMaterials: number
}

export interface GranuleProgress {
  code: string
  tema: string
  guion: boolean
  txt: boolean
  docx: boolean
  materiales: number
  materialesTotal: number
}

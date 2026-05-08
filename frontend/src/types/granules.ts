export type PromptType = 'pregrado' | 'especializacion' | 'maestria' | 'diplomado'
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
  | 'organizando archivos'
  | 'finalizado'
  | 'error'

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

export type BackendJobStatus = 'queued' | 'running' | 'completed' | 'failed'
export type PhaseStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
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
  currentPhase: string
  availableNextAction: AvailableNextAction
  phaseStatus: JobPhaseStatus | null
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

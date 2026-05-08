export type PromptType = 'pregrado' | 'especializacion' | 'maestria' | 'diplomado'
export type ScriptType = 'analistas' | 'presentadoras'

export type GenerationStatus =
  | 'pendiente'
  | 'leyendo syllabus'
  | 'detectando estructura temática'
  | 'preparando prompts'
  | 'generando documentos'
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

export interface SyllabusPreviewResponse {
  fileName: string
  subjectName: string
  programName: string
  detectedTopics: PreviewTopicResponse[]
  totalGranules: number
}

export type BackendJobStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface JobStatusResponse {
  jobId: string
  status: BackendJobStatus
  progressStep: GenerationStatus
  logs: string[]
  files: string[]
}

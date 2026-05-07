export type ScriptType = 'video' | 'podcast' | 'interactive' | 'guided-class'

export type ScriptGenerationStatus =
  | 'pendiente'
  | 'leyendo gránulo'
  | 'extrayendo estructura'
  | 'preparando prompt'
  | 'generando guion'
  | 'finalizado'
  | 'error'

export const SCRIPT_TYPES: Array<{ value: ScriptType; label: string; description: string }> = [
  { value: 'video', label: 'Video educativo', description: 'Guion estructurado para video con escenas y narración.' },
  { value: 'podcast', label: 'Podcast', description: 'Guion conversacional con segmentos y transiciones.' },
  { value: 'interactive', label: 'Recurso interactivo', description: 'Guion con actividades, preguntas y retroalimentación.' },
  { value: 'guided-class', label: 'Clase guiada', description: 'Guion de clase con objetivos, desarrollo y cierre.' },
]

export const SCRIPT_PIPELINE_STEPS: ScriptGenerationStatus[] = [
  'pendiente',
  'leyendo gránulo',
  'extrayendo estructura',
  'preparando prompt',
  'generando guion',
  'finalizado',
]
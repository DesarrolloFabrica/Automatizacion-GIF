import type { GranuleTopic, GenerationStatus } from '../types/granules'

export const DEFAULT_MOCK_GRANULES: GranuleTopic[] = [
  { id: 'G1', label: 'Introducción a los Métodos Numéricos y su Aplicación' },
  { id: 'G2', label: 'Métodos de Resolución de Ecuaciones No Lineales' },
  { id: 'G3', label: 'Interpolación y Ajuste de Curvas' },
  { id: 'G4', label: 'Integración y Diferenciación Numérica' },
  { id: 'G5', label: 'Solución de Sistemas de Ecuaciones Lineales' },
]

export const PIPELINE_STEPS: GenerationStatus[] = [
  'pendiente',
  'leyendo syllabus',
  'detectando estructura temática',
  'preparando prompts',
  'generando documentos',
  'finalizado',
]

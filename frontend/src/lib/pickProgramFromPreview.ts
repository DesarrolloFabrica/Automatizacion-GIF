import type { SyllabusPreviewResponse } from '../types/granules'

/** Une programName (camelCase o snake_case), selectedCourse o el primer curso con programa. */
export function pickProgramFromPreview(preview: SyllabusPreviewResponse): string {
  const r = preview as unknown as Record<string, unknown>
  const direct = r.programName ?? r.program_name
  if (typeof direct === 'string' && direct.trim()) return direct.trim()
  const sc = preview.selectedCourse?.programa
  if (typeof sc === 'string' && sc.trim()) return sc.trim()
  const fromCourse = preview.coursesDetected?.find((c) => (c.programa ?? '').trim())?.programa
  if (typeof fromCourse === 'string' && fromCourse.trim()) return fromCourse.trim()
  return ''
}

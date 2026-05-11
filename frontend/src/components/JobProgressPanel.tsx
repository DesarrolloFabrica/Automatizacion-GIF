import type { CategoryDeliverable, GenerationStatus, GranuleTopic } from '../types/granules'

const PHASES = [
  { key: 'syllabus', label: 'Syllabus recibido' },
  { key: 'granules', label: 'Gránulos G1-G5' },
  { key: 'documents', label: 'TXT/DOCX académicos' },
  { key: 'materials', label: 'Recursos complementarios' },
  { key: 'package', label: 'ZIP final' },
] as const

interface JobProgressPanelProps {
  status: GenerationStatus
  logs: string[]
  granules: GranuleTopic[]
  isGenerating: boolean
  isError: boolean
  generatedFilesCount: number
  totalMaterialsExpected?: number
  materialsPerGranule?: number
  deliverables?: CategoryDeliverable[]
  categoryLabel?: string
  backendCurrentPhase?: string
  onRetry: () => void
}

interface GranuleProgressState {
  code: string
  label: string
  materials: number
}

function normalizeLog(line: string): string {
  return line.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
}

function getLatestRelevantLog(logs: string[]): string {
  const ignored = ['ejecutando comando:', 'proceso finalizado con codigo:']
  return [...logs].reverse().find((line) => {
    const normalized = normalizeLog(line)
    return line.trim() && !ignored.some((item) => normalized.includes(item))
  }) ?? 'Esperando información del proceso...'
}

function inferCurrentPhase(status: GenerationStatus, logs: string[]): string {
  const latest = normalizeLog(getLatestRelevantLog(logs))
  if (status === 'error') return 'error'
  if (status === 'finalizado') return 'package'
  if (latest.includes('material guardado') || latest.includes('generando material') || status === 'generando materiales especialización' || status === 'generando materiales') return 'materials'
  if (latest.includes('generando docx') || latest.includes('generando txt') || status === 'generando docx' || status === 'generando txt') return 'documents'
  if (latest.includes('guardado:') || latest.includes('generando documento') || status === 'generando gránulos' || status === 'generando documentos') return 'granules'
  if (latest.includes('summary guardado') || latest.includes('manifest guardado') || status === 'organizando archivos') return 'package'
  return 'syllabus'
}

function mapBackendPhase(backendCurrentPhase?: string): string | null {
  if (backendCurrentPhase === 'completed') return 'package'
  if (backendCurrentPhase === 'specializationMaterials') return 'materials'
  if (backendCurrentPhase === 'pipelineLocal') return 'documents'
  if (backendCurrentPhase === 'granules') return 'granules'
  return null
}

function phaseIndex(key: string): number {
  return PHASES.findIndex((phase) => phase.key === key)
}

function parseProgress(logs: string[], granules: GranuleTopic[]) {
  const granuleMap = new Map<string, GranuleProgressState>()
  const baseGranules = granules.length > 0
    ? granules
    : Array.from({ length: 5 }, (_, index) => ({ id: `G${index + 1}`, label: `Gránulo ${index + 1}` }))

  baseGranules.forEach((granule) => {
    granuleMap.set(granule.id, {
      code: granule.id,
      label: granule.label,
      materials: 0,
    })
  })

  const savedMaterials = new Set<string>()
  const generatedGranules = new Set<string>()
  let currentGranule = ''
  let currentMaterial = ''
  let errors = 0
  let masterTxt = false
  let masterDocx = false

  for (const line of logs) {
    const normalized = normalizeLog(line)
    const generatingGranule = line.match(/Generando documento\s+(\d+)\s*\/\s*\d+/i)
    if (generatingGranule) {
      currentGranule = `G${generatingGranule[1]}`
    }

    const savedGranule = line.match(/Guardado:\s*.*?(G\d+)[^\\/]*\.docx/i)
    if (savedGranule) {
      generatedGranules.add(savedGranule[1])
    }

    if ((normalized.includes('generando txt') || normalized.includes('fase 1: generacion de txt')) && !normalized.includes('drive')) {
      masterTxt = true
    }

    if ((normalized.includes('generando docx') || normalized.includes('fase 2: generacion de docx')) && !normalized.includes('drive')) {
      masterDocx = true
    }

    const generatingMaterial = line.match(/Generando material:\s*(\d+)\s+(G\d+)/i)
    if (generatingMaterial) {
      currentMaterial = generatingMaterial[1]
      currentGranule = generatingMaterial[2]
    }

    const savedMaterial = line.match(/Material guardado:\s*(\d+)_(G\d+)_.*?\.docx/i)
    if (savedMaterial) {
      const key = `${savedMaterial[2]}-${savedMaterial[1]}`
      savedMaterials.add(key)
      const state = granuleMap.get(savedMaterial[2])
      if (state) state.materials = Math.max(state.materials, [...savedMaterials].filter((item) => item.startsWith(`${savedMaterial[2]}-`)).length)
    }

    if (normalized.includes('error material')) {
      errors += 1
    }
  }

  return {
    granules: Array.from(granuleMap.values()),
    granulesGenerated: generatedGranules.size,
    masterTxt,
    masterDocx,
    materialsSaved: savedMaterials.size,
    currentGranule,
    currentMaterial,
    errors,
  }
}

function calculateProgressPercent(currentPhase: string, materialsSaved: number, totalMaterialsExpected: number, isError: boolean, hasStarted: boolean): number {
  if (!hasStarted) return 0
  if (isError) return 100
  if (currentPhase === 'package') return 100
  if (currentPhase === 'materials') {
    return Math.min(92, 58 + Math.round((materialsSaved / totalMaterialsExpected) * 34))
  }
  const baseByPhase: Record<string, number> = {
    syllabus: 8,
    granules: 34,
    documents: 54,
  }
  return baseByPhase[currentPhase] ?? 12
}

function stepClass(stepKey: string, currentPhase: string, isError: boolean): string {
  if (currentPhase === 'idle') return 'is-pending'
  if (isError && stepKey === currentPhase) return 'is-error'
  const current = phaseIndex(currentPhase)
  const step = phaseIndex(stepKey)
  if (step < current || currentPhase === 'package') return 'is-complete'
  if (step === current) return 'is-active'
  return 'is-pending'
}

function MaterialList({ currentMaterial, deliverables }: { currentMaterial: string; deliverables: CategoryDeliverable[] }) {
  return (
    <div className="job-material-list">
      {deliverables.map((material) => (
        <span key={material.nn} className={material.nn === currentMaterial ? 'is-active' : ''}>
          {material.nn} {material.name.replaceAll('_', ' ').toLowerCase()}
        </span>
      ))}
    </div>
  )
}

function JobProgressPanel({
  status,
  logs,
  granules,
  isGenerating,
  isError,
  generatedFilesCount,
  totalMaterialsExpected = 30,
  materialsPerGranule = 6,
  deliverables = [],
  categoryLabel = 'la categoría',
  backendCurrentPhase,
  onRetry,
}: JobProgressPanelProps) {
  const parsed = parseProgress(logs, granules)
  const hasStarted = isGenerating || logs.length > 0 || status !== 'pendiente' || Boolean(backendCurrentPhase && backendCurrentPhase !== 'pending')
  const currentPhase = hasStarted ? mapBackendPhase(backendCurrentPhase) ?? inferCurrentPhase(status, logs) : 'idle'
  const latestLog = hasStarted ? getLatestRelevantLog(logs) : 'Listo para iniciar. Carga o valida el syllabus y ejecuta el paquete completo.'
  const progressPercent = calculateProgressPercent(currentPhase, parsed.materialsSaved, totalMaterialsExpected, isError, hasStarted)
  const currentMaterialName = parsed.currentMaterial ? deliverables.find((material) => material.nn === parsed.currentMaterial)?.name.replaceAll('_', ' ').toLowerCase() ?? '' : ''
  const isCompleted = status === 'finalizado'
  const completedTitle = currentPhase === 'package'
    ? 'Paquete listo para descargar'
    : currentPhase === 'documents'
      ? 'TXT y DOCX académicos listos'
      : 'Gránulos listos para revisar'

  return (
    <section className={`job-progress-panel ${isError ? 'is-error' : ''} ${isCompleted ? 'is-complete' : ''}`}>
      <div className="job-progress-header">
        <div>
          <span className="job-progress-kicker">ESTADO DEL PAQUETE</span>
          <h3>{isError ? 'Generación detenida' : isCompleted ? completedTitle : isGenerating ? 'Sistema procesando' : granules.length > 0 ? 'Syllabus listo' : 'Listo para iniciar'}</h3>
          <p>{isError ? 'Revisa el último evento y vuelve a intentar.' : isCompleted ? 'Los entregables ya están disponibles.' : isGenerating ? 'La fase activa se actualiza con los eventos del job.' : 'Sin progreso hasta iniciar un job real.'}</p>
        </div>
        <div className="job-progress-percent">{progressPercent}%</div>
      </div>

      <div className="job-progress-bar" aria-label={`Progreso ${progressPercent}%`}>
        <div style={{ width: `${progressPercent}%` }} />
      </div>

      <div className="job-progress-summary-grid">
        <div>
          <span>Fase actual</span>
          <strong>{currentPhase === 'idle' ? 'Pendiente' : PHASES.find((phase) => phase.key === currentPhase)?.label ?? status}</strong>
        </div>
        <div>
          <span>Gránulos</span>
          <strong>{parsed.granulesGenerated}/{granules.length || 5}</strong>
        </div>
        <div>
          <span>Recursos</span>
          <strong>{parsed.materialsSaved}/{totalMaterialsExpected}</strong>
        </div>
        <div>
          <span>Archivos</span>
          <strong>{generatedFilesCount}</strong>
        </div>
      </div>

      <div className="job-progress-steps">
        {PHASES.map((phase) => (
          <div key={phase.key} className={`job-progress-step ${stepClass(phase.key, currentPhase, isError)}`}>
            <span />
            <p>{phase.label}</p>
          </div>
        ))}
      </div>

      {currentPhase === 'materials' && (
        <div className="job-material-current-card">
          <div>
            <span>Generando materiales de {categoryLabel}</span>
            <strong>{parsed.currentGranule && currentMaterialName ? `${parsed.currentGranule} · ${parsed.currentMaterial} ${currentMaterialName}` : 'Preparando materiales'}</strong>
          </div>
          <p>Materiales generados: {parsed.materialsSaved}/{totalMaterialsExpected}</p>
          <MaterialList currentMaterial={parsed.currentMaterial} deliverables={deliverables} />
        </div>
      )}

      <div className="job-granule-checklist" aria-label="Progreso por gránulo">
        {parsed.granules.map((granule) => (
          <article key={granule.code} className="job-granule-card">
            <div className="job-granule-title">
              <strong>{granule.code}</strong>
              <span title={granule.label}>{granule.label}</span>
            </div>
            <div className="job-granule-material-progress">
              <div>
                <span>Materiales de {categoryLabel}</span>
                <strong>{granule.materials}/{materialsPerGranule}</strong>
              </div>
              <div className="job-granule-mini-bar">
                <span style={{ width: `${Math.min(100, materialsPerGranule ? (granule.materials / materialsPerGranule) * 100 : 0)}%` }} />
              </div>
              <p className={granule.materials >= materialsPerGranule ? 'is-complete' : granule.materials > 0 ? 'is-active' : 'is-pending'}>
                {granule.materials >= materialsPerGranule ? 'Completado' : granule.materials > 0 ? 'En proceso' : 'Pendiente'}
              </p>
            </div>
          </article>
        ))}
      </div>

      <div className="job-latest-log">
        <span>Último evento</span>
        <code>{latestLog}</code>
      </div>

      {logs.length > 0 && (
        <details className="job-logs-details">
          <summary>Ver logs ({logs.length})</summary>
          <pre>{logs.slice(-24).join('\n')}</pre>
        </details>
      )}

      {isError && (
        <button type="button" className="secondary-button link-button" onClick={onRetry}>
          Intentar nuevamente
        </button>
      )}

      {isCompleted && (
        <div className="job-final-summary">
          <span>Gránulos generados: {granules.length}</span>
          <span>Materiales {categoryLabel}: {parsed.materialsSaved}</span>
          <span>Errores: {parsed.errors}</span>
          <span>Archivos disponibles: {generatedFilesCount}</span>
        </div>
      )}
    </section>
  )
}

export default JobProgressPanel

import type { GenerationStatus, GranuleTopic } from '../types/granules'

const MATERIAL_NAMES: Record<string, string> = {
  '02': 'Fichas de estudio de evidencia',
  '03': 'Glosario especializado',
  '04': 'Revista dossier',
  '05': 'Infografía modelo o ruta',
  '06': 'Podcast debate experto',
  '07': 'Video solución o procedimiento',
}

const PHASES = [
  { key: 'syllabus', label: 'Syllabus recibido' },
  { key: 'granules', label: 'Generando gránulos' },
  { key: 'txt', label: 'Generando TXT maestro' },
  { key: 'docx', label: 'Generando DOCX maestro' },
  { key: 'materials', label: 'Generando materiales de Especialización' },
  { key: 'organizing', label: 'Organizando archivos' },
  { key: 'package', label: 'Finalizando paquete descargable' },
] as const

interface JobProgressPanelProps {
  status: GenerationStatus
  logs: string[]
  granules: GranuleTopic[]
  isGenerating: boolean
  isError: boolean
  generatedFilesCount: number
  totalMaterialsExpected?: number
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
  if (latest.includes('material guardado') || latest.includes('generando material') || status === 'generando materiales especialización') return 'materials'
  if (latest.includes('generando docx') || status === 'generando docx') return 'docx'
  if (latest.includes('generando txt') || status === 'generando txt') return 'txt'
  if (latest.includes('guardado:') || latest.includes('generando documento') || status === 'generando gránulos' || status === 'generando documentos') return 'granules'
  if (latest.includes('summary guardado') || latest.includes('manifest guardado') || status === 'organizando archivos') return 'organizing'
  return 'syllabus'
}

function mapBackendPhase(backendCurrentPhase?: string): string | null {
  if (backendCurrentPhase === 'completed') return 'package'
  if (backendCurrentPhase === 'specializationMaterials') return 'materials'
  if (backendCurrentPhase === 'pipelineLocal') return 'docx'
  if (backendCurrentPhase === 'granules') return 'granules'
  return null
}

function phaseIndex(key: string): number {
  return PHASES.findIndex((phase) => phase.key === key)
}

function parseProgress(logs: string[], granules: GranuleTopic[]) {
  const granuleMap = new Map<string, GranuleProgressState>()
  granules.forEach((granule) => {
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

function calculateProgressPercent(currentPhase: string, materialsSaved: number, totalMaterialsExpected: number, isError: boolean): number {
  if (isError) return 100
  if (currentPhase === 'package') return 100
  if (currentPhase === 'materials') {
    return Math.min(92, 58 + Math.round((materialsSaved / totalMaterialsExpected) * 34))
  }
  const baseByPhase: Record<string, number> = {
    syllabus: 8,
    granules: 34,
    txt: 44,
    docx: 54,
    organizing: 94,
  }
  return baseByPhase[currentPhase] ?? 12
}

function stepClass(stepKey: string, currentPhase: string, isError: boolean): string {
  if (isError && stepKey === currentPhase) return 'is-error'
  const current = phaseIndex(currentPhase)
  const step = phaseIndex(stepKey)
  if (step < current || currentPhase === 'package') return 'is-complete'
  if (step === current) return 'is-active'
  return 'is-pending'
}

function MaterialList({ currentMaterial }: { currentMaterial: string }) {
  return (
    <div className="job-material-list">
      {Object.entries(MATERIAL_NAMES).map(([code, name]) => (
        <span key={code} className={code === currentMaterial ? 'is-active' : ''}>
          {code} {name}
        </span>
      ))}
    </div>
  )
}

function globalItemClass(isComplete: boolean, isActive: boolean): string {
  if (isComplete) return 'is-complete'
  if (isActive) return 'is-active'
  return 'is-pending'
}

function JobProgressPanel({
  status,
  logs,
  granules,
  isGenerating,
  isError,
  generatedFilesCount,
  totalMaterialsExpected = 30,
  backendCurrentPhase,
  onRetry,
}: JobProgressPanelProps) {
  if (!isGenerating && status === 'pendiente' && logs.length === 0) return null

  const parsed = parseProgress(logs, granules)
  const currentPhase = mapBackendPhase(backendCurrentPhase) ?? inferCurrentPhase(status, logs)
  const latestLog = getLatestRelevantLog(logs)
  const progressPercent = calculateProgressPercent(currentPhase, parsed.materialsSaved, totalMaterialsExpected, isError)
  const currentMaterialName = parsed.currentMaterial ? MATERIAL_NAMES[parsed.currentMaterial] : ''
  const isCompleted = status === 'finalizado'
  const completedTitle = currentPhase === 'package'
    ? 'Paquete listo para descargar'
    : currentPhase === 'docx'
      ? 'TXT y DOCX académicos listos'
      : 'Gránulos listos para revisar'

  return (
    <section className={`job-progress-panel ${isError ? 'is-error' : ''} ${isCompleted ? 'is-complete' : ''}`}>
      <div className="job-progress-header">
        <div>
          <span className="job-progress-kicker">ESTADO DEL JOB</span>
          <h3>{isError ? 'La generación necesita revisión' : isCompleted ? completedTitle : 'Ejecutando fase seleccionada'}</h3>
          <p>{isError ? 'Se detuvo el proceso. Revisa el último log y vuelve a intentar.' : isCompleted ? 'Revisa los resultados temporales y continúa con la siguiente fase cuando estés listo.' : 'No cierres esta ventana mientras se generan los archivos.'}</p>
        </div>
        <div className="job-progress-percent">{progressPercent}%</div>
      </div>

      <div className="job-progress-bar" aria-label={`Progreso ${progressPercent}%`}>
        <div style={{ width: `${progressPercent}%` }} />
      </div>

      <div className="job-progress-summary-grid">
        <div>
          <span>Fase actual</span>
          <strong>{PHASES.find((phase) => phase.key === currentPhase)?.label ?? status}</strong>
        </div>
        <div>
          <span>Material actual</span>
          <strong>{parsed.currentGranule && currentMaterialName ? `${parsed.currentGranule} · ${parsed.currentMaterial} ${currentMaterialName}` : 'Pendiente'}</strong>
        </div>
        <div>
          <span>Materiales generados</span>
          <strong>{parsed.materialsSaved}/{totalMaterialsExpected}</strong>
        </div>
        <div>
          <span>Tiempo estimado</span>
          <strong>{isCompleted ? 'Finalizado' : '30-45 min aprox.'}</strong>
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

      <div className="job-global-pipeline" aria-label="Progreso global del pipeline">
        <article className={globalItemClass(true, currentPhase === 'syllabus')}>
          <span>Syllabus recibido</span>
          <strong>Listo</strong>
        </article>
        <article className={globalItemClass(parsed.granulesGenerated >= granules.length && granules.length > 0, currentPhase === 'granules')}>
          <span>Gránulos generados</span>
          <strong>{parsed.granulesGenerated}/{granules.length || 5}</strong>
        </article>
        <article className={globalItemClass(parsed.masterTxt || phaseIndex(currentPhase) > phaseIndex('txt'), currentPhase === 'txt')}>
          <span>TXT maestro</span>
          <strong>{parsed.masterTxt || phaseIndex(currentPhase) > phaseIndex('txt') ? 'En proceso / listo' : 'Pendiente'}</strong>
        </article>
        <article className={globalItemClass(parsed.masterDocx || phaseIndex(currentPhase) > phaseIndex('docx'), currentPhase === 'docx')}>
          <span>DOCX maestro</span>
          <strong>{parsed.masterDocx || phaseIndex(currentPhase) > phaseIndex('docx') ? 'En proceso / listo' : 'Pendiente'}</strong>
        </article>
        <article className={globalItemClass(currentPhase === 'package', currentPhase === 'organizing')}>
          <span>Paquete descargable</span>
          <strong>{currentPhase === 'package' ? 'Finalizado' : currentPhase === 'organizing' ? 'Organizando' : 'Pendiente'}</strong>
        </article>
      </div>

      {currentPhase === 'materials' && (
        <div className="job-material-current-card">
          <div>
            <span>Generando materiales de Especialización</span>
            <strong>{parsed.currentGranule && currentMaterialName ? `${parsed.currentGranule} · ${parsed.currentMaterial} ${currentMaterialName}` : 'Preparando materiales'}</strong>
          </div>
          <p>Materiales generados: {parsed.materialsSaved}/{totalMaterialsExpected}</p>
          <MaterialList currentMaterial={parsed.currentMaterial} />
        </div>
      )}

      <div className="job-granule-checklist">
        {parsed.granules.map((granule) => (
          <article key={granule.code} className="job-granule-card">
            <div className="job-granule-title">
              <strong>{granule.code}</strong>
              <span title={granule.label}>{granule.label}</span>
            </div>
            <div className="job-granule-material-progress">
              <div>
                <span>Materiales de Especialización</span>
                <strong>{granule.materials}/6</strong>
              </div>
              <div className="job-granule-mini-bar">
                <span style={{ width: `${Math.min(100, (granule.materials / 6) * 100)}%` }} />
              </div>
              <p className={granule.materials >= 6 ? 'is-complete' : granule.materials > 0 ? 'is-active' : 'is-pending'}>
                {granule.materials >= 6 ? 'Completado' : granule.materials > 0 ? 'En proceso' : 'Pendiente'}
              </p>
            </div>
          </article>
        ))}
      </div>

      <div className="job-latest-log">
        <span>Último log relevante</span>
        <code>{latestLog}</code>
      </div>

      {isError && (
        <button type="button" className="secondary-button link-button" onClick={onRetry}>
          Intentar nuevamente
        </button>
      )}

      {isCompleted && (
        <div className="job-final-summary">
          <span>Gránulos generados: {granules.length}</span>
          <span>Materiales especialización: {parsed.materialsSaved}</span>
          <span>Errores: {parsed.errors}</span>
          <span>Archivos disponibles: {generatedFilesCount}</span>
        </div>
      )}
    </section>
  )
}

export default JobProgressPanel

import { useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import { SCRIPTS_LOCAL_PIPELINE_STEPS, validateLocalGranulesSelection } from '../data/mockScripts'
import type { LocalGeneratedFile, ScriptsLocalJobStatusResponse, ScriptsLocalProgressStep } from '../data/mockScripts'
import type { GenerationStatus, JobStatusResponse, PromptType } from '../types/granules'

interface ScriptsViewProps {
  onBack: () => void
}

type ScriptMode = 'granules' | 'txtdocx' | 'materials'

const API_BASE = 'http://localhost:8000'

const promptOptions: Array<{ value: PromptType; label: string }> = [
  { value: 'curso_rapido', label: 'Curso rápido' },
  { value: 'pregrado', label: 'Pregrado' },
  { value: 'diplomado', label: 'Diplomado' },
  { value: 'especializacion', label: 'Especialización' },
  { value: 'curso_externos_profesional', label: 'Curso externos profesional' },
  { value: 'maestria', label: 'Maestría · pendiente de prompt de materiales' },
]

async function readApiErrorDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === 'string') return payload.detail
    return 'Solicitud no válida.'
  } catch {
    return 'Error al procesar la respuesta del servidor.'
  }
}

function statusLabel(status: GenerationStatus | ScriptsLocalProgressStep): string {
  const labels: Record<string, string> = {
    pendiente: 'Listo para iniciar',
    'leyendo syllabus': 'Leyendo syllabus',
    'detectando estructura temática': 'Detectando estructura temática',
    'preparando prompts': 'Preparando prompts',
    'generando documentos': 'Generando gránulos',
    'generando gránulos': 'Generando gránulos',
    'cargando granulos': 'Cargando gránulos',
    'validando estructura': 'Validando estructura',
    'leyendo granulos': 'Leyendo gránulos',
    'generando txt': 'Generando TXT',
    'generando docx': 'Generando DOCX',
    'generando materiales': 'Generando materiales',
    'generando materiales especialización': 'Generando materiales',
    'preparando descargas': 'Preparando descargas',
    finalizado: 'Completado',
    error: 'Error',
  }
  return labels[status] ?? status
}

function ScriptsView({ onBack }: ScriptsViewProps) {
  const [mode, setMode] = useState<ScriptMode>('granules')

  const [syllabusFile, setSyllabusFile] = useState<File | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptType>('especializacion')
  const [granulesJobId, setGranulesJobId] = useState<string | null>(null)
  const [granulesStatus, setGranulesStatus] = useState<GenerationStatus>('pendiente')
  const [granulesMessage, setGranulesMessage] = useState('Sube un syllabus y genera únicamente los gránulos G1-G5.')
  const [granulesLogs, setGranulesLogs] = useState<string[]>([])
  const [granulesFiles, setGranulesFiles] = useState<string[]>([])
  const [isGeneratingGranules, setIsGeneratingGranules] = useState(false)
  const granulesPollRef = useRef<number | null>(null)

  const [materialsFile, setMaterialsFile] = useState<File | null>(null)
  const [materialsPrompt, setMaterialsPrompt] = useState<PromptType>('especializacion')
  const [materialsJobId, setMaterialsJobId] = useState<string | null>(null)
  const [materialsStatus, setMaterialsStatus] = useState<GenerationStatus>('pendiente')
  const [materialsMessage, setMaterialsMessage] = useState('Sube un gránulo .docx, elige el nivel y genera sus materiales editoriales.')
  const [materialsLogs, setMaterialsLogs] = useState<string[]>([])
  const [materialsFiles, setMaterialsFiles] = useState<string[]>([])
  const [isGeneratingMaterials, setIsGeneratingMaterials] = useState(false)
  const materialsPollRef = useRef<number | null>(null)

  const [localFiles, setLocalFiles] = useState<File[]>([])
  const [localAsignatura, setLocalAsignatura] = useState('')
  const [localPrograma, setLocalPrograma] = useState('')
  const [localStatus, setLocalStatus] = useState<ScriptsLocalProgressStep>('pendiente')
  const [localIsGenerating, setLocalIsGenerating] = useState(false)
  const [localMessage, setLocalMessage] = useState('Sube G1-G5 en .docx para generar TXT/DOCX académicos.')
  const [localLogs, setLocalLogs] = useState<string[]>([])
  const [localGeneratedFiles, setLocalGeneratedFiles] = useState<LocalGeneratedFile[]>([])
  const [localJobId, setLocalJobId] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const localPollRef = useRef<number | null>(null)

  const localValidation = useMemo(() => validateLocalGranulesSelection(localFiles), [localFiles])
  const localFormValid = localValidation.ok && localAsignatura.trim().length > 0 && localPrograma.trim().length > 0
  const localTxtFiles = localGeneratedFiles.filter((f) => f.kind === 'txt')
  const localDocxFiles = localGeneratedFiles.filter((f) => f.kind === 'docx')
  const materialsFormValid = Boolean(materialsFile && materialsPrompt)

  const clearGranulesPolling = () => {
    if (granulesPollRef.current !== null) {
      window.clearInterval(granulesPollRef.current)
      granulesPollRef.current = null
    }
  }

  const clearLocalPolling = () => {
    if (localPollRef.current !== null) {
      window.clearInterval(localPollRef.current)
      localPollRef.current = null
    }
  }

  useEffect(() => () => clearGranulesPolling(), [])
  useEffect(() => () => clearLocalPolling(), [])
  useEffect(() => () => {
    if (materialsPollRef.current !== null) window.clearInterval(materialsPollRef.current)
  }, [])

  const addFiles = (incoming: FileList | File[]) => {
    const next = Array.from(incoming)
    if (next.length === 0) return
    setLocalFiles((prev) => {
      const merged = [...prev]
      for (const file of next) {
        const exists = merged.some((item) => item.name === file.name && item.size === file.size)
        if (!exists) merged.push(file)
      }
      return merged
    })
  }

  const removeLocalFile = (index: number) => {
    setLocalFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleGenerateGranulesOnly = async () => {
    if (!syllabusFile || isGeneratingGranules) return

    clearGranulesPolling()
    setIsGeneratingGranules(true)
    setGranulesStatus('leyendo syllabus')
    setGranulesMessage('Fase local: generando únicamente gránulos desde syllabus.')
    setGranulesLogs([])
    setGranulesFiles([])
    setGranulesJobId(null)

    try {
      const formData = new FormData()
      formData.append('syllabus', syllabusFile)
      formData.append('nivel', selectedPrompt)

      const createResponse = await fetch(`${API_BASE}/api/jobs`, {
        method: 'POST',
        body: formData,
      })

      if (!createResponse.ok) throw new Error(await readApiErrorDetail(createResponse))

      const created = (await createResponse.json()) as { jobId: string }
      setGranulesJobId(created.jobId)

      granulesPollRef.current = window.setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/api/jobs/${created.jobId}`)
          if (!res.ok) return

          const payload = (await res.json()) as JobStatusResponse
          setGranulesStatus(payload.progressStep)
          setGranulesLogs(payload.logs ?? [])
          setGranulesFiles((payload.files ?? []).filter((file) => /^G\d+_/.test(file)))

          if (payload.status === 'completed') {
            setGranulesStatus('finalizado')
            setIsGeneratingGranules(false)
            setGranulesMessage('Gránulos completados. Puedes descargar el ZIP parcial o los archivos generados.')
            clearGranulesPolling()
          }

          if (payload.status === 'failed') {
            setGranulesStatus('error')
            setIsGeneratingGranules(false)
            setGranulesMessage('Error generando gránulos. Revisa el registro de actividad.')
            clearGranulesPolling()
          }
        } catch {
          setGranulesStatus('error')
          setIsGeneratingGranules(false)
          setGranulesMessage('No fue posible consultar el estado del job.')
          clearGranulesPolling()
        }
      }, 3000)
    } catch (error) {
      setGranulesStatus('error')
      setIsGeneratingGranules(false)
      setGranulesMessage(error instanceof Error ? error.message : 'Error al iniciar la generación de gránulos.')
    }
  }

  const clearMaterialsPolling = () => {
    if (materialsPollRef.current !== null) {
      window.clearInterval(materialsPollRef.current)
      materialsPollRef.current = null
    }
  }

  const handleGenerateMaterialsOnly = async () => {
    if (!materialsFormValid || !materialsFile || isGeneratingMaterials) return

    clearMaterialsPolling()
    setIsGeneratingMaterials(true)
    setMaterialsStatus('generando materiales')
    setMaterialsMessage('Generando materiales desde el gránulo cargado...')
    setMaterialsLogs([])
    setMaterialsFiles([])
    setMaterialsJobId(null)

    try {
      const formData = new FormData()
      formData.append('granule', materialsFile)
      formData.append('nivel', materialsPrompt)

      const createResponse = await fetch(`${API_BASE}/api/materials/local/jobs`, {
        method: 'POST',
        body: formData,
      })

      if (!createResponse.ok) throw new Error(await readApiErrorDetail(createResponse))

      const created = (await createResponse.json()) as { jobId: string }
      setMaterialsJobId(created.jobId)

      materialsPollRef.current = window.setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/api/jobs/${created.jobId}`)
          if (!res.ok) return

          const payload = (await res.json()) as JobStatusResponse
          setMaterialsStatus(payload.progressStep)
          setMaterialsLogs(payload.logs ?? [])
          setMaterialsFiles((payload.files ?? []).filter((file) => file.includes('materiales_') || file.includes('materials')))

          if (payload.status === 'completed') {
            setMaterialsStatus('finalizado')
            setIsGeneratingMaterials(false)
            setMaterialsMessage('Materiales generados. Puedes descargar el paquete de materiales.')
            clearMaterialsPolling()
          }

          if (payload.status === 'failed') {
            setMaterialsStatus('error')
            setIsGeneratingMaterials(false)
            setMaterialsMessage('Error generando materiales. Revisa el registro de actividad.')
            clearMaterialsPolling()
          }
        } catch {
          setMaterialsStatus('error')
          setIsGeneratingMaterials(false)
          setMaterialsMessage('No fue posible consultar el estado del job de materiales.')
          clearMaterialsPolling()
        }
      }, 3000)
    } catch (error) {
      setMaterialsStatus('error')
      setIsGeneratingMaterials(false)
      setMaterialsMessage(error instanceof Error ? error.message : 'Error al iniciar materiales por gránulo.')
    }
  }

  const handleGenerateLocal = async () => {
    if (!localFormValid || localIsGenerating) return

    clearLocalPolling()
    setLocalIsGenerating(true)
    setLocalLogs([])
    setLocalGeneratedFiles([])
    setLocalJobId(null)
    setLocalStatus('cargando granulos')
    setLocalMessage('Subiendo gránulos locales al backend...')

    try {
      const formData = new FormData()
      localFiles.forEach((file) => formData.append('granules', file))
      formData.append('asignatura', localAsignatura.trim())
      formData.append('programa', localPrograma.trim())

      const createResponse = await fetch(`${API_BASE}/api/scripts/local/jobs`, {
        method: 'POST',
        body: formData,
      })

      if (!createResponse.ok) throw new Error(await readApiErrorDetail(createResponse))

      const created = (await createResponse.json()) as { jobId: string }
      setLocalJobId(created.jobId)
      setLocalStatus('validando estructura')
      setLocalMessage('Procesando G1-G5 para crear TXT/DOCX académicos...')

      localPollRef.current = window.setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/api/scripts/local/jobs/${created.jobId}`)
          if (!res.ok) return

          const payload = (await res.json()) as ScriptsLocalJobStatusResponse
          setLocalLogs(payload.logs ?? [])
          const step = payload.progressStep as ScriptsLocalProgressStep
          setLocalStatus(step === 'error' ? 'error' : step)

          if (payload.status === 'completed') {
            setLocalGeneratedFiles(payload.files ?? [])
            setLocalStatus('finalizado')
            setLocalIsGenerating(false)
            setLocalMessage('TXT/DOCX completados. Puedes descargar el paquete generado localmente.')
            clearLocalPolling()
          }

          if (payload.status === 'failed') {
            setLocalStatus('error')
            setLocalIsGenerating(false)
            setLocalMessage('El proceso local falló. Revisa el registro de actividad.')
            clearLocalPolling()
          }
        } catch {
          setLocalStatus('error')
          setLocalIsGenerating(false)
          setLocalMessage('No fue posible consultar el estado del job local.')
          clearLocalPolling()
        }
      }, 4000)
    } catch (error) {
      setLocalStatus('error')
      setLocalIsGenerating(false)
      setLocalMessage(error instanceof Error ? error.message : 'Error al iniciar el proceso local.')
    }
  }

  return (
    <div className="scripts-view">
      <div className="scripts-view-content">
        <div className="view-header premium-view-header">
          <BackButton onBack={onBack} />
          <div className="view-header-text">
            <span className="view-kicker">Ejecución local modular</span>
            <h1 className="view-title">Scripts individuales</h1>
            <p className="view-subtitle">Ejecuta tareas locales específicas sin activar todo el paquete académico.</p>
          </div>
        </div>

        <section className="scripts-cluster">
          <div className="scripts-cluster-heading">
            <span className="view-kicker">Scripts locales</span>
            <h2>Operaciones modulares conectadas</h2>
            <p>Ejecuta una parte específica del flujo cuando no necesitas construir el paquete completo.</p>
          </div>
          <div className="scripts-command-center">
            <button type="button" className={`script-command-card ${mode === 'granules' ? 'is-active' : ''}`} onClick={() => setMode('granules')}>
              <span className="script-command-icon">01</span>
              <strong>Crear solo gránulos</strong>
              <small>Syllabus → G1-G5</small>
              <em>Conectado localmente</em>
            </button>
            <button type="button" className={`script-command-card ${mode === 'txtdocx' ? 'is-active' : ''}`} onClick={() => setMode('txtdocx')}>
              <span className="script-command-icon">02</span>
              <strong>Crear TXT/DOCX</strong>
              <small>G1-G5 locales → actividades Moodle</small>
              <em>Conectado localmente</em>
            </button>
            <button type="button" className={`script-command-card ${mode === 'materials' ? 'is-active' : ''}`} onClick={() => setMode('materials')}>
              <span className="script-command-icon">03</span>
              <strong>Materiales por gránulo</strong>
              <small>Sube un gránulo y elige el nivel académico.</small>
              <em>Conectado localmente</em>
            </button>
          </div>
        </section>

        {mode === 'granules' && (
          <section className="scripts-workspace-card">
            <div className="scripts-workspace-header">
              <div>
                <span className="scripts-step-badge">Script local conectado</span>
                <h2>Crear solo gránulos desde syllabus</h2>
                <p>Usa `/api/jobs` para generar la Fase 1 y descargar únicamente los gránulos.</p>
              </div>
              <span className={`script-status-pill script-status-pill--${granulesStatus === 'error' ? 'error' : granulesStatus === 'finalizado' ? 'success' : isGeneratingGranules ? 'active' : 'idle'}`}>
                {statusLabel(granulesStatus)}
              </span>
            </div>

            <div className="scripts-form-grid">
              <label className="label-block">
                Nivel académico
                <select className="select-input" value={selectedPrompt} onChange={(event) => setSelectedPrompt(event.target.value as PromptType)} disabled={isGeneratingGranules}>
                  {promptOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="scripts-local-dropzone scripts-file-selector">
                <span className="file-input-label">Subir syllabus .docx</span>
                <input
                  type="file"
                  accept=".docx"
                  className="file-input"
                  disabled={isGeneratingGranules}
                  onChange={(event) => setSyllabusFile(event.target.files?.[0] ?? null)}
                />
                <p className="muted">{syllabusFile ? syllabusFile.name : 'Selecciona el syllabus fuente.'}</p>
              </label>
            </div>

            <section className="scripts-action-panel scripts-generate-section">
              <p className="muted">{granulesMessage}</p>
              <button type="button" className="primary-button primary-button--hero" onClick={handleGenerateGranulesOnly} disabled={!syllabusFile || isGeneratingGranules}>
                {isGeneratingGranules ? 'Generando gránulos...' : 'Generar gránulos'}
              </button>
            </section>

            {(isGeneratingGranules || granulesStatus !== 'pendiente') && (
              <article className="script-progress-card">
                <h3>Estado de gránulos</h3>
                <p>{statusLabel(granulesStatus)}</p>
                {granulesLogs.length > 0 && <div className="logs-box"><pre>{granulesLogs.slice(-28).join('\n')}</pre></div>}
              </article>
            )}

            {granulesJobId && granulesFiles.length > 0 && (
              <article className="script-results-card">
                <h3>Gránulos generados ({granulesFiles.length})</h3>
                <ul className="results-list">
                  {granulesFiles.map((fileName) => (
                    <li key={fileName}>
                      <span><strong>DOCX</strong> · {fileName}</span>
                      <a className="secondary-button link-button" href={`${API_BASE}/api/jobs/${granulesJobId}/files/${encodeURIComponent(fileName)}`} target="_blank" rel="noreferrer">Descargar</a>
                    </li>
                  ))}
                </ul>
                <a className="primary-button link-button" href={`${API_BASE}/api/jobs/${granulesJobId}/download/granules`} target="_blank" rel="noreferrer">Descargar gránulos (.zip)</a>
              </article>
            )}
          </section>
        )}

        {mode === 'txtdocx' && (
          <section className="scripts-workspace-card">
            <div className="scripts-workspace-header">
              <div>
                <span className="scripts-step-badge">Script local conectado</span>
                <h2>Crear TXT/DOCX desde gránulos locales</h2>
                <p>Sube G1-G5 ya generados y descarga PDA, QUIZ y documentos académicos.</p>
              </div>
              <span className={`script-status-pill script-status-pill--${localStatus === 'error' ? 'error' : localStatus === 'finalizado' ? 'success' : localIsGenerating ? 'active' : 'idle'}`}>
                {statusLabel(localStatus)}
              </span>
            </div>

            <div
              onDragOver={(event) => {
                event.preventDefault()
                setIsDragging(true)
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setIsDragging(false)
                addFiles(event.dataTransfer.files)
              }}
              className={['scripts-local-dropzone', 'scripts-local-dropzone--large', isDragging ? 'scripts-local-dropzone--drag' : ''].filter(Boolean).join(' ')}
            >
              <label className="file-input-label" htmlFor="local-granules-input">Subir G1-G5 en .docx</label>
              <input id="local-granules-input" type="file" multiple accept=".docx" onChange={(event) => addFiles(event.target.files ?? [])} className="file-input" />
              <p className="muted">Arrastra aquí tus gránulos o haz clic para seleccionarlos.</p>
              {localValidation.reason && <p className={`script-validation script-validation--${localValidation.level ?? 'error'}`}>{localValidation.reason}</p>}
              {localFiles.length > 0 && (
                <ul className="results-list compact-results-list">
                  {localFiles.map((file, index) => (
                    <li key={`${file.name}-${file.size}`}>
                      <span>{file.name}</span>
                      <button type="button" className="secondary-button" onClick={() => removeLocalFile(index)} disabled={localIsGenerating}>Quitar</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="scripts-form-grid">
              <label className="label-block">
                Asignatura
                <input type="text" className="select-input" value={localAsignatura} onChange={(event) => setLocalAsignatura(event.target.value)} placeholder="Ej: Inteligencia artificial y analítica avanzada" disabled={localIsGenerating} />
              </label>
              <label className="label-block">
                Programa
                <input type="text" className="select-input" value={localPrograma} onChange={(event) => setLocalPrograma(event.target.value)} placeholder="Ej: Especialización en videojuegos" disabled={localIsGenerating} />
              </label>
            </div>

            <section className="scripts-action-panel scripts-generate-section">
              <p className="muted">{localMessage}</p>
              <button type="button" className="primary-button primary-button--hero" onClick={handleGenerateLocal} disabled={!localFormValid || localIsGenerating}>
                {localIsGenerating ? 'Generando TXT/DOCX...' : 'Generar TXT/DOCX'}
              </button>
            </section>

            {(localIsGenerating || localStatus !== 'pendiente') && (
              <article className="script-progress-card">
                <h3>Estado de procesamiento local</h3>
                <ol className="progress-list script-progress-list">
                  {SCRIPTS_LOCAL_PIPELINE_STEPS.map((step) => (
                    <li key={step} className={`progress-item ${step === localStatus ? 'is-current' : ''}`}>
                      <span className="progress-dot" />
                      <span>{statusLabel(step)}</span>
                    </li>
                  ))}
                </ol>
                {localLogs.length > 0 && <div className="logs-box"><pre>{localLogs.slice(-28).join('\n')}</pre></div>}
              </article>
            )}

            {localStatus === 'finalizado' && localGeneratedFiles.length > 0 && (
              <article className="script-results-card">
                <h3>Archivos TXT/DOCX generados</h3>
                {localTxtFiles.length > 0 && <p className="card-description">TXT: {localTxtFiles.map((file) => file.name).join(', ')}</p>}
                {localDocxFiles.length > 0 && <p className="card-description">DOCX: {localDocxFiles.map((file) => file.name).join(', ')}</p>}
                <a className="primary-button link-button" href={`${API_BASE}/api/scripts/local/jobs/${localJobId}/download-all`} target="_blank" rel="noreferrer">Descargar TXT/DOCX (.zip)</a>
              </article>
            )}
          </section>
        )}

        {mode === 'materials' && (
          <section className="scripts-workspace-card">
            <div className="scripts-workspace-header">
              <div>
                <span className="scripts-step-badge">Script local conectado</span>
                <h2>Crear materiales por gránulo</h2>
                <p>Sube un gránulo maestro .docx, selecciona el nivel y genera directamente los materiales editoriales de ese gránulo.</p>
              </div>
              <span className={`script-status-pill script-status-pill--${materialsStatus === 'error' ? 'error' : materialsStatus === 'finalizado' ? 'success' : isGeneratingMaterials ? 'active' : 'idle'}`}>
                {statusLabel(materialsStatus)}
              </span>
            </div>

            <div className="scripts-form-grid">
              <label className="label-block">
                Nivel académico
                <select className="select-input" value={materialsPrompt} onChange={(event) => setMaterialsPrompt(event.target.value as PromptType)} disabled={isGeneratingMaterials}>
                  {promptOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="scripts-local-dropzone scripts-file-selector">
                <span className="file-input-label">Subir gránulo .docx</span>
                <input
                  type="file"
                  accept=".docx"
                  className="file-input"
                  disabled={isGeneratingMaterials}
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null
                    setMaterialsFile(file)
                    setMaterialsFiles([])
                    setMaterialsJobId(null)
                    setMaterialsStatus('pendiente')
                    setMaterialsMessage(file ? 'Gránulo cargado. Elige el nivel y genera sus materiales.' : 'Sube un gránulo .docx, elige el nivel y genera sus materiales editoriales.')
                  }}
                />
                <p className="muted">{materialsFile ? materialsFile.name : 'Selecciona un gránulo fuente, por ejemplo G1_TEMA.docx.'}</p>
              </label>
            </div>

            <section className="scripts-action-panel scripts-generate-section">
              <p className="muted">{materialsMessage}</p>
              <button type="button" className="primary-button primary-button--hero" onClick={handleGenerateMaterialsOnly} disabled={!materialsFormValid || isGeneratingMaterials}>
                {isGeneratingMaterials ? 'Generando materiales...' : 'Generar materiales por gránulo'}
              </button>
            </section>

            {(isGeneratingMaterials || materialsStatus !== 'pendiente') && (
              <article className="script-progress-card">
                <h3>Estado de materiales</h3>
                <p>{statusLabel(materialsStatus)}</p>
                {materialsLogs.length > 0 && <div className="logs-box"><pre>{materialsLogs.slice(-28).join('\n')}</pre></div>}
              </article>
            )}

            {materialsJobId && materialsFiles.length > 0 && (
              <article className="script-results-card">
                <h3>Materiales generados ({materialsFiles.length})</h3>
                <ul className="results-list compact-results-list">
                  {materialsFiles.map((fileName) => (
                    <li key={fileName}>
                      <span><strong>DOCX</strong> · {fileName.replace(/^materiales_[^/]+\//, '')}</span>
                    </li>
                  ))}
                </ul>
                <a className="primary-button link-button" href={`${API_BASE}/api/jobs/${materialsJobId}/download/materials`} target="_blank" rel="noreferrer">
                  Descargar materiales (.zip)
                </a>
              </article>
            )}
          </section>
        )}

        <section className="drive-soon-section">
          <span className="drive-lock-orb" aria-hidden>↗</span>
          <div>
            <span className="scripts-step-badge">Próximamente</span>
            <h2>Flujos Drive</h2>
            <p>El paquete Drive completo queda bloqueado. El script histórico de TXT/DOCX desde Drive no corresponde al paquete Drive completo y se deja separado para una iteración posterior.</p>
          </div>
          <button type="button" className="secondary-button" disabled>Drive próximamente</button>
        </section>
      </div>
    </div>
  )
}

export default ScriptsView

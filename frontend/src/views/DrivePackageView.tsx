import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import FileDropzone from '../components/FileDropzone'
import JobProgressPanel from '../components/JobProgressPanel'
import PromptSelector from '../components/PromptSelector'
import { CATEGORY_CONFIGS, getCategoryConfig } from '../data/categories'
import { apiFetch, readApiErrorDetail } from '../lib/api'
import type { CategoryConfig, DriveUploadResponse, GenerationStatus, JobPhaseStatus, JobStatusResponse, PromptType, SyllabusPreviewResponse } from '../types/granules'

interface DrivePackageViewProps {
  onBack: () => void
}

type DriveStage = 'idle' | 'granules' | 'activities' | 'resources' | 'uploading' | 'ready' | 'error'
type DrivePhaseKey = 'granules' | 'activities' | 'resources' | 'drive'

function DrivePackageView({ onBack }: DrivePackageViewProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptType | ''>('')
  const [detectedGranules, setDetectedGranules] = useState<Array<{ id: string; label: string }>>([])
  const [subjectName, setSubjectName] = useState('')
  const [programName, setProgramName] = useState('')
  const [isAnalyzingSyllabus, setIsAnalyzingSyllabus] = useState(false)
  const [previewMessage, setPreviewMessage] = useState('')
  const [status, setStatus] = useState<GenerationStatus>('pendiente')
  const [driveStage, setDriveStage] = useState<DriveStage>('idle')
  const [failedDrivePhase, setFailedDrivePhase] = useState<DrivePhaseKey | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [jobLogs, setJobLogs] = useState<string[]>([])
  const [generatedDocuments, setGeneratedDocuments] = useState<string[]>([])
  const [phaseStatus, setPhaseStatus] = useState<JobPhaseStatus | null>(null)
  const [currentPhase, setCurrentPhase] = useState('pending')
  const [categories, setCategories] = useState<CategoryConfig[]>(CATEGORY_CONFIGS)
  const [driveFolderId, setDriveFolderId] = useState('')
  const [driveMessage, setDriveMessage] = useState('')
  const [driveResult, setDriveResult] = useState<DriveUploadResponse | null>(null)
  const pollRef = useRef<number | null>(null)
  const runLockRef = useRef(false)
  const resultsPanelRef = useRef<HTMLElement | null>(null)

  const hasSyllabus = Boolean(selectedFile)
  const selectedCategory = useMemo(() => categories.find((category) => category.key === selectedPrompt) ?? getCategoryConfig(selectedPrompt), [categories, selectedPrompt])
  const categoryLabel = selectedCategory?.label ?? 'categoría seleccionada'
  const materialsPerGranule = selectedCategory?.expectedMaterialsPerGranule ?? 0
  const canUploadSyllabus = Boolean(selectedPrompt)
  const canRunDrivePackage = Boolean(selectedCategory?.enabledForPackage && selectedFile && driveFolderId.trim() && detectedGranules.length > 0 && !isRunning && driveStage !== 'ready')
  const driveActionLabel: Record<DriveStage, string> = {
    idle: 'Generar y subir a Drive',
    granules: 'Generando gránulos...',
    activities: 'Generando actividades...',
    resources: 'Generando recursos complementarios...',
    uploading: 'Subiendo paquete a Drive...',
    ready: 'Paquete creado en Drive',
    error: 'Reintentar flujo Drive',
  }

  const drivePhases = [
    { key: 'syllabus', number: '01', icon: 'DOC', title: 'Syllabus recibido' },
    { key: 'granules', number: '02', icon: 'G1', title: 'Generando gránulos' },
    { key: 'activities', number: '03', icon: 'TXT', title: 'Generando actividades' },
    { key: 'resources', number: '04', icon: '6x', title: 'Generando recursos' },
    { key: 'drive', number: '05', icon: 'DRV', title: 'Subiendo a Drive' },
  ] as const

  const clearPolling = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const resetForNewSyllabus = () => {
    setSelectedFile(null)
    setDetectedGranules([])
    setSubjectName('')
    setProgramName('')
    setPreviewMessage('')
    setStatus('pendiente')
    setDriveStage('idle')
    setFailedDrivePhase(null)
    setIsRunning(false)
    setJobLogs([])
    setGeneratedDocuments([])
    setPhaseStatus(null)
    setCurrentPhase('pending')
    setDriveMessage('')
    setDriveResult(null)
    runLockRef.current = false
    clearPolling()
  }

  const applyJobStatus = (payload: JobStatusResponse) => {
    setStatus(payload.progressStep)
    setJobLogs(payload.logs ?? [])
    setGeneratedDocuments(payload.files ?? [])
    setPhaseStatus(payload.phaseStatus)
    setCurrentPhase(payload.currentPhase)
  }

  const fetchJobStatus = async (targetJobId: string): Promise<JobStatusResponse> => {
    const statusResponse = await apiFetch(`/api/jobs/${targetJobId}`)
    if (!statusResponse.ok) throw new Error('No fue posible consultar el estado del job.')
    const payload = (await statusResponse.json()) as JobStatusResponse
    applyJobStatus(payload)
    return payload
  }

  const waitForJobIdle = (targetJobId: string, phaseLabel: string): Promise<JobStatusResponse> => {
    clearPolling()
    return new Promise((resolve, reject) => {
      let isPolling = false

      const stopPolling = () => {
        clearPolling()
        isPolling = false
      }

      const poll = async () => {
        if (isPolling) return
        isPolling = true
        try {
          const payload = await fetchJobStatus(targetJobId)
          if (payload.status === 'completed') {
            stopPolling()
            resolve(payload)
            return
          }
          if (payload.status === 'failed') {
            stopPolling()
            reject(new Error(`Error en fase ${phaseLabel}.`))
            return
          }
        } catch (error) {
          stopPolling()
          reject(error)
          return
        } finally {
          isPolling = false
        }
      }

      pollRef.current = window.setInterval(poll, 2000)
      void poll()
    })
  }

  const createGranulesJob = async (): Promise<string> => {
    if (!selectedFile || !selectedPrompt) throw new Error('Falta seleccionar syllabus y categoría académica.')

    const formData = new FormData()
    formData.append('syllabus', selectedFile)
    formData.append('nivel', selectedPrompt)

    const createResponse = await apiFetch('/api/jobs', {
      method: 'POST',
      body: formData,
    })

    if (!createResponse.ok) {
      throw new Error(await readApiErrorDetail(createResponse, 'No se pudo crear el job de generación.'))
    }

    const createdJob = (await createResponse.json()) as { jobId: string; status: string }
    return createdJob.jobId
  }

  const postExistingJobPhase = async (targetJobId: string, path: string, runningStatus: GenerationStatus, stage: DriveStage, phaseLabel: string) => {
    setStatus(runningStatus)
    setDriveStage(stage)
    const response = await apiFetch(path, { method: 'POST' })
    if (!response.ok) {
      throw new Error(await readApiErrorDetail(response, `No se pudo iniciar ${phaseLabel}.`))
    }
    return waitForJobIdle(targetJobId, phaseLabel)
  }

  const uploadDrivePackage = async (targetJobId: string): Promise<DriveUploadResponse> => {
    const formData = new FormData()
    formData.append('driveFolderId', driveFolderId.trim())
    formData.append('includeZip', 'true')

    const response = await apiFetch(`/api/jobs/${targetJobId}/upload-drive`, {
      method: 'POST',
      body: formData,
    })
    const payload = (await response.json()) as DriveUploadResponse | { detail?: string }
    if (!response.ok) throw new Error((payload as { detail?: string }).detail ?? 'No fue posible subir el paquete a Drive.')
    return payload as DriveUploadResponse
  }

  const analyzeSyllabusPreview = async (file: File) => {
    setIsAnalyzingSyllabus(true)
    setPreviewMessage('Analizando estructura temática...')
    setDetectedGranules([])

    try {
      const formData = new FormData()
      formData.append('syllabus', file)

      const response = await apiFetch('/api/syllabus/preview', {
        method: 'POST',
        body: formData,
      })
      const payload = (await response.json()) as SyllabusPreviewResponse | { detail?: string }

      if (!response.ok) {
        throw new Error((payload as { detail?: string }).detail ?? 'No fue posible analizar el syllabus.')
      }

      const preview = payload as SyllabusPreviewResponse
      const selectedCourse = preview.selectedCourse
      const selectedTopics = selectedCourse?.temas?.length
        ? selectedCourse.temas.map((title, index) => ({ index: index + 1, title }))
        : preview.detectedTopics

      setSubjectName(selectedCourse?.asignatura || preview.subjectName || '')
      setProgramName(preview.programName ?? '')
      setDetectedGranules(selectedTopics.map((topic) => ({ id: `G${topic.index}`, label: topic.title })))
      setPreviewMessage(selectedTopics.length === 0 ? 'No se encontraron contenidos en la estructura temática. Revisa que el syllabus tenga la sección 5. ESTRUCTURA TEMÁTICA con columna Contenidos.' : '')
    } catch (error) {
      setPreviewMessage(error instanceof Error ? error.message : 'Error analizando syllabus.')
      setDetectedGranules([])
      setSubjectName('')
      setProgramName('')
    } finally {
      setIsAnalyzingSyllabus(false)
    }
  }

  const handleGenerateDrivePackage = async () => {
    if (!canRunDrivePackage || runLockRef.current) return

    runLockRef.current = true
    setIsRunning(true)
    setDriveStage('granules')
    setFailedDrivePhase(null)
    setStatus('leyendo syllabus')
    setDriveMessage('Generando gránulos. El paquete se subirá a Drive cuando finalicen todas las fases de generación.')
    setDriveResult(null)
    setJobLogs([])
    setGeneratedDocuments([])
    setPhaseStatus(null)
    clearPolling()

    let activeDrivePhase: DrivePhaseKey = 'granules'

    try {
      const createdJobId = await createGranulesJob()
      await waitForJobIdle(createdJobId, '1: generar gránulos')

      activeDrivePhase = 'activities'
      setDriveMessage('Generando actividades. Drive seguirá pendiente hasta completar actividades y recursos.')
      await postExistingJobPhase(createdJobId, `/api/jobs/${createdJobId}/pipeline-local`, 'generando txt', 'activities', '2: generar actividades')

      activeDrivePhase = 'resources'
      setDriveMessage('Generando recursos complementarios. La subida a Drive iniciará al terminar esta fase.')
      await postExistingJobPhase(createdJobId, `/api/jobs/${createdJobId}/materials`, 'generando materiales', 'resources', '3: generar recursos')

      activeDrivePhase = 'drive'
      setDriveStage('uploading')
      setStatus('organizando archivos')
      setDriveMessage('Subiendo paquete a Drive...')
      const drivePayload = await uploadDrivePackage(createdJobId)
      setDriveResult(drivePayload)
      await fetchJobStatus(createdJobId)
      setDriveStage('ready')
      setStatus('finalizado')
      setDriveMessage('Paquete creado en Drive.')
    } catch (error) {
      setFailedDrivePhase(activeDrivePhase)
      setDriveStage('error')
      setStatus('error')
      const phaseNames: Record<DrivePhaseKey, string> = {
        granules: 'generación de gránulos',
        activities: 'generación de actividades',
        resources: 'generación de recursos complementarios',
        drive: 'subida a Drive',
      }
      const detail = error instanceof Error ? error.message : 'Error Drive.'
      setDriveMessage(`Error en ${phaseNames[activeDrivePhase]}: ${detail}`)
    } finally {
      clearPolling()
      runLockRef.current = false
      setIsRunning(false)
    }
  }

  const handlePromptChange = (prompt: PromptType | '') => {
    setSelectedPrompt(prompt)
    resetForNewSyllabus()
  }

  const getDrivePhaseState = (phaseKey: string): 'pending' | 'active' | 'completed' | 'error' => {
    if (phaseKey === 'syllabus') return hasSyllabus ? 'completed' : 'active'
    if (phaseKey === 'granules') {
      if (driveStage === 'error' && failedDrivePhase === 'granules') return 'error'
      if (phaseStatus?.granules.status === 'completed') return 'completed'
      return driveStage === 'granules' ? 'active' : 'pending'
    }
    if (phaseKey === 'activities') {
      if (driveStage === 'error' && failedDrivePhase === 'activities') return 'error'
      if (phaseStatus?.pipelineLocal.status === 'completed') return 'completed'
      return driveStage === 'activities' ? 'active' : 'pending'
    }
    if (phaseKey === 'resources') {
      if (driveStage === 'error' && failedDrivePhase === 'resources') return 'error'
      if (phaseStatus?.specializationMaterials.status === 'completed') return 'completed'
      return driveStage === 'resources' ? 'active' : 'pending'
    }
    if (phaseKey === 'drive') {
      if (driveStage === 'error' && failedDrivePhase === 'drive') return 'error'
      if (driveStage === 'ready') return 'completed'
      return driveStage === 'uploading' ? 'active' : 'pending'
    }
    return 'pending'
  }

  const consoleStatus = driveStage === 'error'
    ? 'Error Drive'
    : driveStage === 'ready'
      ? 'Paquete Drive listo'
      : isRunning
        ? 'Procesando Drive'
        : 'Sistema listo'

  const alignTopWithViewport = useCallback((el: HTMLElement | null) => {
    if (!el) return
    const y = Math.round(window.scrollY + el.getBoundingClientRect().top)
    window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' })
  }, [])

  useEffect(() => () => clearPolling(), [])

  useEffect(() => {
    let cancelled = false
    apiFetch('/api/categories')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('No categories')))
      .then((payload: CategoryConfig[]) => {
        if (!cancelled && Array.isArray(payload) && payload.length > 0) setCategories(payload)
      })
      .catch((error) => {
        if (!cancelled) {
          setCategories(CATEGORY_CONFIGS)
          if (error instanceof Error) setPreviewMessage(error.message)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!isRunning) return
    const t = window.setTimeout(() => alignTopWithViewport(resultsPanelRef.current), 180)
    return () => window.clearTimeout(t)
  }, [isRunning, alignTopWithViewport])

  return (
    <div className="granules-view">
      <div className="granules-view-content">
        <div className="view-header generation-console-header">
          <BackButton onBack={onBack} />
          <span className="generation-header-badge">Pipeline Drive</span>
          <div className="view-header-text">
            <h1 className="view-title">Generar paquete en Drive</h1>
            <p className="view-subtitle">Crea la misma estructura académica directamente dentro de una carpeta de Google Drive.</p>
          </div>
          <span className={`generation-status-pill generation-status-pill--${driveStage === 'error' ? 'error' : driveStage === 'ready' ? 'ready' : isRunning ? 'live' : 'idle'}`}>
            {consoleStatus}
          </span>
        </div>

        <section className="generation-console">
          <aside className="config-console-panel">
            <div className="config-console-shell">
              <div className="config-console-shell-header">
                <span className="view-kicker">Configuración Drive</span>
                <h2>Panel del paquete Drive</h2>
                <p>Selecciona la categoría, carga el syllabus y define la carpeta Drive destino.</p>
              </div>

              <PromptSelector selectedPrompt={selectedPrompt} onSelectPrompt={handlePromptChange} categories={categories} />

              {!canUploadSyllabus && (
                <section className="action-card granule-card setup-card console-hint-card">
                  <p className="muted">Selecciona una categoría activa para habilitar el upload del syllabus.</p>
                </section>
              )}

              {canUploadSyllabus && (
                <FileDropzone
                  selectedFile={selectedFile}
                  onFileSelected={async (file) => {
                    resetForNewSyllabus()
                    setSelectedFile(file)

                    if (!file) return
                    if (!file.name.toLowerCase().endsWith('.docx')) {
                      setPreviewMessage('El archivo debe ser .docx')
                      return
                    }

                    await analyzeSyllabusPreview(file)
                  }}
                />
              )}

              <section className="action-card granule-card drive-upload-card console-primary-action">
                <div>
                  <span className="view-kicker">Google Drive</span>
                  <h2>Carpeta destino</h2>
                  <p className="card-description">Pega el ID de la carpeta Drive donde se creará el paquete académico.</p>
                </div>
                <input
                  type="text"
                  className="select-input"
                  value={driveFolderId}
                  onChange={(event) => setDriveFolderId(event.target.value)}
                  placeholder="Ej: 1AbCDefGhIjKlMnOpQrStUv"
                  disabled={isRunning}
                />
                <button
                  type="button"
                  className="primary-button primary-button--hero"
                  onClick={handleGenerateDrivePackage}
                  disabled={!canRunDrivePackage}
                >
                  {driveActionLabel[driveStage]}
                </button>
                {!driveFolderId.trim() && <p className="preview-alert is-info">Pega el ID de la carpeta Drive donde se creará el paquete académico.</p>}
                {driveMessage && <p className={`preview-alert ${driveStage === 'error' ? 'is-error' : 'is-info'}`}>{driveMessage}</p>}
              </section>

              <section className="granule-card syllabus-compact-preview granules-pipeline-scroll-target">
                <div className="granule-card-header">
                  <span className="granule-card-kicker">PREVIEW</span>
                </div>
                <div className="syllabus-preview-rows">
                  <div><span>Archivo original</span><strong>{selectedFile?.name ?? 'Pendiente'}</strong></div>
                  <div><span>Nombre interno</span><strong>{selectedFile ? 'syllabus.docx' : 'Pendiente'}</strong></div>
                  <div><span>Asignatura</span><strong>{subjectName || 'Sin detectar'}</strong></div>
                  <div><span>Programa</span><strong>{programName || 'Sin detectar'}</strong></div>
                  <div><span>Gránulos</span><strong>{isAnalyzingSyllabus ? 'Analizando...' : `${detectedGranules.length || 0} detectados`}</strong></div>
                </div>
                {previewMessage && <p className="preview-alert is-info">{previewMessage}</p>}
              </section>
            </div>
          </aside>

          <aside className="status-console-panel">
            <section ref={resultsPanelRef} className="package-status-card status-console-shell">
              <div className="local-flow-phases card console-pipeline-card">
                <div className="local-flow-heading">
                  <div>
                    <span className="view-kicker">Mapa del flujo Drive</span>
                    <h2>Pipeline académico Drive</h2>
                  </div>
                  <span className={`local-flow-live ${isRunning ? 'is-live' : ''}`}>{consoleStatus}</span>
                </div>
                <div className="local-flow-stepper console-flow-stepper">
                  {drivePhases.map((phase) => {
                    const phaseState = getDrivePhaseState(phase.key)
                    return (
                      <article key={phase.key} className={`local-flow-step local-flow-step--${phaseState}`}>
                        <span className="local-flow-step-number">{phase.number}</span>
                        <span className="local-flow-step-icon">{phase.icon}</span>
                        <span className="local-flow-step-check" aria-hidden>{phaseState === 'completed' ? '✓' : phaseState === 'error' ? '!' : ''}</span>
                        <strong>{phase.title}</strong>
                        <small>{phaseState === 'completed' ? 'Completado' : phaseState === 'active' ? 'Activo' : phaseState === 'error' ? 'Error' : 'Pendiente'}</small>
                      </article>
                    )
                  })}
                </div>
              </div>

              <JobProgressPanel
                status={status}
                logs={jobLogs}
                granules={detectedGranules}
                isGenerating={isRunning}
                isError={driveStage === 'error'}
                generatedFilesCount={generatedDocuments.length}
                totalMaterialsExpected={detectedGranules.length * materialsPerGranule}
                materialsPerGranule={materialsPerGranule}
                deliverables={selectedCategory?.deliverables ?? []}
                categoryLabel={categoryLabel}
                backendCurrentPhase={currentPhase}
                onRetry={handleGenerateDrivePackage}
              />

              <section className="action-card granule-card drive-upload-card">
                <div>
                  <span className="view-kicker">Resultado Drive</span>
                  <h2>{driveStage === 'ready' ? 'Paquete Drive listo' : driveStage === 'error' ? 'Error Drive' : 'Estado de subida Drive'}</h2>
                  <p className="card-description">El paquete se subirá a Drive cuando finalicen gránulos, actividades y recursos.</p>
                </div>
                {driveResult ? (
                  <>
                    <div className="syllabus-preview-rows">
                      <div><span>Carpetas creadas</span><strong>{driveResult.foldersCreated}</strong></div>
                      <div><span>Carpetas reutilizadas</span><strong>{driveResult.foldersReused}</strong></div>
                      <div><span>Archivos subidos</span><strong>{driveResult.filesUploaded}</strong></div>
                      <div><span>Archivos sobrescritos</span><strong>{driveResult.filesOverwritten}</strong></div>
                      <div><span>Carpeta Drive</span><strong><a href={driveResult.folderLink} target="_blank" rel="noreferrer">PAQUETE_ACADEMICO</a></strong></div>
                    </div>
                    <a className="primary-button primary-button--hero link-button" href={driveResult.folderLink} target="_blank" rel="noreferrer">Abrir carpeta en Drive</a>
                  </>
                ) : (
                  <p className="preview-alert is-info">La carpeta final aparecerá aquí cuando termine la subida a Drive.</p>
                )}
              </section>
            </section>
          </aside>
        </section>
      </div>
    </div>
  )
}

export default DrivePackageView

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import FileDropzone from '../components/FileDropzone'
import JobProgressPanel from '../components/JobProgressPanel'
import PromptSelector from '../components/PromptSelector'
import { CATEGORY_CONFIGS, getCategoryConfig } from '../data/categories'
import { apiFetch, readApiErrorDetail } from '../lib/api'
import type { CategoryConfig, DriveSyncSnapshot, DriveUploadResponse, GenerationStatus, JobPhaseStatus, JobStatusResponse, PromptType, SyllabusPreviewResponse } from '../types/granules'

interface DrivePackageViewProps {
  onBack: () => void
}

function isPhasedDrivePackageComplete(ds: DriveSyncSnapshot | null | undefined): boolean {
  if (!ds?.drivePhasedSync || !ds.drivePhaseStatus) return false
  const keys = ['structure', 'syllabus', 'granules', 'activities', 'resources'] as const
  return keys.every((k) => ds.drivePhaseStatus![k]?.status === 'completed')
}

function snapshotToDriveUploadResponse(ds: DriveSyncSnapshot, jobId: string): DriveUploadResponse {
  return {
    jobId,
    status: 'completed',
    folderId: ds.drivePackageFolderId ?? '',
    folderLink: ds.drivePackageUrl ?? '',
    filesUploaded: ds.driveFilesUploaded,
    filesOverwritten: ds.driveFilesOverwritten,
    filesSkipped: 0,
    foldersCreated: ds.driveFoldersCreated,
    foldersReused: ds.driveFoldersReused,
  }
}

type DriveStage = 'idle' | 'granules' | 'activities' | 'resources' | 'uploading' | 'ready' | 'error'
type DrivePhaseKey = 'granules' | 'activities' | 'resources' | 'drive'
type BackendPhaseKey = 'granules' | 'pipelineLocal' | 'specializationMaterials'

/** Polling del estado del job: menos carga que 2s y límite para no peticiones infinitas si el backend se queda colgado. */
const JOB_POLL_INTERVAL_MS = 3500
const JOB_POLL_MAX_MS = 120 * 60 * 1000

const DRIVE_PACKAGE_SESSION_KEY = 'drivePackageJobSession.v1'

interface StoredDriveSession {
  jobId: string
  driveFolderId: string
  prompt: PromptType | ''
}

function parseGranuleCodesFromJobFiles(files: string[]): Array<{ id: string; label: string }> {
  const seen = new Map<string, string>()
  for (const name of files) {
    const base = name.split(/[/\\]/).pop() ?? name
    const m = /^G(\d+)/i.exec(base)
    if (m) {
      const id = `G${m[1]}`
      if (!seen.has(id)) seen.set(id, `Gránulo ${m[1]}`)
    }
  }
  return Array.from(seen.entries())
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([id, label]) => ({ id, label }))
}

function loadDriveSession(): StoredDriveSession | null {
  try {
    const raw = sessionStorage.getItem(DRIVE_PACKAGE_SESSION_KEY)
    if (!raw) return null
    const s = JSON.parse(raw) as StoredDriveSession
    if (!s?.jobId?.trim()) return null
    return s
  } catch {
    return null
  }
}

function saveDriveSession(session: StoredDriveSession) {
  sessionStorage.setItem(DRIVE_PACKAGE_SESSION_KEY, JSON.stringify(session))
}

function clearDriveSession() {
  sessionStorage.removeItem(DRIVE_PACKAGE_SESSION_KEY)
}

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
  const [driveSync, setDriveSync] = useState<DriveSyncSnapshot | null>(null)
  const [driveResult, setDriveResult] = useState<DriveUploadResponse | null>(null)
  const pollRef = useRef<number | null>(null)
  const runLockRef = useRef(false)
  const resultsPanelRef = useRef<HTMLElement | null>(null)
  const [packageJobId, setPackageJobId] = useState<string | null>(null)
  const executeDrivePipelineRef = useRef<(jobId: string | null, opts?: { force?: boolean }) => Promise<void>>(async () => {})

  const hasSyllabus = Boolean(selectedFile)
  const selectedCategory = useMemo(() => categories.find((category) => category.key === selectedPrompt) ?? getCategoryConfig(selectedPrompt), [categories, selectedPrompt])
  const categoryLabel = selectedCategory?.label ?? 'categoría seleccionada'
  const materialsPerGranule = selectedCategory?.expectedMaterialsPerGranule ?? 0
  const canUploadSyllabus = Boolean(selectedPrompt)
  const canStartNewDrivePackage = Boolean(
    selectedCategory?.enabledForPackage && selectedFile && driveFolderId.trim() && detectedGranules.length > 0 && !isRunning && driveStage !== 'ready',
  )
  const canResumeDrivePackage = Boolean(
    packageJobId && driveFolderId.trim() && selectedPrompt && selectedCategory?.enabledForPackage && !isRunning && driveStage !== 'ready',
  )
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
    setDriveSync(null)
    setDriveResult(null)
    setPackageJobId(null)
    clearDriveSession()
    runLockRef.current = false
    clearPolling()
  }

  const applyJobStatus = (payload: JobStatusResponse) => {
    setStatus(payload.progressStep)
    setJobLogs(payload.logs ?? [])
    setGeneratedDocuments(payload.files ?? [])
    setPhaseStatus(payload.phaseStatus)
    setCurrentPhase(payload.currentPhase)
    setDriveSync(payload.driveSync ?? null)
    if (payload.categoryKey) {
      setSelectedPrompt(payload.categoryKey as PromptType)
    }
    const inferred = parseGranuleCodesFromJobFiles(payload.files ?? [])
    if (inferred.length > 0) {
      setDetectedGranules(inferred)
    }
    setDriveFolderId((prev) => {
      if (prev.trim()) return prev
      const ds = payload.driveSync
      const wid = ds?.driveWorkspaceFolderId || ds?.driveParentFolderId
      return typeof wid === 'string' && wid.trim() ? wid : prev
    })
  }

  const displayedDriveMessage = useMemo(() => {
    const ds = driveSync
    if (!ds?.drivePhasedSync || !ds.drivePhaseStatus) return driveMessage
    const ps = ds.drivePhaseStatus
    const order = ['structure', 'syllabus', 'granules', 'activities', 'resources'] as const
    for (const key of order) {
      if (ps[key]?.status === 'failed') {
        return `Error en Drive (${key}): ${ps[key]?.error ?? 'sin detalle'}`
      }
    }
    if (ps.resources?.status === 'completed') return 'Recursos complementarios subidos a Drive.'
    if (ps.activities?.status === 'completed') return 'Actividades subidas a Drive.'
    if (ps.granules?.status === 'completed') return 'Gránulos subidos a Drive. Generando actividades…'
    if (ps.syllabus?.status === 'completed') return 'Syllabus subido a Drive. Generando gránulos…'
    if (ps.structure?.status === 'completed') return 'Estructura de carpetas lista en Drive.'
    return driveMessage
  }, [driveSync, driveMessage])

  const fetchJobStatus = async (targetJobId: string): Promise<JobStatusResponse> => {
    const statusResponse = await apiFetch(`/api/jobs/${targetJobId}`)
    if (!statusResponse.ok) throw new Error('No fue posible consultar el estado del job.')
    const payload = (await statusResponse.json()) as JobStatusResponse
    applyJobStatus(payload)
    return payload
  }

  const getBackendPhaseStatus = (payload: JobStatusResponse, phaseKey: BackendPhaseKey) => {
    return payload.phaseStatus?.[phaseKey]?.status
  }

  const waitForBackendPhase = (targetJobId: string, phaseKey: BackendPhaseKey, phaseLabel: string): Promise<JobStatusResponse> => {
    clearPolling()
    return new Promise((resolve, reject) => {
      let isPolling = false
      const startedAt = Date.now()

      const stopPolling = () => {
        clearPolling()
        isPolling = false
      }

      const poll = async () => {
        if (Date.now() - startedAt > JOB_POLL_MAX_MS) {
          stopPolling()
          reject(
            new Error(
              `Tiempo máximo de espera (${Math.round(JOB_POLL_MAX_MS / 60000)} min) agotado en ${phaseLabel}. Revisa el backend o los logs del job.`,
            ),
          )
          return
        }
        if (isPolling) return
        isPolling = true
        try {
          const payload = await fetchJobStatus(targetJobId)
          const phaseStatusValue = getBackendPhaseStatus(payload, phaseKey)
          if (phaseStatusValue === 'completed') {
            stopPolling()
            resolve(payload)
            return
          }
          if (phaseStatusValue === 'failed' || payload.status === 'failed') {
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

      pollRef.current = window.setInterval(poll, JOB_POLL_INTERVAL_MS)
      void poll()
    })
  }

  const createGranulesJob = async (): Promise<string> => {
    if (!selectedFile || !selectedPrompt) throw new Error('Falta seleccionar syllabus y categoría académica.')

    const formData = new FormData()
    formData.append('syllabus', selectedFile)
    formData.append('nivel', selectedPrompt)
    formData.append('driveFolderId', driveFolderId.trim())

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

  const postExistingJobPhase = async (targetJobId: string, path: string, runningStatus: GenerationStatus, stage: DriveStage, phaseKey: BackendPhaseKey, phaseLabel: string) => {
    setStatus(runningStatus)
    setDriveStage(stage)
    const response = await apiFetch(path, { method: 'POST' })
    if (!response.ok) {
      throw new Error(await readApiErrorDetail(response, `No se pudo iniciar ${phaseLabel}.`))
    }
    return waitForBackendPhase(targetJobId, phaseKey, phaseLabel)
  }

  const uploadDrivePackage = async (
    targetJobId: string,
    opts?: { phase?: string; includeZip?: boolean },
  ): Promise<DriveUploadResponse> => {
    const formData = new FormData()
    formData.append('driveFolderId', driveFolderId.trim())
    formData.append('includeZip', opts?.includeZip === false ? 'false' : 'true')
    if (opts?.phase) formData.append('phase', opts.phase)

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

  const executeDrivePipeline = async (existingJobId: string | null, options?: { force?: boolean }) => {
      const startNew = !existingJobId
      if (runLockRef.current) return
      if (startNew && !canStartNewDrivePackage) return
      if (!startNew && !canResumeDrivePackage && !options?.force) return

      runLockRef.current = true
      setIsRunning(true)
      setFailedDrivePhase(null)
      setStatus('leyendo syllabus')
      setDriveMessage(
        existingJobId
          ? 'Reanudando: solo se ejecutan las fases pendientes; lo ya generado en Drive se reutiliza cuando la API lo permite.'
          : 'Iniciando job: estructura y syllabus en Drive primero; luego cada fase se genera en el servidor y, al terminar, se publica en Drive (no durante la generación).',
      )
      if (startNew) {
        setDriveResult(null)
        setJobLogs([])
        setGeneratedDocuments([])
        setPhaseStatus(null)
      }
      clearPolling()

      let activeDrivePhase: DrivePhaseKey = 'granules'

      try {
        const jobId = existingJobId ?? (await createGranulesJob())
        setPackageJobId(jobId)
        saveDriveSession({
          jobId,
          driveFolderId: driveFolderId.trim(),
          prompt: selectedPrompt as PromptType,
        })

        const ensureGranulesDone = async () => {
          activeDrivePhase = 'granules'
          setDriveStage('granules')
          const payload = await fetchJobStatus(jobId)
          if (getBackendPhaseStatus(payload, 'granules') === 'completed') return
          if (getBackendPhaseStatus(payload, 'granules') === 'failed') {
            throw new Error('La fase de gránulos falló. Usa «Nuevo paquete» para empezar de cero.')
          }
          await waitForBackendPhase(jobId, 'granules', '1: generar gránulos')
        }

        const ensurePipelineDone = async () => {
          activeDrivePhase = 'activities'
          setDriveStage('activities')
          let payload = await fetchJobStatus(jobId)
          if (getBackendPhaseStatus(payload, 'pipelineLocal') === 'completed') return
          if (getBackendPhaseStatus(payload, 'pipelineLocal') === 'failed') {
            throw new Error('La fase de actividades falló. Reintenta el flujo o usa «Nuevo paquete».')
          }
          if (payload.status === 'running' && payload.currentPhase === 'pipelineLocal') {
            await waitForBackendPhase(jobId, 'pipelineLocal', '2: generar actividades')
            return
          }
          setDriveMessage('Generando actividades; al terminar esta fase se suben a Drive.')
          await postExistingJobPhase(jobId, `/api/jobs/${jobId}/pipeline-local`, 'generando txt', 'activities', 'pipelineLocal', '2: generar actividades')
        }

        const ensureMaterialsDone = async () => {
          activeDrivePhase = 'resources'
          setDriveStage('resources')
          let payload = await fetchJobStatus(jobId)
          if (getBackendPhaseStatus(payload, 'specializationMaterials') === 'completed') return
          if (getBackendPhaseStatus(payload, 'specializationMaterials') === 'failed') {
            throw new Error('La fase de recursos complementarios falló. Reintenta el flujo o usa «Nuevo paquete».')
          }
          if (payload.status === 'running' && payload.currentPhase === 'specializationMaterials') {
            await waitForBackendPhase(jobId, 'specializationMaterials', '3: generar recursos')
            return
          }
          setDriveMessage('Generando recursos complementarios; al terminar esta fase se suben a Drive.')
          await postExistingJobPhase(jobId, `/api/jobs/${jobId}/materials`, 'generando materiales', 'resources', 'specializationMaterials', '3: generar recursos')
        }

        await ensureGranulesDone()
        await ensurePipelineDone()
        await ensureMaterialsDone()

        activeDrivePhase = 'drive'
        const finalPayload = await fetchJobStatus(jobId)
        const ds = finalPayload.driveSync
        if (isPhasedDrivePackageComplete(ds)) {
          setDriveResult(snapshotToDriveUploadResponse(ds!, jobId))
          setDriveStage('ready')
          setStatus('finalizado')
          setDriveMessage('Paquete Drive listo (sincronizado por fases).')
        } else {
          setDriveStage('uploading')
          setStatus('organizando archivos')
          setDriveMessage('Completando sincronización final con Drive…')
          const drivePayload = await uploadDrivePackage(jobId, { phase: 'all', includeZip: false })
          setDriveResult(drivePayload)
          await fetchJobStatus(jobId)
          setDriveStage('ready')
          setStatus('finalizado')
          setDriveMessage('Paquete creado en Drive.')
        }
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
        if (activeDrivePhase === 'drive') console.error('[DrivePackage] Upload-drive falló', error)
        setDriveMessage(`Error en ${phaseNames[activeDrivePhase]}: ${detail}`)
      } finally {
        clearPolling()
        runLockRef.current = false
        setIsRunning(false)
      }
  }

  executeDrivePipelineRef.current = executeDrivePipeline

  const handleGenerateDrivePackage = () => void executeDrivePipeline(null)
  const handleResumeDrivePackage = () => {
    if (!packageJobId) return
    void executeDrivePipeline(packageJobId)
  }

  const cancelGeneration = async () => {
    if (!packageJobId) return
    try {
      const res = await apiFetch(`/api/jobs/${packageJobId}/cancel`, { method: 'POST' })
      if (!res.ok) {
        setDriveMessage(await readApiErrorDetail(res, 'No se pudo cancelar el proceso.'))
        return
      }
      clearPolling()
      runLockRef.current = false
      setIsRunning(false)
      setDriveMessage('Cancelación enviada. Lo ya completado se conserva; puedes usar «Continuar paquete» más tarde.')
      await fetchJobStatus(packageJobId)
    } catch (error) {
      setDriveMessage(error instanceof Error ? error.message : 'Error al cancelar.')
    }
  }

  const handleNewDrivePackage = () => {
    resetForNewSyllabus()
  }

  useEffect(() => {
    let cancelled = false
    const s = loadDriveSession()
    if (!s) return
    setPackageJobId(s.jobId)
    if (s.driveFolderId) setDriveFolderId(s.driveFolderId)
    if (s.prompt) setSelectedPrompt(s.prompt)
    void fetchJobStatus(s.jobId)
      .then((payload) => {
        if (cancelled) return
        applyJobStatus(payload)
        if (isPhasedDrivePackageComplete(payload.driveSync)) {
          setDriveStage('ready')
          setDriveResult(snapshotToDriveUploadResponse(payload.driveSync!, s.jobId))
          setStatus('finalizado')
          setDriveMessage('Paquete Drive listo (sincronizado por fases).')
          return
        }
        if (payload.status === 'running') {
          void executeDrivePipelineRef.current(s.jobId, { force: true })
        }
      })
      .catch(() => {
        clearDriveSession()
        setPackageJobId(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handlePromptChange = (prompt: PromptType | '') => {
    setSelectedPrompt(prompt)
    resetForNewSyllabus()
  }

  const getDrivePhaseState = (phaseKey: string): 'pending' | 'active' | 'completed' | 'error' => {
    const syllabusDone =
      hasSyllabus || Boolean(packageJobId && phaseStatus?.granules?.status && phaseStatus.granules.status !== 'pending')
    if (phaseKey === 'syllabus') return syllabusDone ? 'completed' : 'active'
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
      if (isPhasedDrivePackageComplete(driveSync)) return 'completed'
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
    return () => clearPolling()
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
            <p className="view-subtitle">
              Crea la misma estructura académica dentro de una carpeta de Google Drive. Durante cada fase, cada DOCX (y en actividades también cada TXT) se sube en cuanto se guarda; al terminar la fase se sincroniza de nuevo el conjunto. El contenido intermedio puede usar carpeta temporal del sistema; en el proyecto solo quedan metadatos y registros del job.
            </p>
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
                <div className="drive-package-actions">
                  {packageJobId && canResumeDrivePackage && (
                    <button
                      type="button"
                      className="primary-button primary-button--hero"
                      onClick={handleResumeDrivePackage}
                      disabled={isRunning}
                    >
                      Continuar paquete
                    </button>
                  )}
                  <button
                    type="button"
                    className={packageJobId && canResumeDrivePackage ? 'secondary-button' : 'primary-button primary-button--hero'}
                    onClick={handleGenerateDrivePackage}
                    disabled={!canStartNewDrivePackage || isRunning}
                  >
                    {driveActionLabel[driveStage]}
                  </button>
                  {packageJobId && (
                    <button type="button" className="secondary-button" onClick={handleNewDrivePackage} disabled={isRunning}>
                      Nuevo paquete
                    </button>
                  )}
                  {isRunning && packageJobId && (
                    <button type="button" className="secondary-button" onClick={() => void cancelGeneration()}>
                      Cancelar proceso
                    </button>
                  )}
                </div>
                {packageJobId && (
                  <p className="preview-alert is-info">
                    Job activo en esta sesión: <strong>{packageJobId}</strong>. Puedes recargar la página y continuar; usa «Nuevo paquete» para descartar el progreso guardado.
                  </p>
                )}
                {!driveFolderId.trim() && <p className="preview-alert is-info">Pega el ID de la carpeta Drive donde se creará el paquete académico.</p>}
                {displayedDriveMessage && <p className={`preview-alert ${driveStage === 'error' ? 'is-error' : 'is-info'}`}>{displayedDriveMessage}</p>}
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
                onRetry={() => (packageJobId ? handleResumeDrivePackage() : handleGenerateDrivePackage())}
              />

              <section className="action-card granule-card drive-upload-card">
                <div>
                  <span className="view-kicker">Resultado Drive</span>
                  <h2>{driveStage === 'ready' ? 'Paquete Drive listo' : driveStage === 'error' ? 'Error Drive' : 'Estado de subida Drive'}</h2>
                  <p className="card-description">
                    {driveSync?.drivePhasedSync
                      ? 'Cada archivo aparece en Drive en cuanto se guarda en disco (uno por uno). Al cerrar cada fase también se vuelve a sincronizar el bloque completo.'
                      : 'El paquete se subirá a Drive cuando finalicen gránulos, actividades y recursos.'}
                  </p>
                </div>
                {driveResult ? (
                  <>
                    <div className="syllabus-preview-rows">
                      <div><span>Carpetas creadas</span><strong>{driveResult.foldersCreated}</strong></div>
                      <div><span>Carpetas reutilizadas</span><strong>{driveResult.foldersReused}</strong></div>
                      <div><span>Archivos subidos</span><strong>{driveResult.filesUploaded}</strong></div>
                      <div><span>Archivos sobrescritos</span><strong>{driveResult.filesOverwritten}</strong></div>
                      <div><span>Carpeta Drive</span><strong><a href={driveResult.folderLink} target="_blank" rel="noreferrer">Carpeta destino</a></strong></div>
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

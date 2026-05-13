import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import FileDropzone from '../components/FileDropzone'
import JobProgressPanel from '../components/JobProgressPanel'
import PromptSelector from '../components/PromptSelector'
import ResultsPanel from '../components/ResultsPanel'
import { CATEGORY_CONFIGS, getCategoryConfig } from '../data/categories'
import { useJobPoller } from '../hooks/useJobPoller'
import { API_BASE_URL, apiFetch, isMissingJobResponse, readApiErrorDetail } from '../lib/api'
import { clearLocalSession, loadLocalSession, saveLocalSession } from '../lib/sessionStorage'
import { pickProgramFromPreview } from '../lib/pickProgramFromPreview'
import type { AvailableNextAction, CategoryConfig, GenerationStatus, GranuleMaterials, JobPhaseStatus, JobStatusResponse, PromptType, SyllabusPreviewResponse } from '../types/granules'

interface GranulesViewProps {
  onBack: () => void
}

const MISSING_JOB_MESSAGE = 'El proceso ya no existe, fue limpiado o el backend se reinició.'

type PipelineGeneralState =
  | 'idle'
  | 'syllabus_missing'
  | 'syllabus_loaded'
  | 'preview_ready'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'missing_job'
  | 'recoverable_error'

type PipelinePhaseKey = 'syllabus' | 'granules' | 'txt_docx' | 'materials' | 'zip'
type PipelinePhaseState = 'pending' | 'ready' | 'running' | 'completed' | 'failed' | 'cancelled' | 'stale'

interface PipelineState {
  general: PipelineGeneralState
  phases: Record<PipelinePhaseKey, PipelinePhaseState>
  primaryAction: 'none' | 'generate_granules' | 'generate_pipeline_local' | 'generate_materials' | 'download_zip' | 'retry_current_phase' | 'cancel'
  primaryLabel: string
  message: string
}

function GranulesView({ onBack }: GranulesViewProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptType | ''>('')
  const [detectedGranules, setDetectedGranules] = useState<Array<{ id: string; label: string }>>([])
  const [subjectName, setSubjectName] = useState('')
  const [programName, setProgramName] = useState('')
  const [isAnalyzingSyllabus, setIsAnalyzingSyllabus] = useState(false)
  const [previewMessage, setPreviewMessage] = useState('')
  const [status, setStatus] = useState<GenerationStatus>('pendiente')
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedDocuments, setGeneratedDocuments] = useState<string[]>([])
  const [materialesByGranule, setMaterialesByGranule] = useState<GranuleMaterials[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobLogs, setJobLogs] = useState<string[]>([])
  const [generationMessage, setGenerationMessage] = useState('')
  const [availableNextAction, setAvailableNextAction] = useState<AvailableNextAction>('generate_granules')
  const [phaseStatus, setPhaseStatus] = useState<JobPhaseStatus | null>(null)
  const [currentPhase, setCurrentPhase] = useState('pending')
  const [isFullPipelineRunning, setIsFullPipelineRunning] = useState(false)
  const [categories, setCategories] = useState<CategoryConfig[]>(CATEGORY_CONFIGS)
  const [localUiStatus, setLocalUiStatus] = useState<PipelineGeneralState>('idle')
  const [isCancelling, setIsCancelling] = useState(false)
  const pipelineCardRef = useRef<HTMLElement | null>(null)
  const resultsPanelRef = useRef<HTMLElement | null>(null)
  const prevAnalyzingSyllabusRef = useRef(false)
  const prevIsGeneratingRef = useRef(false)
  const canUploadSyllabus = Boolean(selectedPrompt)
  const hasSyllabus = Boolean(selectedFile)
  const selectedCategory = useMemo(() => categories.find((category) => category.key === selectedPrompt) ?? getCategoryConfig(selectedPrompt), [categories, selectedPrompt])
  const materialsDir = selectedCategory?.materialsDir ?? 'materials'
  const categoryLabel = selectedCategory?.label ?? 'categoría seleccionada'
  const materialsPerGranule = selectedCategory?.expectedMaterialsPerGranule ?? 0

  const localPhases = [
    { key: 'syllabus', number: '01', icon: 'DOC', title: 'Syllabus recibido' },
    { key: 'granules', number: '02', icon: 'G1', title: 'Gránulos' },
    { key: 'pipeline', number: '03', icon: 'TXT', title: 'TXT/DOCX' },
    { key: 'materials', number: '04', icon: '6x', title: 'Recursos' },
    { key: 'download', number: '05', icon: 'ZIP', title: 'ZIP final' },
  ] as const

  const applyJobPayload = useCallback((payload: JobStatusResponse) => {
    setStatus(payload.progressStep)
    setLocalUiStatus(payload.status === 'cancelled' ? 'cancelled' : payload.status === 'failed' ? 'failed' : payload.status === 'completed' ? 'completed' : payload.status === 'running' || payload.status === 'queued' ? 'running' : 'idle')
    setJobLogs(payload.logs ?? [])
    setGeneratedDocuments(payload.files ?? [])
    setPhaseStatus(payload.phaseStatus)
    setAvailableNextAction(payload.availableNextAction)
    setCurrentPhase(payload.currentPhase)
    if (payload.phaseStatus?.specializationMaterials.files?.length) {
      setMaterialesByGranule(parseMaterialesFromFiles(payload.phaseStatus.specializationMaterials.files, materialsDir))
    }
  }, [materialsDir])

  const { start: startPolling, stop: stopPolling } = useJobPoller({
    onStatus: (payload) => {
      applyJobPayload(payload)
    },
    onComplete: (payload) => {
      applyJobPayload(payload)
      setStatus('finalizado')
      setIsGenerating(false)
      setIsFullPipelineRunning(false)
    },
    onFailed: (payload) => {
      applyJobPayload(payload)
      setStatus('error')
      setIsGenerating(false)
      setIsFullPipelineRunning(false)
      setGenerationMessage('La fase falló. Los resultados anteriores quedan disponibles y puedes reintentar.')
    },
    onCancelled: (payload) => {
      applyJobPayload(payload)
      setStatus('cancelado')
      setLocalUiStatus('cancelled')
      setIsGenerating(false)
      setIsFullPipelineRunning(false)
      setIsCancelling(false)
      setGenerationMessage('Proceso cancelado. Puedes iniciar uno nuevo o continuar desde una fase válida si hay entregables disponibles.')
    },
    onMissing: (error) => {
      clearLocalSession()
      setJobId(null)
      setStatus('missing_job')
      setLocalUiStatus('missing_job')
      setIsGenerating(false)
      setIsFullPipelineRunning(false)
      setIsCancelling(false)
      setAvailableNextAction('generate_granules')
      setGenerationMessage(error)
    },
    onRecoverableError: (error) => {
      setStatus('recoverable_error')
      setLocalUiStatus('recoverable_error')
      setIsGenerating(false)
      setIsFullPipelineRunning(false)
      setGenerationMessage(error)
    },
  })

  const getLocalPhaseState = (phaseKey: string): 'pending' | 'active' | 'completed' | 'error' => {
    if (status === 'error') {
      if (currentPhase === 'granules' && phaseKey === 'granules') return 'error'
      if (currentPhase === 'pipelineLocal' && phaseKey === 'pipeline') return 'error'
      if (currentPhase === 'specializationMaterials' && phaseKey === 'materials') return 'error'
    }
    if (phaseKey === 'syllabus') return hasSyllabus ? 'completed' : 'active'
    if (phaseKey === 'granules') {
      if (isAnalyzingSyllabus) return 'active'
      if (phaseStatus?.granules.status === 'completed') return 'completed'
      if (detectedGranules.length > 0 && !jobId) return 'active'
      return currentPhase === 'granules' || status === 'generando gránulos' || status === 'generando documentos' ? 'active' : 'pending'
    }
    if (phaseKey === 'pipeline') {
      if (phaseStatus?.pipelineLocal.status === 'completed') return 'completed'
      return currentPhase === 'pipelineLocal' || status === 'generando txt' || status === 'generando docx' ? 'active' : 'pending'
    }
    if (phaseKey === 'materials') {
      if (phaseStatus?.specializationMaterials.status === 'completed') return 'completed'
      return currentPhase === 'specializationMaterials' || status === 'generando materiales especialización' || status === 'generando materiales' ? 'active' : 'pending'
    }
    if (phaseKey === 'download') return availableNextAction === 'download_package' ? 'completed' : 'pending'
    return 'pending'
  }

  const alignTopWithViewport = useCallback((el: HTMLElement | null) => {
    if (!el) return
    const reduceMotion =
      typeof window.matchMedia !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const y = Math.round(window.scrollY + el.getBoundingClientRect().top)
    window.scrollTo({
      top: Math.max(0, y),
      behavior: reduceMotion ? 'auto' : 'smooth',
    })
  }, [])

  const alignPipelineTopWithViewport = useCallback(() => {
    alignTopWithViewport(pipelineCardRef.current)
  }, [alignTopWithViewport])

  const resetForNewSyllabus = () => {
    setStatus('pendiente')
    setGeneratedDocuments([])
    setMaterialesByGranule([])
    setIsGenerating(false)
    setJobLogs([])
    setJobId(null)
    setAvailableNextAction('generate_granules')
    setPhaseStatus(null)
    setCurrentPhase('pending')
    setIsFullPipelineRunning(false)
    setLocalUiStatus('idle')
    setSubjectName('')
    setProgramName('')
    setPreviewMessage('')
    setGenerationMessage('')
    setSelectedFile(null)
    setDetectedGranules([])
    setIsAnalyzingSyllabus(false)
    stopPolling()
    clearLocalSession()
  }

  function parseMaterialesFromFiles(files: string[], matDir: string): GranuleMaterials[] {
    const granuleMap = new Map<string, GranuleMaterials>()
    for (const relativePath of files) {
      if (!relativePath.startsWith(`${matDir}/`)) continue
      const parts = relativePath.split('/')
      const folder = parts[1] ?? ''
      const name = parts[2] ?? ''
      const match = name.match(/^\d+_(G\d+)_/i) ?? folder.match(/^(G\d+)_/i)
      if (!match || !name) continue
      const granuleCode = match[1]
      if (!granuleMap.has(granuleCode)) {
        granuleMap.set(granuleCode, { granuleCode, granuleFolder: folder, files: [], totalMaterials: 0 })
      }
      const granuleMat = granuleMap.get(granuleCode)!
      granuleMat.files.push({ granule: granuleCode, name, relativePath })
      granuleMat.totalMaterials = granuleMat.files.length
    }
    return Array.from(granuleMap.values()).sort((a, b) => a.granuleCode.localeCompare(b.granuleCode))
  }

  const analyzeSyllabusPreview = async (file: File) => {
    setIsAnalyzingSyllabus(true)
    setPreviewMessage('Analizando estructura temática...')
    setDetectedGranules([])
    try {
      const formData = new FormData()
      formData.append('syllabus', file)
      const response = await apiFetch('/api/syllabus/preview', { method: 'POST', body: formData })
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
      setProgramName(pickProgramFromPreview(preview))
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

  const createGranulesJob = async (): Promise<string> => {
    if (!selectedFile || !selectedPrompt) throw new Error('Falta seleccionar syllabus y nivel académico.')
    const formData = new FormData()
    formData.append('syllabus', selectedFile)
    formData.append('nivel', selectedPrompt)
    const createResponse = await apiFetch('/api/jobs', { method: 'POST', body: formData })
    if (!createResponse.ok) {
      throw new Error(await readApiErrorDetail(createResponse, 'No se pudo crear el job de generación.'))
    }
    const createdJob = (await createResponse.json()) as { jobId: string; status: string }
    setJobId(createdJob.jobId)
    saveLocalSession(createdJob.jobId, selectedPrompt)
    return createdJob.jobId
  }

  const startPhaseWithPolling = async (path: string, runningStatus: GenerationStatus, message: string) => {
    if (!jobId || isGenerating) return
    stopPolling()
    setIsGenerating(true)
    setStatus(runningStatus)
    setGenerationMessage(message)
    setAvailableNextAction('none')
    try {
      const response = await apiFetch(path, { method: 'POST' })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo iniciar la fase.'))
      }
      startPolling(jobId)
    } catch (error) {
      setStatus('error')
      setIsGenerating(false)
      setGenerationMessage(error instanceof Error ? error.message : 'Error iniciando la fase.')
    }
  }

  const handleGenerate = async () => {
    if (!selectedFile || !selectedPrompt || isGenerating || detectedGranules.length === 0) return
    stopPolling()
    setIsGenerating(true)
    setJobLogs([])
    setGeneratedDocuments([])
    setMaterialesByGranule([])
    setJobId(null)
    setPhaseStatus(null)
    setAvailableNextAction('none')
    setStatus('leyendo syllabus')
    setGenerationMessage(`Fase 1: generando gránulos de ${categoryLabel}. Al finalizar podrás continuar con TXT/DOCX académicos.`)
    try {
      const createdJobId = await createGranulesJob()
      setStatus('pendiente')
      startPolling(createdJobId)
    } catch (error) {
      setStatus('error')
      setIsGenerating(false)
      setGenerationMessage(error instanceof Error ? error.message : 'Error iniciando la generación.')
    }
  }

  const handleGeneratePipelineLocal = () => {
    if (!jobId) return
    void startPhaseWithPolling(`/api/jobs/${jobId}/pipeline-local`, 'generando txt', 'Fase 2: generando TXT y DOCX académicos con el pipeline local existente.')
  }

  const handleGenerateMaterials = () => {
    if (!jobId) return
    void startPhaseWithPolling(`/api/jobs/${jobId}/materials`, 'generando materiales', `Fase 3: generando materiales de ${categoryLabel} por gránulo.`)
  }

  const handleRetryGranules = () => {
    if (!jobId || isGenerating) return
    stopPolling()
    setIsGenerating(true)
    setStatus('generando gránulos')
    setLocalUiStatus('running')
    setGenerationMessage('Reintentando Fase 1: gránulos. Las fases posteriores quedarán pendientes si aplica.')
    void (async () => {
      try {
        const response = await apiFetch(`/api/jobs/${jobId}/retry-granules`, { method: 'POST' })
        if (!response.ok) throw new Error(await readApiErrorDetail(response, 'No se pudo reintentar gránulos.'))
        startPolling(jobId)
      } catch (error) {
        setStatus('error')
        setLocalUiStatus('failed')
        setIsGenerating(false)
        setGenerationMessage(error instanceof Error ? error.message : 'Error reintentando gránulos.')
      }
    })()
  }

  const handleRetryPipelineLocal = () => {
    if (!jobId || isGenerating) return
    stopPolling()
    setIsGenerating(true)
    setStatus('generando txt')
    setLocalUiStatus('running')
    setGenerationMessage('Reintentando Fase 2: TXT/DOCX sin regenerar gránulos.')
    void (async () => {
      try {
        const response = await apiFetch(`/api/jobs/${jobId}/retry-pipeline-local`, { method: 'POST' })
        if (!response.ok) throw new Error(await readApiErrorDetail(response, 'No se pudo reintentar TXT/DOCX.'))
        startPolling(jobId)
      } catch (error) {
        setStatus('error')
        setLocalUiStatus('failed')
        setIsGenerating(false)
        setGenerationMessage(error instanceof Error ? error.message : 'Error reintentando TXT/DOCX.')
      }
    })()
  }

  const handleRetryMaterials = () => {
    if (!jobId || isGenerating) return
    stopPolling()
    setIsGenerating(true)
    setStatus('generando materiales')
    setLocalUiStatus('running')
    setGenerationMessage('Reintentando Fase 3: recursos/materiales sin regenerar fases previas.')
    void (async () => {
      try {
        const response = await apiFetch(`/api/jobs/${jobId}/retry-materials`, { method: 'POST' })
        if (!response.ok) throw new Error(await readApiErrorDetail(response, 'No se pudo reintentar recursos.'))
        startPolling(jobId)
      } catch (error) {
        setStatus('error')
        setLocalUiStatus('failed')
        setIsGenerating(false)
        setGenerationMessage(error instanceof Error ? error.message : 'Error reintentando recursos.')
      }
    })()
  }

  const handleGenerateFullLocalPackage = async () => {
    if (!selectedFile || !selectedPrompt || isGenerating || isFullPipelineRunning || detectedGranules.length === 0) return
    stopPolling()
    setIsFullPipelineRunning(true)
    setIsGenerating(true)
    setJobLogs([])
    setGeneratedDocuments([])
    setMaterialesByGranule([])
    setJobId(null)
    setPhaseStatus(null)
    setAvailableNextAction('none')
    setStatus('leyendo syllabus')
    setGenerationMessage(`Flujo completo: generando gránulos, luego TXT/DOCX y materiales de ${categoryLabel} por gránulo.`)
    try {
      const createdJobId = await createGranulesJob()
      setJobId(createdJobId)
      startPolling(createdJobId)
      await new Promise<void>((resolve, reject) => {
        const check = setInterval(async () => {
          try {
            const resp = await apiFetch(`/api/jobs/${createdJobId}`)
            if (!resp.ok) { clearInterval(check); reject(new Error('Job perdido durante flujo completo.')); return }
            const payload = (await resp.json()) as JobStatusResponse
            applyJobPayload(payload)
            if (payload.status === 'completed' || payload.status === 'failed' || payload.status === 'cancelled') {
              clearInterval(check)
              if (payload.status === 'failed') reject(new Error('Error en fase 1: generar gránulos.'))
              else if (payload.status === 'cancelled') reject(new Error('Proceso cancelado.'))
              else resolve()
            }
          } catch (e) {
            clearInterval(check)
            reject(e)
          }
        }, 3000)
      })
      stopPolling()
      await startPhaseWithPolling(`/api/jobs/${createdJobId}/pipeline-local`, 'generando txt', 'Fase 2: generando TXT/DOCX académicos.')
      await new Promise<void>((resolve, reject) => {
        const check = setInterval(async () => {
          try {
            const resp = await apiFetch(`/api/jobs/${createdJobId}`)
            if (!resp.ok) { clearInterval(check); reject(new Error('Job perdido durante fase 2.')); return }
            const payload = (await resp.json()) as JobStatusResponse
            applyJobPayload(payload)
            if (payload.status === 'completed' || payload.status === 'failed' || payload.status === 'cancelled') {
              clearInterval(check)
              if (payload.status === 'failed') reject(new Error('Error en fase 2.'))
              else resolve()
            }
          } catch (e) {
            clearInterval(check)
            reject(e)
          }
        }, 3000)
      })
      stopPolling()
      await startPhaseWithPolling(`/api/jobs/${createdJobId}/materials`, 'generando materiales', 'Fase 3: generando materiales por gránulo.')
      setStatus('finalizado')
      setGenerationMessage('Paquete completo listo. Puedes descargar el ZIP final institucional.')
    } catch (error) {
      setStatus('error')
      setGenerationMessage(error instanceof Error ? error.message : 'Error ejecutando el flujo completo local.')
    } finally {
      setIsGenerating(false)
      setIsFullPipelineRunning(false)
    }
  }

  const handleRetryCurrentPhase = () => {
    if (phaseStatus?.specializationMaterials.status === 'failed') { handleRetryMaterials(); return }
    if (phaseStatus?.pipelineLocal.status === 'failed') { handleRetryPipelineLocal(); return }
    if (phaseStatus?.granules.status === 'failed') { handleRetryGranules(); return }
    if (jobId) { handleRetryGranules() } else { void handleGenerate() }
  }

  const handleCancelJob = () => {
    if (!jobId || isCancelling) return
    stopPolling()
    setIsCancelling(true)
    setIsGenerating(false)
    setIsFullPipelineRunning(false)
    setStatus('cancelado')
    setLocalUiStatus('cancelled')
    setGenerationMessage('Proceso cancelado. Puedes iniciar uno nuevo o continuar desde una fase válida si hay entregables disponibles.')
    void (async () => {
      try {
        const response = await apiFetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
        if (response.ok) {
          await apiFetch(`/api/jobs/${jobId}`).catch(() => undefined)
        } else if (isMissingJobResponse(response)) {
          clearLocalSession()
          setJobId(null)
          setStatus('missing_job')
          setLocalUiStatus('missing_job')
          setGenerationMessage(MISSING_JOB_MESSAGE)
        } else {
          setGenerationMessage(await readApiErrorDetail(response, 'No se pudo cancelar el proceso en backend, pero se detuvo el seguimiento local.'))
        }
      } catch (error) {
        setGenerationMessage(error instanceof Error ? error.message : 'No se pudo contactar el backend para cancelar.')
      } finally {
        setIsCancelling(false)
      }
    })()
  }

  const handleReset = () => { resetForNewSyllabus() }

  const handlePromptChange = (prompt: PromptType | '') => {
    setSelectedPrompt(prompt)
    handleReset()
  }

  useEffect(() => {
    let cancelled = false
    apiFetch('/api/categories')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('No categories')))
      .then((payload: CategoryConfig[]) => {
        if (!cancelled && Array.isArray(payload) && payload.length > 0) setCategories(payload)
      })
      .catch(() => { if (!cancelled) setCategories(CATEGORY_CONFIGS) })
    return () => { cancelled = true }
  }, [])

  const consoleStatus = status === 'error'
    ? 'Error'
    : status === 'cancelado' || localUiStatus === 'cancelled'
      ? 'Cancelado'
      : localUiStatus === 'missing_job'
        ? 'Proceso no disponible'
        : localUiStatus === 'recoverable_error'
          ? 'Revisar backend'
    : availableNextAction === 'download_package'
      ? 'Paquete listo'
      : isGenerating
        ? 'Procesando'
        : 'Sistema listo'

  const canRunFullPackage = Boolean(selectedFile) && detectedGranules.length > 0 && !isGenerating && !isFullPipelineRunning

  const pipelineState: PipelineState = useMemo(() => {
    const granules = phaseStatus?.granules.status ?? 'pending'
    const txtDocx = phaseStatus?.pipelineLocal.status ?? 'pending'
    const materials = phaseStatus?.specializationMaterials.status ?? 'pending'
    const zipCompleted = availableNextAction === 'download_package'
    const phases: PipelineState['phases'] = {
      syllabus: hasSyllabus ? 'completed' : 'pending',
      granules: granules === 'completed' ? 'completed' : granules === 'failed' ? 'failed' : granules === 'cancelled' ? 'cancelled' : currentPhase === 'granules' || status === 'generando gránulos' || status === 'generando documentos' ? 'running' : hasSyllabus && detectedGranules.length > 0 ? 'ready' : 'pending',
      txt_docx: txtDocx === 'completed' ? 'completed' : txtDocx === 'failed' ? 'failed' : txtDocx === 'cancelled' ? 'cancelled' : currentPhase === 'pipelineLocal' || status === 'generando txt' || status === 'generando docx' ? 'running' : granules === 'completed' ? 'ready' : 'pending',
      materials: materials === 'completed' ? 'completed' : materials === 'failed' ? 'failed' : materials === 'cancelled' ? 'cancelled' : currentPhase === 'specializationMaterials' || status === 'generando materiales' || status === 'generando materiales especialización' ? 'running' : txtDocx === 'completed' ? 'ready' : granules === 'completed' ? 'stale' : 'pending',
      zip: zipCompleted ? 'completed' : materials === 'completed' ? 'ready' : 'pending',
    }
    if (isGenerating || isCancelling) return { general: 'running', phases, primaryAction: 'cancel', primaryLabel: isCancelling ? 'Cancelando...' : 'Cancelar proceso', message: 'Hay una fase en ejecución. Puedes cancelar el proceso sin recargar la página.' }
    if (localUiStatus === 'missing_job') return { general: 'missing_job', phases, primaryAction: 'none', primaryLabel: '', message: MISSING_JOB_MESSAGE }
    if (localUiStatus === 'recoverable_error') return { general: 'recoverable_error', phases, primaryAction: 'none', primaryLabel: '', message: generationMessage || 'No fue posible consultar el backend. Revisa el servicio e intenta de nuevo.' }
    if (localUiStatus === 'cancelled' || status === 'cancelado') return { general: 'cancelled', phases, primaryAction: 'none', primaryLabel: '', message: generationMessage || 'Proceso cancelado. Puedes iniciar uno nuevo o continuar desde una fase válida si hay entregables disponibles.' }
    if (!hasSyllabus) return { general: 'syllabus_missing', phases, primaryAction: 'none', primaryLabel: '', message: 'Carga un syllabus .docx para comenzar.' }
    if (status === 'error' || granules === 'failed' || txtDocx === 'failed' || materials === 'failed') return { general: 'failed', phases, primaryAction: 'retry_current_phase', primaryLabel: 'Reintentar fase actual', message: generationMessage || 'La fase activa falló. Puedes reintentar solo esa fase.' }
    if (zipCompleted) return { general: 'completed', phases, primaryAction: 'download_zip', primaryLabel: 'Descargar ZIP final', message: 'ZIP final disponible con nombres internos cortos compatibles con Windows.' }
    if (materials === 'completed') return { general: 'preview_ready', phases, primaryAction: 'download_zip', primaryLabel: 'Generar ZIP final', message: 'Todas las fases están completas. Descarga el ZIP final.' }
    if (txtDocx === 'completed') return { general: 'preview_ready', phases, primaryAction: 'generate_materials', primaryLabel: 'Generar recursos', message: 'TXT/DOCX listos. Continúa con los recursos por gránulo.' }
    if (granules === 'completed') return { general: 'preview_ready', phases, primaryAction: 'generate_pipeline_local', primaryLabel: 'Generar TXT/DOCX', message: 'Gránulos listos. Continúa con TXT/DOCX académicos.' }
    if (detectedGranules.length > 0) return { general: 'preview_ready', phases, primaryAction: 'generate_granules', primaryLabel: 'Generar gránulos', message: 'Preview detectado. Inicia la Fase 1 cuando quieras.' }
    return { general: 'syllabus_loaded', phases, primaryAction: 'none', primaryLabel: '', message: previewMessage || 'Analiza el syllabus para detectar gránulos antes de generar.' }
  }, [availableNextAction, currentPhase, detectedGranules.length, generationMessage, hasSyllabus, isCancelling, isGenerating, localUiStatus, phaseStatus, previewMessage, status])

  const handlePrimaryPipelineAction = () => {
    if (pipelineState.primaryAction === 'cancel') handleCancelJob()
    if (pipelineState.primaryAction === 'generate_granules') void handleGenerate()
    if (pipelineState.primaryAction === 'generate_pipeline_local') handleGeneratePipelineLocal()
    if (pipelineState.primaryAction === 'generate_materials') handleGenerateMaterials()
    if (pipelineState.primaryAction === 'retry_current_phase') handleRetryCurrentPhase()
  }

  useEffect(() => {
    const session = loadLocalSession()
    if (!session?.jobId) return
    let cancelled = false
    void apiFetch(`/api/jobs/${session.jobId}`)
      .then(async (response) => {
        if (cancelled) return
        if (isMissingJobResponse(response)) {
          clearLocalSession()
          setJobId(null)
          setStatus('missing_job')
          setLocalUiStatus('missing_job')
          setGenerationMessage(MISSING_JOB_MESSAGE)
          return
        }
        if (!response.ok) {
          clearLocalSession()
          return
        }
        const payload = (await response.json()) as JobStatusResponse
        setJobId(session.jobId)
        if (session.prompt) setSelectedPrompt(session.prompt as PromptType)
        applyJobPayload(payload)
        if (payload.status === 'running' || payload.status === 'queued') {
          startPolling(session.jobId)
        }
      })
      .catch(() => { if (!cancelled) clearLocalSession() })
    return () => { cancelled = true }
  }, [applyJobPayload, startPolling])

  useEffect(() => {
    if (!selectedFile || !canUploadSyllabus) return
    const t = window.setTimeout(() => { alignPipelineTopWithViewport() }, 180)
    return () => window.clearTimeout(t)
  }, [selectedFile, canUploadSyllabus, alignPipelineTopWithViewport])

  useEffect(() => {
    if (!selectedFile || !canUploadSyllabus) { prevAnalyzingSyllabusRef.current = false; return }
    const finishedAnalysis = prevAnalyzingSyllabusRef.current === true && isAnalyzingSyllabus === false
    prevAnalyzingSyllabusRef.current = isAnalyzingSyllabus
    if (!finishedAnalysis) return
    const t = window.setTimeout(() => alignPipelineTopWithViewport(), 120)
    return () => window.clearTimeout(t)
  }, [selectedFile, canUploadSyllabus, isAnalyzingSyllabus, alignPipelineTopWithViewport])

  useEffect(() => {
    if (!canUploadSyllabus || !hasSyllabus) { prevIsGeneratingRef.current = false; return }
    const generationStarted = !prevIsGeneratingRef.current && isGenerating
    prevIsGeneratingRef.current = isGenerating
    if (!generationStarted) return
    const t = window.setTimeout(() => { alignTopWithViewport(resultsPanelRef.current) }, 180)
    return () => window.clearTimeout(t)
  }, [canUploadSyllabus, hasSyllabus, isGenerating, alignTopWithViewport])

  return (
    <div className="granules-view">
      <div className="granules-view-content">
        <div className="view-header generation-console-header">
          <BackButton onBack={onBack} />
          <span className="generation-header-badge">Pipeline local</span>
          <div className="view-header-text">
            <h1 className="view-title">Generar paquete local</h1>
            <p className="view-subtitle">Consola inteligente para convertir un syllabus en un paquete académico completo.</p>
          </div>
          <span className={`generation-status-pill generation-status-pill--${status === 'error' ? 'error' : availableNextAction === 'download_package' ? 'ready' : isGenerating ? 'live' : 'idle'}`}>
            {consoleStatus}
          </span>
        </div>

        <section className="generation-console">
          <aside className="config-console-panel">
            <div className="config-console-shell">
              <div className="config-console-shell-header">
                <span className="view-kicker">Configuración</span>
                <h2>Panel del pipeline</h2>
                <p>Define el nivel, carga el syllabus y lanza la generación completa desde un solo lugar.</p>
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
                  handleReset()
                  setSelectedFile(file)
                  if (!file) { setDetectedGranules([]); setPreviewMessage(''); return }
                  if (!file.name.toLowerCase().endsWith('.docx')) { setDetectedGranules([]); setPreviewMessage('El archivo debe ser .docx'); return }
                  await analyzeSyllabusPreview(file)
                }}
              />
            )}

            <section className="action-card local-full-run-card console-primary-action">
              <div>
                <span className="view-kicker">Acción principal</span>
                <h2>Generar por pasos</h2>
                <p className="card-description">Avanza fase por fase para controlar, reintentar y descargar cada entregable.</p>
              </div>
              <p className={`preview-alert ${pipelineState.general === 'failed' || pipelineState.general === 'missing_job' || pipelineState.general === 'recoverable_error' ? 'is-error' : 'is-info'}`}>
                {pipelineState.message}
              </p>
              {pipelineState.primaryAction === 'download_zip' && jobId ? (
                <a className="primary-button primary-button--hero link-button" href={`${API_BASE_URL}/api/jobs/${jobId}/download-all`} target="_blank" rel="noreferrer">
                  {pipelineState.primaryLabel}
                </a>
              ) : pipelineState.primaryAction !== 'none' ? (
                <button type="button" className="primary-button primary-button--hero" onClick={handlePrimaryPipelineAction}>
                  {pipelineState.primaryLabel}
                </button>
              ) : null}
              <div className="console-secondary-actions">
                {jobId && !isGenerating && <button type="button" className="secondary-button" onClick={handleReset}>Limpiar sesión</button>}
                {jobId && (phaseStatus?.granules.status === 'failed' || phaseStatus?.granules.status === 'completed') && !isGenerating && (
                  <button type="button" className="secondary-button" onClick={handleRetryGranules}>Regenerar gránulos</button>
                )}
                {jobId && phaseStatus?.granules.status === 'completed' && (phaseStatus?.pipelineLocal.status === 'failed' || phaseStatus?.pipelineLocal.status === 'completed') && !isGenerating && (
                  <button type="button" className="secondary-button" onClick={handleRetryPipelineLocal}>Regenerar TXT/DOCX</button>
                )}
                {jobId && phaseStatus?.pipelineLocal.status === 'completed' && (phaseStatus?.specializationMaterials.status === 'failed' || phaseStatus?.specializationMaterials.status === 'completed') && !isGenerating && (
                  <button type="button" className="secondary-button" onClick={handleRetryMaterials}>Regenerar recursos</button>
                )}
                {jobId && generatedDocuments.length > 0 && (
                  <a className="secondary-button link-button" href={`${API_BASE_URL}/api/jobs/${jobId}/download/granules`} target="_blank" rel="noreferrer">Descargar gránulos</a>
                )}
              </div>
            </section>

            <section className="action-card granule-card console-advanced-action">
              <div>
                <span className="view-kicker">Opción avanzada</span>
                <h2>Generar paquete completo</h2>
                <p className="card-description">Ejecuta todas las fases en secuencia. Úsalo cuando no necesites revisar o descargar entregables intermedios.</p>
              </div>
              {canRunFullPackage ? (
                <button type="button" className="secondary-button" onClick={handleGenerateFullLocalPackage}>
                  {isFullPipelineRunning ? 'Generando paquete...' : 'Generar paquete académico completo'}
                </button>
              ) : (
                <p className="muted">Disponible cuando el syllabus tenga preview detectado y no haya una fase activa.</p>
              )}
            </section>

            <section ref={pipelineCardRef} className="granule-card syllabus-compact-preview granules-pipeline-scroll-target">
              <div className="granule-card-header">
                <span className="granule-card-kicker">PREVIEW</span>
              </div>
              <div className="syllabus-preview-rows">
                <div><span>Archivo</span><strong>{selectedFile?.name ?? 'Pendiente'}</strong></div>
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
                  <span className="view-kicker">Mapa del flujo</span>
                  <h2>Pipeline académico</h2>
                </div>
                <span className={`local-flow-live ${isGenerating ? 'is-live' : ''}`}>{consoleStatus}</span>
              </div>
              <div className="local-flow-stepper console-flow-stepper">
                {localPhases.map((phase) => {
                  const phaseState = getLocalPhaseState(phase.key)
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
                isGenerating={isGenerating}
                isError={status === 'error'}
                generatedFilesCount={generatedDocuments.length}
                totalMaterialsExpected={detectedGranules.length * materialsPerGranule}
                materialsPerGranule={materialsPerGranule}
                deliverables={selectedCategory?.deliverables ?? []}
                categoryLabel={categoryLabel}
                backendCurrentPhase={currentPhase}
                phaseStatus={phaseStatus}
                availableNextAction={availableNextAction}
                uiState={pipelineState.general}
                message={generationMessage || pipelineState.message}
                onRetry={handleRetryCurrentPhase}
              />

              <ResultsPanel
                jobId={jobId}
                documents={generatedDocuments}
                materialesByGranule={materialesByGranule}
                isVisible={Boolean(jobId)}
                phaseStatus={phaseStatus}
                availableNextAction={availableNextAction}
                isGenerating={isGenerating}
                onGeneratePipelineLocal={handleGeneratePipelineLocal}
                onGenerateSpecializationMaterials={handleGenerateMaterials}
                category={selectedCategory}
              />
            </section>
          </aside>
        </section>
      </div>
    </div>
  )
}

export default GranulesView

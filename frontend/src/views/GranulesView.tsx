import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import FileDropzone from '../components/FileDropzone'
import JobProgressPanel from '../components/JobProgressPanel'
import PromptSelector from '../components/PromptSelector'
import ResultsPanel from '../components/ResultsPanel'
import { CATEGORY_CONFIGS, getCategoryConfig } from '../data/categories'
import { API_BASE_URL, apiFetch } from '../lib/api'
import { normalizeJobStatus } from '../lib/normalizeJobStatus'
import { clearLocalSession, loadLocalSession, saveLocalSession } from '../lib/sessionStorage'
import { pickProgramFromPreview } from '../lib/pickProgramFromPreview'
import {
  useCancelJob,
  useCreateJob,
  useJobStatus,
  useRetryGranules,
  useRetryMaterials,
  useRetryPipelineLocal,
  useRunMaterials,
  useRunPipelineLocal,
  useSyllabusPreview,
} from '../queries/jobs'
import type { AvailableNextAction, CategoryConfig, GenerationStatus, GranuleMaterials, GranulesMetrics, JobStatusResponse, PromptType, SyllabusPreviewResponse } from '../types/granules'

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

function GranulesView({ onBack }: GranulesViewProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [syllabusFileName, setSyllabusFileName] = useState<string>('')
  const [selectedPrompt, setSelectedPrompt] = useState<PromptType | ''>('')
  const [detectedGranules, setDetectedGranules] = useState<Array<{ id: string; label: string }>>([])
  const [subjectName, setSubjectName] = useState('')
  const [programName, setProgramName] = useState('')
  const [isAnalyzingSyllabus, setIsAnalyzingSyllabus] = useState(false)
  const [previewMessage, setPreviewMessage] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationMessage, setGenerationMessage] = useState('')
  const [isFullPipelineRunning, setIsFullPipelineRunning] = useState(false)
  const [categories, setCategories] = useState<CategoryConfig[]>(CATEGORY_CONFIGS)
  const [isCancelling, setIsCancelling] = useState(false)
  const pipelineCardRef = useRef<HTMLElement | null>(null)
  const resultsPanelRef = useRef<HTMLElement | null>(null)
  const prevAnalyzingSyllabusRef = useRef(false)
  const prevIsGeneratingRef = useRef(false)
  const canUploadSyllabus = Boolean(selectedPrompt)
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

  const [hydratedJobId, setHydratedJobId] = useState<string | null>(null)

  const { data: jobData } = useJobStatus(hydratedJobId, {
    onMissing: () => {
      clearLocalSession()
      setHydratedJobId(null)
    },
  })

  const hasSyllabus = Boolean(selectedFile || syllabusFileName || jobData?.syllabusOriginalName)

  const normalizedJob = useMemo(() => {
    if (!jobData) return null
    return normalizeJobStatus(jobData)
  }, [jobData])

  const status: GenerationStatus = normalizedJob?.status === 'running' || normalizedJob?.status === 'queued'
    ? jobData?.progressStep ?? 'pendiente'
    : normalizedJob?.status === 'completed'
      ? 'finalizado'
      : normalizedJob?.status === 'failed'
        ? 'error'
        : normalizedJob?.status === 'cancelled'
          ? 'cancelado'
          : normalizedJob?.status === 'missing_job'
            ? 'missing_job'
            : 'pendiente'

  const localUiStatus: PipelineGeneralState = normalizedJob?.status === 'cancelled' ? 'cancelled'
    : normalizedJob?.status === 'missing_job' ? 'missing_job'
    : normalizedJob?.status === 'recoverable_error' ? 'recoverable_error'
    : normalizedJob?.status === 'completed' ? 'completed'
    : normalizedJob?.status === 'failed' ? 'failed'
    : (normalizedJob?.status === 'running' || normalizedJob?.status === 'queued') ? 'running'
    : 'idle'

  const phaseStatus = jobData?.phaseStatus ?? null
  const currentPhase = jobData?.currentPhase ?? 'pending'
  const availableNextAction = (jobData?.availableNextAction ?? 'none') as AvailableNextAction
  const jobLogs = jobData?.logs ?? []
  const generatedDocuments = jobData?.files ?? []
  const jobId = hydratedJobId
  const metrics = (jobData?.metrics ?? null) as GranulesMetrics | null
  const [metricsOpen, setMetricsOpen] = useState(false)

  const materialesByGranule = useMemo(() => {
    const filesFromStatus = phaseStatus?.specializationMaterials?.files ?? []
    return filesFromStatus.length > 0 ? parseMaterialesFromFiles(filesFromStatus, materialsDir) : []
  }, [phaseStatus, materialsDir])

  const createJobMutation = useCreateJob()
  const cancelJobMutation = useCancelJob()
  const runPipelineLocalMutation = useRunPipelineLocal()
  const runMaterialsMutation = useRunMaterials()
  const retryGranulesMutation = useRetryGranules()
  const retryPipelineLocalMutation = useRetryPipelineLocal()
  const retryMaterialsMutation = useRetryMaterials()
  const syllabusPreviewMutation = useSyllabusPreview()

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
    const reduceMotion = typeof window.matchMedia !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const y = Math.round(window.scrollY + el.getBoundingClientRect().top)
    window.scrollTo({ top: Math.max(0, y), behavior: reduceMotion ? 'auto' : 'smooth' })
  }, [])

  const alignPipelineTopWithViewport = useCallback(() => { alignTopWithViewport(pipelineCardRef.current) }, [alignTopWithViewport])

  const resetForNewSyllabus = () => {
    setDetectedGranules([])
    setSubjectName('')
    setProgramName('')
    setPreviewMessage('')
    setSelectedFile(null)
    setSyllabusFileName('')
    setIsAnalyzingSyllabus(false)
    clearLocalSession()
    setHydratedJobId(null)
  }

  const analyzeSyllabusPreview = async (file: File) => {
    setIsAnalyzingSyllabus(true)
    setPreviewMessage('Analizando estructura temática...')
    setDetectedGranules([])
    try {
      const preview = await syllabusPreviewMutation.mutateAsync(file)
      const p = preview as SyllabusPreviewResponse
      const selectedCourse = p.selectedCourse
      const selectedTopics = selectedCourse?.temas?.length
        ? selectedCourse.temas.map((title, index) => ({ index: index + 1, title }))
        : p.detectedTopics
      setSubjectName(selectedCourse?.asignatura || p.subjectName || '')
      setProgramName(pickProgramFromPreview(p))
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

  const handleGenerate = async () => {
    if (!selectedFile || !selectedPrompt || isGenerating || detectedGranules.length === 0) return
    setIsGenerating(true)
    setGenerationMessage(`Fase 1: generando gránulos de ${categoryLabel}. Al finalizar podrás continuar con TXT/DOCX académicos.`)
    try {
      const created = await createJobMutation.mutateAsync({ syllabus: selectedFile, nivel: selectedPrompt })
      setHydratedJobId(created.jobId)
      saveLocalSession({
        jobId: created.jobId,
        prompt: selectedPrompt,
        subjectName,
        programName,
        detectedGranules,
        previewMessage,
        syllabusFileName: selectedFile?.name,
      })
    } catch (error) {
      setGenerationMessage(error instanceof Error ? error.message : 'Error iniciando la generación.')
      setIsGenerating(false)
    }
  }

  const handleGeneratePipelineLocal = async () => {
    if (!jobId || isGenerating) return
    setIsGenerating(true)
    setGenerationMessage('Fase 2: generando TXT y DOCX académicos con el pipeline local existente.')
    try {
      await runPipelineLocalMutation.mutateAsync(jobId)
    } catch (error) {
      setGenerationMessage(error instanceof Error ? error.message : 'Error iniciando la fase.')
      setIsGenerating(false)
    }
  }

  const handleGenerateMaterials = async () => {
    if (!jobId || isGenerating) return
    setIsGenerating(true)
    setGenerationMessage(`Fase 3: generando materiales de ${categoryLabel} por gránulo.`)
    try {
      await runMaterialsMutation.mutateAsync(jobId)
    } catch (error) {
      setGenerationMessage(error instanceof Error ? error.message : 'Error iniciando la fase.')
      setIsGenerating(false)
    }
  }

  const handleRetryGranules = async () => {
    if (!jobId || isGenerating) return
    setIsGenerating(true)
    setGenerationMessage('Reintentando Fase 1: gránulos.')
    try {
      await retryGranulesMutation.mutateAsync(jobId)
    } catch (error) {
      setGenerationMessage(error instanceof Error ? error.message : 'Error reintentando gránulos.')
      setIsGenerating(false)
    }
  }

  const handleRetryPipelineLocal = async () => {
    if (!jobId || isGenerating) return
    setIsGenerating(true)
    setGenerationMessage('Reintentando Fase 2: TXT/DOCX sin regenerar gránulos.')
    try {
      await retryPipelineLocalMutation.mutateAsync(jobId)
    } catch (error) {
      setGenerationMessage(error instanceof Error ? error.message : 'Error reintentando TXT/DOCX.')
      setIsGenerating(false)
    }
  }

  const handleRetryMaterials = async () => {
    if (!jobId || isGenerating) return
    setIsGenerating(true)
    setGenerationMessage('Reintentando Fase 3: recursos/materiales.')
    try {
      await retryMaterialsMutation.mutateAsync(jobId)
    } catch (error) {
      setGenerationMessage(error instanceof Error ? error.message : 'Error reintentando recursos.')
      setIsGenerating(false)
    }
  }

  const handleGenerateFullLocalPackage = async () => {
    if (!selectedFile || !selectedPrompt || isGenerating || isFullPipelineRunning || detectedGranules.length === 0) return
    setIsFullPipelineRunning(true)
    setIsGenerating(true)
    setGenerationMessage(`Flujo completo: generando gránulos, luego TXT/DOCX y materiales de ${categoryLabel}.`)
    try {
      const created = await createJobMutation.mutateAsync({ syllabus: selectedFile, nivel: selectedPrompt })
      setHydratedJobId(created.jobId)
      saveLocalSession({ jobId: created.jobId, prompt: selectedPrompt, subjectName, programName, detectedGranules, previewMessage, syllabusFileName: selectedFile?.name })
      await new Promise<void>((resolve, reject) => {
        const check = setInterval(async () => {
          try {
            const resp = await apiFetch(`/api/jobs/${created.jobId}`)
            if (!resp.ok) { clearInterval(check); reject(new Error('Job perdido.')); return }
            const payload = (await resp.json()) as JobStatusResponse
            if (payload.status === 'completed' || payload.status === 'failed' || payload.status === 'cancelled') {
              clearInterval(check)
              if (payload.status === 'failed') reject(new Error('Error en fase 1.'))
              else if (payload.status === 'cancelled') reject(new Error('Cancelado.'))
              else resolve()
            }
          } catch (e) { clearInterval(check); reject(e) }
        }, 3000)
      })
      await runPipelineLocalMutation.mutateAsync(created.jobId)
      await new Promise<void>((resolve, reject) => {
        const check = setInterval(async () => {
          try {
            const resp = await apiFetch(`/api/jobs/${created.jobId}`)
            if (!resp.ok) { clearInterval(check); reject(new Error('Job perdido.')); return }
            const payload = (await resp.json()) as JobStatusResponse
            if (payload.status === 'completed' || payload.status === 'failed' || payload.status === 'cancelled') {
              clearInterval(check)
              if (payload.status === 'failed') reject(new Error('Error en fase 2.'))
              else resolve()
            }
          } catch (e) { clearInterval(check); reject(e) }
        }, 3000)
      })
      await runMaterialsMutation.mutateAsync(created.jobId)
      setGenerationMessage('Paquete completo listo. Puedes descargar el ZIP final institucional.')
    } catch (error) {
      setGenerationMessage(error instanceof Error ? error.message : 'Error ejecutando el flujo completo.')
    } finally {
      setIsGenerating(false)
      setIsFullPipelineRunning(false)
    }
  }

  const handleRetryCurrentPhase = () => {
    if (phaseStatus?.specializationMaterials.status === 'failed') { void handleRetryMaterials(); return }
    if (phaseStatus?.pipelineLocal.status === 'failed') { void handleRetryPipelineLocal(); return }
    if (phaseStatus?.granules.status === 'failed') { void handleRetryGranules(); return }
    if (jobId) { void handleRetryGranules() } else { void handleGenerate() }
  }

  const handleCancelJob = async () => {
    if (!jobId || isCancelling) return
    setIsCancelling(true)
    setIsGenerating(false)
    setIsFullPipelineRunning(false)
    try {
      await cancelJobMutation.mutateAsync(jobId)
    } catch (error) {
      setGenerationMessage(error instanceof Error ? error.message : 'No se pudo contactar el backend para cancelar.')
    } finally {
      setIsCancelling(false)
    }
  }

  const handleReset = () => {
    resetForNewSyllabus()
  }

  const handlePromptChange = (prompt: PromptType | '') => {
    setSelectedPrompt(prompt)
    handleReset()
  }

  useEffect(() => {
    let cancelled = false
    apiFetch('/api/categories')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('No categories')))
      .then((payload: CategoryConfig[]) => { if (!cancelled && Array.isArray(payload) && payload.length > 0) setCategories(payload) })
      .catch(() => { if (!cancelled) setCategories(CATEGORY_CONFIGS) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const session = loadLocalSession()
    if (!session?.jobId) return
    setHydratedJobId(session.jobId)
    if (session.prompt) setSelectedPrompt(session.prompt as PromptType)
    if (session.subjectName) setSubjectName(session.subjectName)
    if (session.programName) setProgramName(session.programName)
    if (session.detectedGranules) setDetectedGranules(session.detectedGranules)
    if (session.previewMessage) setPreviewMessage(session.previewMessage)
    if (session.syllabusFileName) setSyllabusFileName(session.syllabusFileName)
  }, [])

  useEffect(() => {
    if (jobData?.syllabusOriginalName && !syllabusFileName) {
      setSyllabusFileName(jobData.syllabusOriginalName)
    }
  }, [jobData?.syllabusOriginalName])

  useEffect(() => {
    if (!jobData?.phaseStatus) return
    const anyPhaseRunning =
      jobData.phaseStatus.granules?.status === 'running' ||
      jobData.phaseStatus.pipelineLocal?.status === 'running' ||
      jobData.phaseStatus.specializationMaterials?.status === 'running' ||
      jobData.phaseStatus.uploadDrive?.status === 'running'
    setIsGenerating(anyPhaseRunning)
    const fullPipelineRunning = anyPhaseRunning && jobData.status === 'running'
    setIsFullPipelineRunning(fullPipelineRunning)
  }, [jobData?.phaseStatus, jobData?.status])

  const consoleStatus = status === 'error'
    ? 'Error'
    : status === 'cancelado' || localUiStatus === 'cancelled' ? 'Cancelado'
    : localUiStatus === 'missing_job' ? 'Proceso no disponible'
    : localUiStatus === 'recoverable_error' ? 'Revisar backend'
    : availableNextAction === 'download_package' ? 'Paquete listo'
    : isGenerating ? 'Procesando'
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
    if (localUiStatus === 'cancelled' || status === 'cancelado') return { general: 'cancelled', phases, primaryAction: 'none', primaryLabel: '', message: generationMessage || 'Proceso cancelado. Puedes iniciar uno nuevo o continuar desde una fase válida.' }
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
    if (pipelineState.primaryAction === 'cancel') void handleCancelJob()
    if (pipelineState.primaryAction === 'generate_granules') void handleGenerate()
    if (pipelineState.primaryAction === 'generate_pipeline_local') void handleGeneratePipelineLocal()
    if (pipelineState.primaryAction === 'generate_materials') void handleGenerateMaterials()
    if (pipelineState.primaryAction === 'retry_current_phase') void handleRetryCurrentPhase()
  }

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
                syllabusFileName={syllabusFileName}
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
                  <button type="button" className="secondary-button" onClick={() => void handleRetryGranules()}>Regenerar gránulos</button>
                )}
                {jobId && phaseStatus?.granules.status === 'completed' && (phaseStatus?.pipelineLocal.status === 'failed' || phaseStatus?.pipelineLocal.status === 'completed') && !isGenerating && (
                  <button type="button" className="secondary-button" onClick={() => void handleRetryPipelineLocal()}>Regenerar TXT/DOCX</button>
                )}
                {jobId && phaseStatus?.pipelineLocal.status === 'completed' && (phaseStatus?.specializationMaterials.status === 'failed' || phaseStatus?.specializationMaterials.status === 'completed') && !isGenerating && (
                  <button type="button" className="secondary-button" onClick={() => void handleRetryMaterials()}>Regenerar recursos</button>
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
                <button type="button" className="secondary-button" onClick={() => void handleGenerateFullLocalPackage()}>
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
                <div><span>Archivo</span><strong>{selectedFile?.name ?? syllabusFileName ?? (jobId ? 'Syllabus cargado' : 'Pendiente')}</strong></div>
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

              {metrics && metrics.total && (
                <details className="metrics-panel" open={metricsOpen} onToggle={(e) => setMetricsOpen((e.target as HTMLDetailsElement).open)}>
                  <summary className="metrics-summary">
                    <span className="metrics-summary-icon">⏱</span>
                    Métricas de tiempo
                    <span className="metrics-badge">
                      {metrics.mode === 'parallel' ? `Paralelo (${metrics.maxWorkers}w)` : 'Secuencial'}
                    </span>
                    <span className="metrics-total">{metrics.total.granulesHuman ?? '—'}</span>
                  </summary>
                  <div className="metrics-content">
                    <div className="metrics-row">
                      <span className="metrics-label">Parse sílabo:</span>
                      <span className="metrics-value">{metrics.total.parseHuman ?? '—'}</span>
                    </div>
                    <div className="metrics-row">
                      <span className="metrics-label">Total gránulos:</span>
                      <span className="metrics-value">{metrics.total.granulesHuman ?? '—'}</span>
                    </div>
                    {metrics.granules && Object.keys(metrics.granules).length > 0 && (
                      <div className="metrics-granules-list">
                        {Object.entries(metrics.granules)
                          .sort(([a], [b]) => a.localeCompare(b))
                          .map(([code, g]) => (
                            <div key={code} className={`metrics-granule-item ${g.success === false ? 'metrics-granule-failed' : ''}`}>
                              <span className="metrics-granule-code">{code}</span>
                              <span className="metrics-granule-duration">{g.durationHuman ?? '—'}</span>
                              {g.success === false && <span className="metrics-granule-status">✗</span>}
                            </div>
                          ))}
                      </div>
                    )}
                    {metrics.granules && metrics.total.granulesSeconds && (
                      <div className="metrics-row metrics-avg">
                        <span className="metrics-label">Promedio por gránulo:</span>
                        <span className="metrics-value">
                          {(() => {
                            const times = Object.values(metrics.granules!).filter(g => g.success !== false).map(g => g.durationSeconds ?? 0)
                            const avg = times.length > 0 ? times.reduce((a, b) => a + b, 0) / times.length : 0
                            const mins = Math.floor(avg / 60)
                            const secs = Math.round(avg % 60)
                            return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`
                          })()}
                        </span>
                      </div>
                    )}
                  </div>
                </details>
              )}
            </section>
          </aside>
        </section>
      </div>
    </div>
  )
}

export default GranulesView

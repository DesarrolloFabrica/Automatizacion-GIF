import { useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import { SCRIPTS_LOCAL_PIPELINE_STEPS, validateLocalGranulesSelection } from '../data/mockScripts'
import { API_BASE_URL } from '../lib/api'
import {
  loadScriptsModularSession,
  saveScriptsModularSession,
  type ScriptsModularModuleState,
} from '../lib/sessionStorage'
import type { LocalGeneratedFile, ScriptsLocalJobStatusResponse, ScriptsLocalProgressStep } from '../data/mockScripts'
import type { GenerationStatus, JobStatusResponse, PromptType } from '../types/granules'

interface ScriptsViewProps {
  onBack: () => void
  initialMode?: ScriptMode
  onModeChange?: (mode: ScriptMode) => void
}

type ScriptMode = 'granules' | 'txtdocx' | 'materials'

const API_BASE = API_BASE_URL

const promptOptions: Array<{ value: PromptType; label: string }> = [
  { value: 'curso_rapido', label: 'Curso rápido' },
  { value: 'pregrado', label: 'Pregrado' },
  { value: 'diplomado', label: 'Diplomado' },
  { value: 'especializacion', label: 'Especialización' },
  { value: 'curso_externos_profesional', label: 'Curso externos profesional' },
  { value: 'maestria', label: 'Maestría · pendiente de prompt de materiales' },
]

interface ScriptModuleInfo {
  id: ScriptMode
  number: string
  title: string
  subtitle: string
  description: string
  inputLabel: string
  inputHint: string
  outputLabel: string
  ctaLabel: string
  ctaGenerating: string
  requiresFile: boolean
  detectedLabel: string
}

const MODULES: ScriptModuleInfo[] = [
  {
    id: 'granules',
    number: '01',
    title: 'Crear solo gránulos',
    subtitle: 'Syllabus → G1-G5',
    description: 'Sube un syllabus y genera únicamente los gránulos G1-G5 sin construir el paquete completo.',
    inputLabel: 'Subir syllabus .docx',
    inputHint: 'Selecciona el syllabus fuente.',
    outputLabel: 'Gránulos generados',
    ctaLabel: 'Generar gránulos',
    ctaGenerating: 'Generando gránulos...',
    requiresFile: true,
    detectedLabel: 'gránulos detectados',
  },
  {
    id: 'txtdocx',
    number: '02',
    title: 'Crear TXT/DOCX',
    subtitle: 'G1-G5 locales → actividades Moodle',
    description: 'Sube gránulos ya generados y produce PDA, QUIZ, ACA, PRESENTACIÓN y FORO listos para Moodle.',
    inputLabel: 'Subir G1-G5 en .docx o .pdf',
    inputHint: 'Arrastra aquí tus gránulos o haz clic para seleccionarlos.',
    outputLabel: 'Archivos TXT/DOCX generados',
    ctaLabel: 'Generar TXT/DOCX',
    ctaGenerating: 'Generando TXT/DOCX...',
    requiresFile: true,
    detectedLabel: 'archivos académicos encontrados',
  },
  {
    id: 'materials',
    number: '03',
    title: 'Materiales por gránulo',
    subtitle: 'Gránulo → 6 materiales editoriales',
    description: 'Sube un gránulo maestro y genera directamente los materiales editoriales de ese gránulo.',
    inputLabel: 'Subir gránulo .docx',
    inputHint: 'Selecciona un gránulo fuente, por ejemplo G1_TEMA.docx.',
    outputLabel: 'Materiales generados',
    ctaLabel: 'Generar materiales por gránulo',
    ctaGenerating: 'Generando materiales...',
    requiresFile: true,
    detectedLabel: 'materiales encontrados',
  },
]

const MODULE_MAP: Record<ScriptMode, ScriptModuleInfo> = {
  granules: MODULES[0],
  txtdocx: MODULES[1],
  materials: MODULES[2],
}

interface ModularJobSummary {
  jobId: string
  category: string
  syllabusName: string | null
  granulesCount: number
  pipelineFilesCount: number
  materialsCount: number
  granulesStatus: string
  pipelineLocalStatus: string
  materialsStatus: string
  createdAt: string | null
  updatedAt: string | null
}

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

function statusPillClass(status: string, isGenerating: boolean): string {
  if (status === 'error') return 'script-status-pill--error'
  if (status === 'finalizado') return 'script-status-pill--success'
  if (isGenerating) return 'script-status-pill--active'
  return 'script-status-pill--idle'
}

function statusPillLabel(status: string, isGenerating: boolean): string {
  if (isGenerating) return 'Generando'
  if (status === 'finalizado') return 'Outputs listos'
  if (status === 'error') return 'Error recuperable'
  return 'Listo para iniciar'
}

function ScriptsView({ onBack, initialMode, onModeChange }: ScriptsViewProps) {
  const [mode, setMode] = useState<ScriptMode>(initialMode ?? 'granules')
  const [recentJobs, setRecentJobs] = useState<ModularJobSummary[]>([])
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/scripts/modular/recent`)
      .then((r) => r.ok ? r.json() : Promise.resolve({ jobs: [] }))
      .then((data) => {
        const jobs = (data as { jobs: ModularJobSummary[] }).jobs ?? []
        setRecentJobs(jobs)
        if (jobs.length > 0 && !selectedJobId) {
          setSelectedJobId(jobs[0].jobId)
        }
      })
      .catch(() => {})
  }, [])

  const rehydrateFromSession = (mod: ScriptMode): Partial<ScriptsModularModuleState> => {
    const session = loadScriptsModularSession()
    if (!session?.modules?.[mod]) return {}
    return session.modules[mod]
  }

  const applySessionState = (mod: ScriptMode, state: Partial<ScriptsModularModuleState>) => {
    if (mod === 'granules') {
      if (state.jobId) setGranulesJobId(state.jobId)
      if (state.status) setGranulesStatus(state.status as GenerationStatus)
      if (state.message) setGranulesMessage(state.message)
      if (state.files) setGranulesFiles(state.files)
      if (state.nivel) setSelectedPrompt(state.nivel as PromptType)
      if (state.selectedFileName) setSyllabusFileName(state.selectedFileName)
    } else if (mod === 'txtdocx') {
      if (state.jobId) setLocalJobId(state.jobId)
      if (state.status) setLocalStatus(state.status as ScriptsLocalProgressStep)
      if (state.message) setLocalMessage(state.message)
      if (state.asignatura) setLocalAsignatura(state.asignatura)
      if (state.programa) setLocalPrograma(state.programa)
    } else if (mod === 'materials') {
      if (state.jobId) setMaterialsJobId(state.jobId)
      if (state.status) setMaterialsStatus(state.status as GenerationStatus)
      if (state.message) setMaterialsMessage(state.message)
      if (state.files) setMaterialsFiles(state.files)
      if (state.nivel) setMaterialsPrompt(state.nivel as PromptType)
      if (state.selectedFileName) setMaterialsFileName(state.selectedFileName)
    }
  }

  const handleModeChange = (newMode: ScriptMode) => {
    setMode(newMode)
    onModeChange?.(newMode)
    saveScriptsModularSession(mode, {}, newMode)
    const restored = rehydrateFromSession(newMode)
    if (restored && Object.keys(restored).length > 0) {
      applySessionState(newMode, restored)
    }
  }

  const [syllabusFile, setSyllabusFile] = useState<File | null>(null)
  const [syllabusFileName, setSyllabusFileName] = useState<string | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptType>('especializacion')
  const [granulesJobId, setGranulesJobId] = useState<string | null>(null)
  const [granulesStatus, setGranulesStatus] = useState<GenerationStatus>('pendiente')
  const [granulesMessage, setGranulesMessage] = useState('Sube un syllabus y genera únicamente los gránulos G1-G5.')
  const [granulesLogs, setGranulesLogs] = useState<string[]>([])
  const [granulesFiles, setGranulesFiles] = useState<string[]>([])
  const [isGeneratingGranules, setIsGeneratingGranules] = useState(false)
  const granulesPollRef = useRef<number | null>(null)

  const [materialsFile, setMaterialsFile] = useState<File | null>(null)
  const [materialsFileName, setMaterialsFileName] = useState<string | null>(null)
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
  const [localMessage, setLocalMessage] = useState('Sube G1-G5 en .docx o .pdf para generar TXT/DOCX académicos.')
  const [localLogs, setLocalLogs] = useState<string[]>([])
  const [localGeneratedFiles, setLocalGeneratedFiles] = useState<LocalGeneratedFile[]>([])
  const [localJobId, setLocalJobId] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const localPollRef = useRef<number | null>(null)

  const localValidation = useMemo(() => validateLocalGranulesSelection(localFiles), [localFiles])
  const localFormValid = localValidation.ok && localAsignatura.trim().length > 0 && localPrograma.trim().length > 0
  const localTxtFiles = localGeneratedFiles.filter((f) => f.kind === 'txt')
  const localDocxFiles = localGeneratedFiles.filter((f) => f.kind === 'docx')
  const materialsFormValid = Boolean((materialsFile || materialsFileName) && materialsPrompt)

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

  useEffect(() => {
    const restored = rehydrateFromSession(mode)
    if (restored && Object.keys(restored).length > 0) {
      applySessionState(mode, restored)
    }
  }, [])

  useEffect(() => {
    if (!granulesJobId) return
    const isRunning = granulesStatus !== 'finalizado' && granulesStatus !== 'error' && isGeneratingGranules
    if (!isRunning) return
    granulesPollRef.current = window.setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${granulesJobId}`)
        if (!res.ok) return
        const payload = (await res.json()) as JobStatusResponse
        setGranulesStatus(payload.progressStep)
        setGranulesLogs(payload.logs ?? [])
        setGranulesFiles((payload.files ?? []).filter((file) => /^G\d+_/.test(file)))
        if (payload.status === 'completed') {
          setGranulesStatus('finalizado')
          setIsGeneratingGranules(false)
          setGranulesMessage('Gránulos completados. Puedes descargar el ZIP parcial o los archivos generados.')
          saveScriptsModularSession('granules', {
            jobId: granulesJobId,
            status: 'finalizado',
            files: (payload.files ?? []).filter((file) => /^G\d+_/.test(file)),
            message: 'Gránulos completados.',
            completedAt: new Date().toISOString(),
          })
          clearGranulesPolling()
        }
        if (payload.status === 'failed') {
          setGranulesStatus('error')
          setIsGeneratingGranules(false)
          setGranulesMessage('Error generando gránulos. Revisa el registro de actividad.')
          saveScriptsModularSession('granules', {
            jobId: granulesJobId,
            status: 'error',
            error: 'Error generando gránulos',
          })
          clearGranulesPolling()
        }
      } catch {
        setGranulesStatus('error')
        setIsGeneratingGranules(false)
        setGranulesMessage('No fue posible consultar el estado del job.')
        clearGranulesPolling()
      }
    }, 3000)
    return () => clearGranulesPolling()
  }, [granulesJobId, isGeneratingGranules])

  useEffect(() => {
    if (!localJobId) return
    const isRunning = localStatus !== 'finalizado' && localStatus !== 'error' && localIsGenerating
    if (!isRunning) return
    localPollRef.current = window.setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/scripts/local/jobs/${localJobId}`)
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
          saveScriptsModularSession('txtdocx', {
            jobId: localJobId,
            status: 'finalizado',
            files: (payload.files ?? []).map((f) => f.name),
            message: 'TXT/DOCX completados.',
            completedAt: new Date().toISOString(),
          })
          clearLocalPolling()
        }
        if (payload.status === 'failed') {
          setLocalStatus('error')
          setLocalIsGenerating(false)
          setLocalMessage('El proceso local falló. Revisa el registro de actividad.')
          saveScriptsModularSession('txtdocx', {
            jobId: localJobId,
            status: 'error',
            error: 'El proceso local falló',
          })
          clearLocalPolling()
        }
      } catch {
        setLocalStatus('error')
        setLocalIsGenerating(false)
        setLocalMessage('No fue posible consultar el estado del job local.')
        clearLocalPolling()
      }
    }, 4000)
    return () => clearLocalPolling()
  }, [localJobId, localIsGenerating])

  useEffect(() => {
    if (!materialsJobId) return
    const isRunning = materialsStatus !== 'finalizado' && materialsStatus !== 'error' && isGeneratingMaterials
    if (!isRunning) return
    materialsPollRef.current = window.setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${materialsJobId}`)
        if (!res.ok) return
        const payload = (await res.json()) as JobStatusResponse
        setMaterialsStatus(payload.progressStep)
        setMaterialsLogs(payload.logs ?? [])
        setMaterialsFiles((payload.files ?? []).filter((file) => file.includes('materiales_') || file.includes('materials')))
        if (payload.status === 'completed') {
          setMaterialsStatus('finalizado')
          setIsGeneratingMaterials(false)
          setMaterialsMessage('Materiales generados. Puedes descargar el paquete de materiales.')
          saveScriptsModularSession('materials', {
            jobId: materialsJobId,
            status: 'finalizado',
            files: (payload.files ?? []).filter((file) => file.includes('materiales_') || file.includes('materials')),
            message: 'Materiales generados.',
            completedAt: new Date().toISOString(),
          })
          clearMaterialsPolling()
        }
        if (payload.status === 'failed') {
          setMaterialsStatus('error')
          setIsGeneratingMaterials(false)
          setMaterialsMessage('Error generando materiales. Revisa el registro de actividad.')
          saveScriptsModularSession('materials', {
            jobId: materialsJobId,
            status: 'error',
            error: 'Error generando materiales',
          })
          clearMaterialsPolling()
        }
      } catch {
        setMaterialsStatus('error')
        setIsGeneratingMaterials(false)
        setMaterialsMessage('No fue posible consultar el estado del job de materiales.')
        clearMaterialsPolling()
      }
    }, 3000)
    return () => clearMaterialsPolling()
  }, [materialsJobId, isGeneratingMaterials])

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
      saveScriptsModularSession('granules', {
        jobId: created.jobId,
        status: 'leyendo syllabus',
        selectedFileName: syllabusFile.name,
        nivel: selectedPrompt,
      })

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
            saveScriptsModularSession('granules', {
              jobId: created.jobId,
              status: 'finalizado',
              files: (payload.files ?? []).filter((file) => /^G\d+_/.test(file)),
              message: 'Gránulos completados.',
              completedAt: new Date().toISOString(),
            })
            clearGranulesPolling()
          }

          if (payload.status === 'failed') {
            setGranulesStatus('error')
            setIsGeneratingGranules(false)
            setGranulesMessage('Error generando gránulos. Revisa el registro de actividad.')
            saveScriptsModularSession('granules', {
              jobId: created.jobId,
              status: 'error',
              error: 'Error generando gránulos',
            })
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
      saveScriptsModularSession('materials', {
        jobId: created.jobId,
        status: 'generando materiales',
        selectedFileName: materialsFile.name,
        nivel: materialsPrompt,
      })

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
            saveScriptsModularSession('materials', {
              jobId: created.jobId,
              status: 'finalizado',
              files: (payload.files ?? []).filter((file) => file.includes('materiales_') || file.includes('materials')),
              message: 'Materiales generados.',
              completedAt: new Date().toISOString(),
            })
            clearMaterialsPolling()
          }

          if (payload.status === 'failed') {
            setMaterialsStatus('error')
            setIsGeneratingMaterials(false)
            setMaterialsMessage('Error generando materiales. Revisa el registro de actividad.')
            saveScriptsModularSession('materials', {
              jobId: created.jobId,
              status: 'error',
              error: 'Error generando materiales',
            })
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
      saveScriptsModularSession('txtdocx', {
        jobId: created.jobId,
        status: 'cargando granulos',
        asignatura: localAsignatura.trim(),
        programa: localPrograma.trim(),
      })

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
            saveScriptsModularSession('txtdocx', {
              jobId: created.jobId,
              status: 'finalizado',
              files: (payload.files ?? []).map((f) => f.name),
              message: 'TXT/DOCX completados.',
              completedAt: new Date().toISOString(),
            })
            clearLocalPolling()
          }

          if (payload.status === 'failed') {
            setLocalStatus('error')
            setLocalIsGenerating(false)
            setLocalMessage('El proceso local falló. Revisa el registro de actividad.')
            saveScriptsModularSession('txtdocx', {
              jobId: created.jobId,
              status: 'error',
              error: 'El proceso local falló',
            })
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

  const info = MODULE_MAP[mode]

  const latestGranulesJob = recentJobs.find((j) => j.granulesCount > 0)
  const latestPipelineJob = recentJobs.find((j) => j.pipelineFilesCount > 0)
  const latestMaterialsJob = recentJobs.find((j) => j.materialsCount > 0)

  const renderGranulesModule = () => {
    const isRunning = isGeneratingGranules
    const isDone = granulesStatus === 'finalizado'
    const hasFiles = granulesFiles.length > 0
    const hasJob = granulesJobId !== null
    const hasDetectedOutputs = !hasJob && latestGranulesJob && latestGranulesJob.granulesCount > 0

    return (
      <section className="scripts-workspace-card">
        <div className="scripts-workspace-header">
          <div>
            <span className="scripts-step-badge">Módulo {info.number}</span>
            <h2>{info.title}</h2>
            <p className="module-pipeline-hint">
              {hasDetectedOutputs
                ? `${latestGranulesJob.granulesCount} gránulos detectados del job ${latestGranulesJob.jobId.slice(0, 6)}. Puedes generar nuevos o usar los existentes.`
                : 'Usa /api/jobs para generar la Fase 1 y descargar únicamente los gránulos.'}
            </p>
          </div>
          <span className={`script-status-pill ${statusPillClass(granulesStatus, isRunning)}`}>
            {statusPillLabel(granulesStatus, isRunning)}
          </span>
        </div>

        <div className="scripts-module-info">
          <div className="module-info-item">
            <span className="module-info-label">Entrada</span>
            <span className="module-info-value">{syllabusFileName ?? 'syllabus .docx'}</span>
          </div>
          <div className="module-info-item">
            <span className="module-info-label">Salida</span>
            <span className="module-info-value">G1-G5 (.docx)</span>
          </div>
          {hasDetectedOutputs && (
            <div className="module-info-item">
              <span className="module-info-label">Outputs existentes</span>
              <span className="module-info-value">{latestGranulesJob.granulesCount} {info.detectedLabel}</span>
            </div>
          )}
          {hasJob && isDone && (
            <div className="module-info-item">
              <span className="module-info-label">Última ejecución</span>
              <span className="module-info-value">{granulesFiles.length} archivos generados</span>
            </div>
          )}
        </div>

        <div className="scripts-form-grid">
          <label className="label-block">
            Nivel académico
            <select className="select-input" value={selectedPrompt} onChange={(event) => setSelectedPrompt(event.target.value as PromptType)} disabled={isRunning}>
              {promptOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="scripts-local-dropzone scripts-file-selector">
            <span className="file-input-label">{info.inputLabel}</span>
            <input
              type="file"
              accept=".docx"
              className="file-input"
              disabled={isRunning}
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null
                setSyllabusFile(file)
                setSyllabusFileName(file?.name ?? null)
              }}
            />
            <p className="muted">{syllabusFileName ?? info.inputHint}</p>
          </label>
        </div>

        <section className="scripts-action-panel scripts-generate-section">
          <p className="muted">{granulesMessage}</p>
          <button type="button" className="primary-button primary-button--hero" onClick={handleGenerateGranulesOnly} disabled={!syllabusFile || isRunning}>
            {isRunning ? info.ctaGenerating : info.ctaLabel}
          </button>
        </section>

        {(isRunning || granulesStatus !== 'pendiente') && (
          <article className="script-progress-card">
            <h3>Estado de gránulos</h3>
            <p>{statusLabel(granulesStatus)}</p>
            {granulesLogs.length > 0 && <div className="logs-box"><pre>{granulesLogs.slice(-28).join('\n')}</pre></div>}
          </article>
        )}

        {hasJob && hasFiles && (
          <article className="script-results-card">
            <h3>{info.outputLabel} ({granulesFiles.length})</h3>
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

        {hasDetectedOutputs && !hasJob && (
          <article className="script-results-card">
            <h3>{info.outputLabel} ({latestGranulesJob.granulesCount})</h3>
            <p className="card-description">Outputs del job <code>{latestGranulesJob.jobId.slice(0, 8)}</code></p>
            <a className="primary-button link-button" href={`${API_BASE}/api/jobs/${latestGranulesJob.jobId}/download/granules`} target="_blank" rel="noreferrer">Descargar gránulos (.zip)</a>
          </article>
        )}
      </section>
    )
  }

  const renderTxtDocxModule = () => {
    const isRunning = localIsGenerating
    const isDone = localStatus === 'finalizado'
    const hasFiles = localGeneratedFiles.length > 0
    const hasJob = localJobId !== null
    const hasDetectedOutputs = !hasJob && latestPipelineJob && latestPipelineJob.pipelineFilesCount > 0
    const hasGranulesFromJob = latestGranulesJob && latestGranulesJob.granulesCount >= 4

    return (
      <section className="scripts-workspace-card">
        <div className="scripts-workspace-header">
          <div>
            <span className="scripts-step-badge">Módulo {info.number}</span>
            <h2>{info.title}</h2>
            <p className="module-pipeline-hint">
              {hasDetectedOutputs
                ? `${latestPipelineJob.pipelineFilesCount} archivos académicos encontrados del job ${latestPipelineJob.jobId.slice(0, 6)}.`
                : hasGranulesFromJob
                  ? `${latestGranulesJob!.granulesCount} gránulos disponibles del job ${latestGranulesJob.jobId.slice(0, 6)}. Sube 4-5 para generar TXT/DOCX.`
                  : 'Sube G1-G5 ya generados y descarga PDA, QUIZ y documentos académicos.'}
            </p>
          </div>
          <span className={`script-status-pill ${statusPillClass(localStatus, isRunning)}`}>
            {statusPillLabel(localStatus, isRunning)}
          </span>
        </div>

        <div className="scripts-module-info">
          <div className="module-info-item">
            <span className="module-info-label">Entrada</span>
            <span className="module-info-value">4-5 gránulos (.docx / .pdf)</span>
          </div>
          <div className="module-info-item">
            <span className="module-info-label">Salida</span>
            <span className="module-info-value">PDA, QUIZ, ACA, PRESENTACIÓN, FORO</span>
          </div>
          {hasDetectedOutputs && (
            <div className="module-info-item">
              <span className="module-info-label">Outputs existentes</span>
              <span className="module-info-value">{latestPipelineJob.pipelineFilesCount} {info.detectedLabel}</span>
            </div>
          )}
          {hasJob && isDone && (
            <div className="module-info-item">
              <span className="module-info-label">Última ejecución</span>
              <span className="module-info-value">{localGeneratedFiles.length} archivos generados</span>
            </div>
          )}
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
          <label className="file-input-label" htmlFor="local-granules-input">{info.inputLabel}</label>
          <input id="local-granules-input" type="file" multiple accept=".docx,.pdf,application/pdf" onChange={(event) => addFiles(event.target.files ?? [])} className="file-input" />
          <p className="muted">{localFiles.length > 0 ? `${localFiles.length} archivo(s) seleccionado(s)` : info.inputHint}</p>
          {localValidation.reason && <p className={`script-validation script-validation--${localValidation.level ?? 'error'}`}>{localValidation.reason}</p>}
          {localFiles.length > 0 && (
            <ul className="results-list compact-results-list">
              {localFiles.map((file, index) => (
                <li key={`${file.name}-${file.size}`}>
                  <span>{file.name}</span>
                  <button type="button" className="secondary-button" onClick={() => removeLocalFile(index)} disabled={isRunning}>Quitar</button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="scripts-form-grid">
          <label className="label-block">
            Asignatura
            <input type="text" className="select-input" value={localAsignatura} onChange={(event) => setLocalAsignatura(event.target.value)} placeholder="Ej: Inteligencia artificial y analítica avanzada" disabled={isRunning} />
          </label>
          <label className="label-block">
            Programa
            <input type="text" className="select-input" value={localPrograma} onChange={(event) => setLocalPrograma(event.target.value)} placeholder="Ej: Especialización en videojuegos" disabled={isRunning} />
          </label>
        </div>

        <section className="scripts-action-panel scripts-generate-section">
          <p className="muted">{localMessage}</p>
          <button type="button" className="primary-button primary-button--hero" onClick={handleGenerateLocal} disabled={!localFormValid || isRunning}>
            {isRunning ? info.ctaGenerating : info.ctaLabel}
          </button>
        </section>

        {(isRunning || localStatus !== 'pendiente') && (
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

        {isDone && hasFiles && (
          <article className="script-results-card">
            <h3>{info.outputLabel}</h3>
            {localTxtFiles.length > 0 && <p className="card-description">TXT: {localTxtFiles.map((file) => file.name).join(', ')}</p>}
            {localDocxFiles.length > 0 && <p className="card-description">DOCX: {localDocxFiles.map((file) => file.name).join(', ')}</p>}
            <a className="primary-button link-button" href={`${API_BASE}/api/scripts/local/jobs/${localJobId}/download-all`} target="_blank" rel="noreferrer">Descargar TXT/DOCX (.zip)</a>
          </article>
        )}

        {hasDetectedOutputs && !hasJob && (
          <article className="script-results-card">
            <h3>{info.outputLabel} ({latestPipelineJob.pipelineFilesCount})</h3>
            <p className="card-description">Outputs del job <code>{latestPipelineJob.jobId.slice(0, 8)}</code></p>
            <a className="primary-button link-button" href={`${API_BASE}/api/scripts/local/jobs/${latestPipelineJob.jobId}/download-all`} target="_blank" rel="noreferrer">Descargar TXT/DOCX (.zip)</a>
          </article>
        )}
      </section>
    )
  }

  const renderMaterialsModule = () => {
    const isRunning = isGeneratingMaterials
    const isDone = materialsStatus === 'finalizado'
    const hasFiles = materialsFiles.length > 0
    const hasJob = materialsJobId !== null
    const hasDetectedOutputs = !hasJob && latestMaterialsJob && latestMaterialsJob.materialsCount > 0

    return (
      <section className="scripts-workspace-card">
        <div className="scripts-workspace-header">
          <div>
            <span className="scripts-step-badge">Módulo {info.number}</span>
            <h2>{info.title}</h2>
            <p className="module-pipeline-hint">
              {hasDetectedOutputs
                ? `${latestMaterialsJob.materialsCount} materiales encontrados del job ${latestMaterialsJob.jobId.slice(0, 6)}.`
                : 'Sube un gránulo maestro .docx, selecciona el nivel y genera directamente los materiales editoriales de ese gránulo.'}
            </p>
          </div>
          <span className={`script-status-pill ${statusPillClass(materialsStatus, isRunning)}`}>
            {statusPillLabel(materialsStatus, isRunning)}
          </span>
        </div>

        <div className="scripts-module-info">
          <div className="module-info-item">
            <span className="module-info-label">Entrada</span>
            <span className="module-info-value">{materialsFileName ?? '1 gránulo (.docx)'}</span>
          </div>
          <div className="module-info-item">
            <span className="module-info-label">Salida</span>
            <span className="module-info-value">6 materiales editoriales (.docx)</span>
          </div>
          {hasDetectedOutputs && (
            <div className="module-info-item">
              <span className="module-info-label">Outputs existentes</span>
              <span className="module-info-value">{latestMaterialsJob.materialsCount} {info.detectedLabel}</span>
            </div>
          )}
          {hasJob && isDone && (
            <div className="module-info-item">
              <span className="module-info-label">Última ejecución</span>
              <span className="module-info-value">{materialsFiles.length} archivos generados</span>
            </div>
          )}
        </div>

        <div className="scripts-form-grid">
          <label className="label-block">
            Nivel académico
            <select className="select-input" value={materialsPrompt} onChange={(event) => setMaterialsPrompt(event.target.value as PromptType)} disabled={isRunning}>
              {promptOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="scripts-local-dropzone scripts-file-selector">
            <span className="file-input-label">{info.inputLabel}</span>
            <input
              type="file"
              accept=".docx"
              className="file-input"
              disabled={isRunning}
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null
                setMaterialsFile(file)
                setMaterialsFileName(file?.name ?? null)
                setMaterialsFiles([])
                setMaterialsJobId(null)
                setMaterialsStatus('pendiente')
                setMaterialsMessage(file ? 'Gránulo cargado. Elige el nivel y genera sus materiales.' : info.inputHint)
              }}
            />
            <p className="muted">{materialsFileName ?? info.inputHint}</p>
          </label>
        </div>

        <section className="scripts-action-panel scripts-generate-section">
          <p className="muted">{materialsMessage}</p>
          <button type="button" className="primary-button primary-button--hero" onClick={handleGenerateMaterialsOnly} disabled={!materialsFormValid || isRunning}>
            {isRunning ? info.ctaGenerating : info.ctaLabel}
          </button>
        </section>

        {(isRunning || materialsStatus !== 'pendiente') && (
          <article className="script-progress-card">
            <h3>Estado de materiales</h3>
            <p>{statusLabel(materialsStatus)}</p>
            {materialsLogs.length > 0 && <div className="logs-box"><pre>{materialsLogs.slice(-28).join('\n')}</pre></div>}
          </article>
        )}

        {hasJob && hasFiles && (
          <article className="script-results-card">
            <h3>{info.outputLabel} ({materialsFiles.length})</h3>
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

        {hasDetectedOutputs && !hasJob && (
          <article className="script-results-card">
            <h3>{info.outputLabel} ({latestMaterialsJob.materialsCount})</h3>
            <p className="card-description">Outputs del job <code>{latestMaterialsJob.jobId.slice(0, 8)}</code></p>
            <a className="primary-button link-button" href={`${API_BASE}/api/jobs/${latestMaterialsJob.jobId}/download/materials`} target="_blank" rel="noreferrer">
              Descargar materiales (.zip)
            </a>
          </article>
        )}
      </section>
    )
  }

  return (
    <div className="scripts-view">
      <div className="scripts-view-content">
        <div className="view-header premium-view-header">
          <BackButton onBack={onBack} />
          <div className="view-header-text">
            <span className="view-kicker">Ejecución local modular</span>
            <h1 className="view-title">Laboratorio modular</h1>
            <p className="view-subtitle">Ejecuta fases específicas del pipeline sin construir todo el paquete completo.</p>
          </div>
        </div>

        <section className="scripts-cluster">
          <div className="scripts-cluster-heading">
            <span className="view-kicker">Módulos disponibles</span>
            <h2>Operaciones modulares conectadas</h2>
            <p>Selecciona un módulo para ejecutar una parte específica del flujo.</p>
          </div>
          <div className="scripts-command-center">
            {MODULES.map((mod) => {
              const isActive = mode === mod.id
              let statusText = 'Listo'
              let statusClass = 'module-status--ready'
              if (mod.id === 'granules') {
                if (isGeneratingGranules) { statusText = 'Generando'; statusClass = 'module-status--active' }
                else if (granulesStatus === 'finalizado') { statusText = `${granulesFiles.length} outputs`; statusClass = 'module-status--outputs' }
                else if (granulesStatus === 'error') { statusText = 'Error'; statusClass = 'module-status--error' }
                else if (latestGranulesJob && latestGranulesJob.granulesCount > 0) { statusText = `${latestGranulesJob.granulesCount} ${mod.detectedLabel}`; statusClass = 'module-status--detected' }
              }
              if (mod.id === 'txtdocx') {
                if (localIsGenerating) { statusText = 'Generando'; statusClass = 'module-status--active' }
                else if (localStatus === 'finalizado') { statusText = `${localGeneratedFiles.length} outputs`; statusClass = 'module-status--outputs' }
                else if (localStatus === 'error') { statusText = 'Error'; statusClass = 'module-status--error' }
                else if (latestPipelineJob && latestPipelineJob.pipelineFilesCount > 0) { statusText = `${latestPipelineJob.pipelineFilesCount} ${mod.detectedLabel}`; statusClass = 'module-status--detected' }
              }
              if (mod.id === 'materials') {
                if (isGeneratingMaterials) { statusText = 'Generando'; statusClass = 'module-status--active' }
                else if (materialsStatus === 'finalizado') { statusText = `${materialsFiles.length} outputs`; statusClass = 'module-status--outputs' }
                else if (materialsStatus === 'error') { statusText = 'Error'; statusClass = 'module-status--error' }
                else if (latestMaterialsJob && latestMaterialsJob.materialsCount > 0) { statusText = `${latestMaterialsJob.materialsCount} ${mod.detectedLabel}`; statusClass = 'module-status--detected' }
              }
              return (
                <button key={mod.id} type="button" className={`script-command-card ${isActive ? 'is-active' : ''}`} onClick={() => handleModeChange(mod.id)}>
                  <span className="script-command-icon">{mod.number}</span>
                  <div className="script-command-body">
                    <strong>{mod.title}</strong>
                    <small>{mod.subtitle}</small>
                    <p className="module-card-desc">{mod.description}</p>
                  </div>
                  <span className={`module-status-badge ${statusClass}`}>{statusText}</span>
                </button>
              )
            })}
          </div>
        </section>

        {mode === 'granules' && renderGranulesModule()}
        {mode === 'txtdocx' && renderTxtDocxModule()}
        {mode === 'materials' && renderMaterialsModule()}

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

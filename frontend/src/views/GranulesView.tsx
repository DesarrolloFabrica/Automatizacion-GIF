import { useCallback, useEffect, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import DetectedGranulesPreview from '../components/DetectedGranulesPreview'
import FileDropzone from '../components/FileDropzone'
import JobProgressPanel from '../components/JobProgressPanel'
import PromptSelector from '../components/PromptSelector'
import ResultsPanel from '../components/ResultsPanel'
import type { AvailableNextAction, GenerationStatus, GranuleMaterials, JobPhaseStatus, JobStatusResponse, PromptType, SyllabusPreviewResponse } from '../types/granules'

interface GranulesViewProps {
  onBack: () => void
}

function GranulesView({ onBack }: GranulesViewProps) {
  const apiBaseUrl = 'http://localhost:8000'
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
  const [generationMessage, setGenerationMessage] = useState('La generación puede tardar aproximadamente 20 minutos.')
  const [availableNextAction, setAvailableNextAction] = useState<AvailableNextAction>('generate_granules')
  const [phaseStatus, setPhaseStatus] = useState<JobPhaseStatus | null>(null)
  const [currentPhase, setCurrentPhase] = useState('pending')
  const pollRef = useRef<number | null>(null)
  const pipelineCardRef = useRef<HTMLElement | null>(null)
  const resultsPanelRef = useRef<HTMLElement | null>(null)
  const prevAnalyzingSyllabusRef = useRef(false)
  const prevIsGeneratingRef = useRef(false)
  const canUploadSyllabus = Boolean(selectedPrompt)
  const hasSyllabus = Boolean(selectedFile)
  const isEspecializacion = selectedPrompt === 'especializacion'

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

  const clearPolling = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

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
    setSubjectName('')
    setProgramName('')
    setPreviewMessage('')
    setGenerationMessage('La generación puede tardar aproximadamente 20 minutos.')
    setSelectedFile(null)
    setDetectedGranules([])
    setIsAnalyzingSyllabus(false)
    clearPolling()
  }

  const parseMaterialesFromLogs = (logs: string[]): GranuleMaterials[] => {
    const granuleMap = new Map<string, GranuleMaterials>()

    for (const line of logs) {
      const match = line.match(/Material guardado:\s*(\d+)_(G\d+)_(.+?)_V\d+\.docx/i)
      if (match) {
        const [, nn, granuleCode, tema] = match
        const folderName = `${granuleCode}_${tema}`
        if (!granuleMap.has(granuleCode)) {
          granuleMap.set(granuleCode, {
            granuleCode,
            granuleFolder: folderName,
            files: [],
            totalMaterials: 0,
          })
        }
        const granuleMat = granuleMap.get(granuleCode)!
        granuleMat.files.push({
          granule: granuleCode,
          name: `${nn}_${granuleCode}_${tema}_V01.docx`,
          relativePath: `materiales_especializacion/${folderName}/${nn}_${granuleCode}_${tema}_V01.docx`,
        })
        granuleMat.totalMaterials = granuleMat.files.length
      }
    }

    return Array.from(granuleMap.values()).sort((a, b) => a.granuleCode.localeCompare(b.granuleCode))
  }

  const parseMaterialesFromFiles = (files: string[]): GranuleMaterials[] => {
    const granuleMap = new Map<string, GranuleMaterials>()
    for (const relativePath of files) {
      if (!relativePath.startsWith('materiales_especializacion/')) continue
      const parts = relativePath.split('/')
      const folder = parts[1] ?? ''
      const name = parts[2] ?? ''
      const match = name.match(/^\d+_(G\d+)_/i) ?? folder.match(/^(G\d+)_/i)
      if (!match || !name) continue
      const granuleCode = match[1]
      if (!granuleMap.has(granuleCode)) {
        granuleMap.set(granuleCode, {
          granuleCode,
          granuleFolder: folder,
          files: [],
          totalMaterials: 0,
        })
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

      const response = await fetch(`${apiBaseUrl}/api/syllabus/preview`, {
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

      if (selectedTopics.length === 0) {
        setPreviewMessage('No se encontraron contenidos en la estructura temática. Revisa que el syllabus tenga la sección 5. ESTRUCTURA TEMÁTICA con columna Contenidos.')
      } else {
        setPreviewMessage('')
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Error analizando syllabus.'
      setPreviewMessage(message)
      setDetectedGranules([])
      setSubjectName('')
      setProgramName('')
    } finally {
      setIsAnalyzingSyllabus(false)
    }
  }

  const applyJobStatus = (payload: JobStatusResponse) => {
    setStatus(payload.progressStep)
    setJobLogs(payload.logs ?? [])
    setGeneratedDocuments(payload.files ?? [])
    setPhaseStatus(payload.phaseStatus)
    setAvailableNextAction(payload.availableNextAction)
    setCurrentPhase(payload.currentPhase)

    const filesFromStatus = payload.phaseStatus?.specializationMaterials.files ?? []
    const parsedMateriales = parseMaterialesFromFiles(filesFromStatus)
    setMaterialesByGranule(parsedMateriales.length > 0 ? parsedMateriales : parseMaterialesFromLogs(payload.logs ?? []))
  }

  const pollJobUntilIdle = (createdJobId: string) => {
    clearPolling()
    pollRef.current = window.setInterval(async () => {
      try {
        const statusResponse = await fetch(`${apiBaseUrl}/api/jobs/${createdJobId}`)
        if (!statusResponse.ok) return

        const payload = (await statusResponse.json()) as JobStatusResponse
        applyJobStatus(payload)

        if (payload.status === 'completed') {
          setStatus('finalizado')
          setIsGenerating(false)
          clearPolling()
        }

        if (payload.status === 'failed') {
          setStatus('error')
          setIsGenerating(false)
          setGenerationMessage('La fase falló. Los resultados anteriores quedan disponibles y puedes reintentar.')
          clearPolling()
        }
      } catch {
        setStatus('error')
        setIsGenerating(false)
        setGenerationMessage('No fue posible consultar el estado del job.')
        clearPolling()
      }
    }, 3000)
  }

  const handleGenerate = async () => {
    if (!selectedFile || !selectedPrompt || isGenerating || detectedGranules.length === 0) return

    setIsGenerating(true)
    setJobLogs([])
    setGeneratedDocuments([])
    setMaterialesByGranule([])
    setJobId(null)
    setPhaseStatus(null)
    setAvailableNextAction('none')
    setStatus('leyendo syllabus')
    setGenerationMessage(isEspecializacion
      ? 'Fase 1: generando gránulos. Al finalizar podrás revisar resultados y continuar con TXT/DOCX académicos.'
      : 'La generación puede tardar aproximadamente 20 minutos.'
    )
    clearPolling()

    try {
      const formData = new FormData()
      formData.append('syllabus', selectedFile)
      formData.append('nivel', selectedPrompt)

      const createResponse = await fetch(`${apiBaseUrl}/api/jobs`, {
        method: 'POST',
        body: formData,
      })

      if (!createResponse.ok) {
        const payload = (await createResponse.json()) as { detail?: string }
        throw new Error(payload.detail ?? 'No se pudo crear el job de generación.')
      }

      const createdJob = (await createResponse.json()) as { jobId: string; status: string }
      setJobId(createdJob.jobId)
      setStatus('pendiente')
      pollJobUntilIdle(createdJob.jobId)
    } catch (error) {
      setStatus('error')
      setIsGenerating(false)
      const message = error instanceof Error ? error.message : 'Error iniciando la generación.'
      setGenerationMessage(message)
    }
  }

  const startExistingJobPhase = async (path: string, runningStatus: GenerationStatus, message: string) => {
    if (!jobId || isGenerating) return
    setIsGenerating(true)
    setStatus(runningStatus)
    setGenerationMessage(message)
    setAvailableNextAction('none')
    clearPolling()

    try {
      const response = await fetch(`${apiBaseUrl}${path}`, { method: 'POST' })
      if (!response.ok) {
        const payload = (await response.json()) as { detail?: string }
        throw new Error(payload.detail ?? 'No se pudo iniciar la fase.')
      }
      pollJobUntilIdle(jobId)
    } catch (error) {
      setStatus('error')
      setIsGenerating(false)
      const message = error instanceof Error ? error.message : 'Error iniciando la fase.'
      setGenerationMessage(message)
    }
  }

  const handleGeneratePipelineLocal = () => {
    if (!jobId) return
    startExistingJobPhase(
      `/api/jobs/${jobId}/pipeline-local`,
      'generando txt',
      'Fase 2: generando TXT y DOCX académicos con el pipeline local existente.',
    )
  }

  const handleGenerateSpecializationMaterials = () => {
    if (!jobId) return
    startExistingJobPhase(
      `/api/jobs/${jobId}/materiales-especializacion`,
      'generando materiales especialización',
      'Fase 3: generando materiales de Especialización por gránulo.',
    )
  }

  const handleRetryCurrentPhase = () => {
    if (phaseStatus?.specializationMaterials.status === 'failed') {
      handleGenerateSpecializationMaterials()
      return
    }
    if (phaseStatus?.pipelineLocal.status === 'failed') {
      handleGeneratePipelineLocal()
      return
    }
    handleGenerate()
  }

  const handleReset = () => {
    resetForNewSyllabus()
  }

  const handlePromptChange = (prompt: PromptType | '') => {
    setSelectedPrompt(prompt)
    handleReset()
  }

  useEffect(() => () => clearPolling(), [])

  useEffect(() => {
    if (!selectedFile || !canUploadSyllabus) return
    const t = window.setTimeout(() => {
      alignPipelineTopWithViewport()
    }, 180)
    return () => window.clearTimeout(t)
  }, [selectedFile, canUploadSyllabus, alignPipelineTopWithViewport])

  useEffect(() => {
    if (!selectedFile || !canUploadSyllabus) {
      prevAnalyzingSyllabusRef.current = false
      return
    }
    const finishedAnalysis =
      prevAnalyzingSyllabusRef.current === true && isAnalyzingSyllabus === false
    prevAnalyzingSyllabusRef.current = isAnalyzingSyllabus

    if (!finishedAnalysis) return

    const t = window.setTimeout(() => alignPipelineTopWithViewport(), 120)
    return () => window.clearTimeout(t)
  }, [selectedFile, canUploadSyllabus, isAnalyzingSyllabus, alignPipelineTopWithViewport])

  useEffect(() => {
    if (!canUploadSyllabus || !hasSyllabus) {
      prevIsGeneratingRef.current = false
      return
    }
    const generationStarted = !prevIsGeneratingRef.current && isGenerating
    prevIsGeneratingRef.current = isGenerating

    if (!generationStarted) return

    const t = window.setTimeout(() => {
      alignTopWithViewport(resultsPanelRef.current)
    }, 180)
    return () => window.clearTimeout(t)
  }, [canUploadSyllabus, hasSyllabus, isGenerating, alignTopWithViewport])

  return (
    <div className="granules-view">
      <div className="granules-view-content">
        <div className="view-header">
          <BackButton onBack={onBack} />
          <div className="view-header-text">
            <h1 className="view-title">Creación de gránulos</h1>
            <p className="view-subtitle">Genera documentos académicos estructurados a partir de un syllabus.</p>
          </div>
        </div>

        <section className="grid-layout granules-config-grid">
          <PromptSelector selectedPrompt={selectedPrompt} onSelectPrompt={handlePromptChange} />
        </section>

        {!canUploadSyllabus && (
          <section className="action-card granule-card setup-card">
            <p className="muted">Selecciona el tipo de prompt (nivel académico) para continuar.</p>
            <p className="card-description">
              Esta configuración define el enfoque con el que se prepararán los gránulos a partir del syllabus.
            </p>
          </section>
        )}

        {canUploadSyllabus && (
          <>
            <FileDropzone
              selectedFile={selectedFile}
              onFileSelected={async (file) => {
                handleReset()
                setSelectedFile(file)

                if (!file) {
                  setDetectedGranules([])
                  setPreviewMessage('')
                  return
                }

                if (!file.name.toLowerCase().endsWith('.docx')) {
                  setDetectedGranules([])
                  setPreviewMessage('El archivo debe ser .docx')
                  return
                }

                await analyzeSyllabusPreview(file)
              }}
            />

            {hasSyllabus && (
              <>
                <DetectedGranulesPreview
                  ref={pipelineCardRef}
                  fileName={selectedFile?.name ?? null}
                  subjectName={subjectName}
                  programName={programName}
                  selectedPrompt={(selectedPrompt || 'pregrado') as PromptType}
                  granules={detectedGranules}
                  isAnalyzing={isAnalyzingSyllabus}
                  previewMessage={previewMessage}
                  generationMessage={generationMessage}
                  isGenerating={isGenerating}
                  canGenerate={Boolean(selectedFile) && detectedGranules.length > 0 && !jobId}
                  onGenerate={handleGenerate}
                />
                <JobProgressPanel
                  status={status}
                  logs={jobLogs}
                  granules={detectedGranules}
                  isGenerating={isGenerating}
                  isError={status === 'error'}
                  generatedFilesCount={generatedDocuments.length}
                  totalMaterialsExpected={30}
                  backendCurrentPhase={currentPhase}
                  onRetry={handleRetryCurrentPhase}
                />
              </>
            )}
          </>
        )}

        {canUploadSyllabus && hasSyllabus && (
          <ResultsPanel
            ref={resultsPanelRef}
            jobId={jobId}
            documents={generatedDocuments}
            materialesByGranule={materialesByGranule}
            isVisible={Boolean(jobId)}
            phaseStatus={phaseStatus}
            availableNextAction={availableNextAction}
            isGenerating={isGenerating}
            onGeneratePipelineLocal={handleGeneratePipelineLocal}
            onGenerateSpecializationMaterials={handleGenerateSpecializationMaterials}
          />
        )}
      </div>
    </div>
  )
}

export default GranulesView

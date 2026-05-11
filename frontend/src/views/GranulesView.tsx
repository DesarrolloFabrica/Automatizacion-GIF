import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import FileDropzone from '../components/FileDropzone'
import JobProgressPanel from '../components/JobProgressPanel'
import PromptSelector from '../components/PromptSelector'
import ResultsPanel from '../components/ResultsPanel'
import { CATEGORY_CONFIGS, getCategoryConfig } from '../data/categories'
import { API_BASE_URL, apiFetch, readApiErrorDetail } from '../lib/api'
import type { AvailableNextAction, CategoryConfig, GenerationStatus, GranuleMaterials, JobPhaseStatus, JobStatusResponse, PromptType, SyllabusPreviewResponse } from '../types/granules'

interface GranulesViewProps {
  onBack: () => void
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
  const [, setGenerationMessage] = useState('')
  const [availableNextAction, setAvailableNextAction] = useState<AvailableNextAction>('generate_granules')
  const [phaseStatus, setPhaseStatus] = useState<JobPhaseStatus | null>(null)
  const [currentPhase, setCurrentPhase] = useState('pending')
  const [isFullPipelineRunning, setIsFullPipelineRunning] = useState(false)
  const [categories, setCategories] = useState<CategoryConfig[]>(CATEGORY_CONFIGS)
  const pollRef = useRef<number | null>(null)
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
    setIsFullPipelineRunning(false)
    setSubjectName('')
    setProgramName('')
    setPreviewMessage('')
    setGenerationMessage('')
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
          relativePath: `${materialsDir}/${folderName}/${nn}_${granuleCode}_${tema}_V01.docx`,
        })
        granuleMat.totalMaterials = granuleMat.files.length
      }
    }

    return Array.from(granuleMap.values()).sort((a, b) => a.granuleCode.localeCompare(b.granuleCode))
  }

  const parseMaterialesFromFiles = (files: string[]): GranuleMaterials[] => {
    const granuleMap = new Map<string, GranuleMaterials>()
    for (const relativePath of files) {
      if (!relativePath.startsWith(`${materialsDir}/`)) continue
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

  const fetchJobStatus = async (targetJobId: string): Promise<JobStatusResponse> => {
    const statusResponse = await apiFetch(`/api/jobs/${targetJobId}`)
    if (!statusResponse.ok) throw new Error('No fue posible consultar el estado del job.')
    const payload = (await statusResponse.json()) as JobStatusResponse
    applyJobStatus(payload)
    return payload
  }

  const waitForJobIdle = (targetJobId: string, phaseLabel: string): Promise<JobStatusResponse> => {
    return new Promise((resolve, reject) => {
      const intervalId = window.setInterval(async () => {
        try {
          const payload = await fetchJobStatus(targetJobId)
          if (payload.status === 'completed') {
            window.clearInterval(intervalId)
            resolve(payload)
          }
          if (payload.status === 'failed') {
            window.clearInterval(intervalId)
            reject(new Error(`Error en fase ${phaseLabel}.`))
          }
        } catch (error) {
          window.clearInterval(intervalId)
          reject(error)
        }
      }, 3000)
    })
  }

  const createGranulesJob = async (): Promise<string> => {
    if (!selectedFile || !selectedPrompt) throw new Error('Falta seleccionar syllabus y nivel académico.')

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
    setJobId(createdJob.jobId)
    return createdJob.jobId
  }

  const postExistingJobPhase = async (targetJobId: string, path: string, runningStatus: GenerationStatus, message: string) => {
    setStatus(runningStatus)
    setGenerationMessage(message)
    setAvailableNextAction('none')
    const response = await apiFetch(path, { method: 'POST' })
    if (!response.ok) {
      throw new Error(await readApiErrorDetail(response, 'No se pudo iniciar la fase.'))
    }
    return waitForJobIdle(targetJobId, message)
  }

  const pollJobUntilIdle = (createdJobId: string) => {
    clearPolling()
    pollRef.current = window.setInterval(async () => {
      try {
        const statusResponse = await apiFetch(`/api/jobs/${createdJobId}`)
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
    setGenerationMessage(`Fase 1: generando gránulos de ${categoryLabel}. Al finalizar podrás continuar con TXT/DOCX académicos.`)
    clearPolling()

    try {
      const createdJobId = await createGranulesJob()
      setStatus('pendiente')
      pollJobUntilIdle(createdJobId)
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
      const response = await apiFetch(path, { method: 'POST' })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo iniciar la fase.'))
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

  const handleGenerateMaterials = () => {
    if (!jobId) return
    startExistingJobPhase(
      `/api/jobs/${jobId}/materials`,
      'generando materiales',
      `Fase 3: generando materiales de ${categoryLabel} por gránulo.`,
    )
  }

  const handleGenerateFullLocalPackage = async () => {
    if (!selectedFile || !selectedPrompt || isGenerating || isFullPipelineRunning || detectedGranules.length === 0) return

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
    clearPolling()

    try {
      const createdJobId = await createGranulesJob()
      await waitForJobIdle(createdJobId, '1: generar gránulos')
      await postExistingJobPhase(
        createdJobId,
        `/api/jobs/${createdJobId}/pipeline-local`,
        'generando txt',
        'Fase 2: generando TXT/DOCX académicos.',
      )
      await postExistingJobPhase(
        createdJobId,
        `/api/jobs/${createdJobId}/materials`,
        'generando materiales',
        'Fase 3: generando materiales por gránulo.',
      )
      await fetchJobStatus(createdJobId)
      setStatus('finalizado')
      setGenerationMessage('Paquete completo listo. Puedes descargar el ZIP final institucional.')
    } catch (error) {
      setStatus('error')
      const message = error instanceof Error ? error.message : 'Error ejecutando el flujo completo local.'
      setGenerationMessage(message)
    } finally {
      setIsGenerating(false)
      setIsFullPipelineRunning(false)
    }
  }

  const handleRetryCurrentPhase = () => {
    if (phaseStatus?.specializationMaterials.status === 'failed') {
      handleGenerateMaterials()
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
    let cancelled = false
    apiFetch('/api/categories')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('No categories')))
      .then((payload: CategoryConfig[]) => {
        if (!cancelled && Array.isArray(payload) && payload.length > 0) setCategories(payload)
      })
      .catch(() => {
        if (!cancelled) setCategories(CATEGORY_CONFIGS)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const consoleStatus = status === 'error'
    ? 'Error'
    : availableNextAction === 'download_package'
      ? 'Paquete listo'
      : isGenerating
        ? 'Procesando'
        : 'Sistema listo'

  const canRunFullPackage = Boolean(selectedFile) && detectedGranules.length > 0 && !isGenerating && !isFullPipelineRunning
  const canRunGranulesOnly = Boolean(selectedFile) && detectedGranules.length > 0 && !jobId && !isGenerating

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
            )}

            <section className="action-card local-full-run-card console-primary-action">
              <div>
                <span className="view-kicker">Acción principal</span>
                <h2>Generar paquete académico completo</h2>
                <p className="card-description">Ejecuta gránulos, TXT/DOCX, recursos complementarios y ZIP final con el flujo local existente.</p>
              </div>
              <button
                type="button"
                className="primary-button primary-button--hero"
                onClick={handleGenerateFullLocalPackage}
                disabled={!canRunFullPackage}
              >
                {isFullPipelineRunning ? 'Generando paquete...' : 'Generar paquete académico completo'}
              </button>
              <div className="console-secondary-actions">
                <button type="button" className="secondary-button" onClick={handleGenerate} disabled={!canRunGranulesOnly}>Generar solo gránulos</button>
                {jobId && generatedDocuments.length > 0 && (
                  <a className="secondary-button link-button" href={`${API_BASE_URL}/api/jobs/${jobId}/download/granules`} target="_blank" rel="noreferrer">Descargar gránulos</a>
                )}
                {jobId && availableNextAction === 'download_package' && (
                  <a className="secondary-button link-button" href={`${API_BASE_URL}/api/jobs/${jobId}/download-all`} target="_blank" rel="noreferrer">Descargar paquete</a>
                )}
              </div>
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

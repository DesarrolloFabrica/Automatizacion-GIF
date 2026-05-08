import { useCallback, useEffect, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import DetectedGranulesPreview from '../components/DetectedGranulesPreview'
import FileDropzone from '../components/FileDropzone'
import PromptSelector from '../components/PromptSelector'
import ResultsPanel from '../components/ResultsPanel'
import type { GenerationStatus, JobStatusResponse, PromptType, SyllabusPreviewResponse } from '../types/granules'

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
  const [jobId, setJobId] = useState<string | null>(null)
  const [, setJobLogs] = useState<string[]>([])
  const [generationMessage, setGenerationMessage] = useState('La generación puede tardar aproximadamente 20 minutos.')
  const pollRef = useRef<number | null>(null)
  const pipelineCardRef = useRef<HTMLElement | null>(null)
  const resultsPanelRef = useRef<HTMLElement | null>(null)
  const prevAnalyzingSyllabusRef = useRef(false)
  const prevIsGeneratingRef = useRef(false)
  const canUploadSyllabus = Boolean(selectedPrompt)
  const hasSyllabus = Boolean(selectedFile)

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
    setIsGenerating(false)
    setJobLogs([])
    setJobId(null)
    setSubjectName('')
    setProgramName('')
    setPreviewMessage('')
    setGenerationMessage('La generación puede tardar aproximadamente 20 minutos.')
    setSelectedFile(null)
    setDetectedGranules([])
    setIsAnalyzingSyllabus(false)
    clearPolling()
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
      setSubjectName(preview.subjectName || '')
      setProgramName(preview.programName ?? '')
      setDetectedGranules(preview.detectedTopics.map((topic) => ({ id: `G${topic.index}`, label: topic.title })))

      if (preview.detectedTopics.length === 0) {
        setPreviewMessage('No se encontraron contenidos en la estructura temática')
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

  const handleGenerate = async () => {
    if (!selectedFile || !selectedPrompt || isGenerating) return

    setIsGenerating(true)
    setJobLogs([])
    setGeneratedDocuments([])
    setJobId(null)
    setStatus('leyendo syllabus')
    setGenerationMessage('La generación puede tardar aproximadamente 20 minutos.')
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

      pollRef.current = window.setInterval(async () => {
        try {
          const statusResponse = await fetch(`${apiBaseUrl}/api/jobs/${createdJob.jobId}`)
          if (!statusResponse.ok) return

          const payload = (await statusResponse.json()) as JobStatusResponse
          setStatus(payload.progressStep)
          setJobLogs(payload.logs ?? [])

          if (payload.status === 'completed') {
            setGeneratedDocuments(payload.files ?? [])
            setStatus('finalizado')
            setIsGenerating(false)
            clearPolling()
          }

          if (payload.status === 'failed') {
            setStatus('error')
            setIsGenerating(false)
            setGenerationMessage('La generación falló. Revisa el log para ver el error real.')
            clearPolling()
          }
        } catch {
          setStatus('error')
          setIsGenerating(false)
          setGenerationMessage('No fue posible consultar el estado del job.')
          clearPolling()
        }
      }, 4000)
    } catch (error) {
      setStatus('error')
      setIsGenerating(false)
      const message = error instanceof Error ? error.message : 'Error iniciando la generación.'
      setGenerationMessage(message)
    }
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
                canGenerate={Boolean(selectedFile)}
                onGenerate={handleGenerate}
              />
            )}
          </>
        )}

        {canUploadSyllabus && hasSyllabus && (
          <ResultsPanel
            ref={resultsPanelRef}
            jobId={jobId}
            documents={generatedDocuments}
            isVisible={status === 'finalizado'}
          />
        )}
      </div>
    </div>
  )
}

export default GranulesView
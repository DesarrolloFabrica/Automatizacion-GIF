import { useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import DetectedGranulesPreview from '../components/DetectedGranulesPreview'
import FileDropzone from '../components/FileDropzone'
import GenerationProgress from '../components/GenerationProgress'
import PromptSelector from '../components/PromptSelector'
import ResultsPanel from '../components/ResultsPanel'
import { DEFAULT_MOCK_GRANULES, PIPELINE_STEPS } from '../data/mockGranules'
import type { GenerationStatus, JobStatusResponse, PromptType, SyllabusPreviewResponse } from '../types/granules'

interface GranulesViewProps {
  onBack: () => void
}

const orderedStatuses: GenerationStatus[] = [
  'pendiente',
  'leyendo syllabus',
  'detectando estructura temática',
  'preparando prompts',
  'generando documentos',
  'finalizado',
]

function GranulesView({ onBack }: GranulesViewProps) {
  const apiBaseUrl = 'http://localhost:8000'
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptType>('pregrado')
  const [detectedGranules, setDetectedGranules] = useState(DEFAULT_MOCK_GRANULES)
  const [subjectName, setSubjectName] = useState('')
  const [isAnalyzingSyllabus, setIsAnalyzingSyllabus] = useState(false)
  const [previewMessage, setPreviewMessage] = useState('')
  const [status, setStatus] = useState<GenerationStatus>('pendiente')
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedDocuments, setGeneratedDocuments] = useState<string[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobLogs, setJobLogs] = useState<string[]>([])
  const [generationMessage, setGenerationMessage] = useState('La generación puede tardar aproximadamente 20 minutos.')
  const pollRef = useRef<number | null>(null)

  const currentStepIndex = useMemo(
    () => orderedStatuses.findIndex((step) => step === status),
    [status],
  )

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
    setPreviewMessage('')
    setGenerationMessage('La generación puede tardar aproximadamente 20 minutos.')
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
    } finally {
      setIsAnalyzingSyllabus(false)
    }
  }

  const handleGenerate = async () => {
    if (!selectedFile || isGenerating) return

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

  useEffect(() => () => clearPolling(), [])

  return (
    <div className="granules-view">
      <div className="granules-view-bg">
        <div className="bg-gradient-tl" />
        <div className="bg-grid-pattern" />
      </div>

      <div className="granules-view-content">
        <div className="view-header">
          <BackButton onBack={onBack} />
          <div className="view-header-text">
            <h1 className="view-title">Creación de gránulos</h1>
            <p className="view-subtitle">Genera documentos académicos estructurados a partir de un syllabus.</p>
          </div>
        </div>

        <section className="grid-layout">
          <FileDropzone
            selectedFile={selectedFile}
            onFileSelected={async (file) => {
              handleReset()
              setSelectedFile(file)

              if (!file) {
                setDetectedGranules(DEFAULT_MOCK_GRANULES)
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
          <PromptSelector selectedPrompt={selectedPrompt} onSelectPrompt={setSelectedPrompt} />
        </section>

        <DetectedGranulesPreview
          fileName={selectedFile?.name ?? null}
          subjectName={subjectName}
          selectedPrompt={selectedPrompt}
          granules={detectedGranules}
          isAnalyzing={isAnalyzingSyllabus}
          previewMessage={previewMessage}
        />

        <section className="action-card">
          <p className="muted">{generationMessage}</p>
          <button
            type="button"
            className="primary-button"
            onClick={handleGenerate}
            disabled={!selectedFile || isGenerating || isAnalyzingSyllabus}
          >
            {isGenerating ? 'Procesando...' : 'Generar gránulos'}
          </button>
        </section>

        <GenerationProgress
          status={status}
          currentStepIndex={currentStepIndex}
          steps={PIPELINE_STEPS}
          hasError={status === 'error'}
          logs={jobLogs}
        />

        <ResultsPanel jobId={jobId} documents={generatedDocuments} isVisible={status === 'finalizado'} />
      </div>
    </div>
  )
}

export default GranulesView
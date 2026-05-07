import { useMemo, useState } from 'react'
import BackButton from '../components/BackButton'
import { SCRIPT_PIPELINE_STEPS, SCRIPT_TYPES } from '../data/mockScripts'
import type { ScriptGenerationStatus, ScriptType } from '../data/mockScripts'

interface ScriptsViewProps {
  onBack: () => void
}

// ============================================================
// MOCK TEMPORAL hasta conectar endpoint real de generación de guiones
// ============================================================
// Futuro endpoint: POST /api/scripts/generate
// Payload esperado:
// {
//   "granule_file": File (.docx),
//   "script_type": "video" | "podcast" | "interactive" | "guided-class",
//   "nivel": "pregrado" | "especializacion" | "maestria" | "diplomado"
// }
// Respuesta esperada:
// {
//   "jobId": string,
//   "status": "queued" | "running" | "completed" | "failed",
//   "progressStep": ScriptGenerationStatus,
//   "logs": string[],
//   "files": string[]
// }
// Polling: GET /api/scripts/jobs/{jobId} cada 4s
// Descarga: GET /api/scripts/jobs/{jobId}/files/{filename}
// ============================================================

function ScriptsView({ onBack }: ScriptsViewProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedScriptType, setSelectedScriptType] = useState<ScriptType | null>(null)
  const [status, setStatus] = useState<ScriptGenerationStatus>('pendiente')
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationMessage, setGenerationMessage] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const [generatedDocuments, setGeneratedDocuments] = useState<string[]>([])

  const currentStepIndex = useMemo(
    () => SCRIPT_PIPELINE_STEPS.findIndex((step) => step === status),
    [status],
  )

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null
    if (file && !file.name.toLowerCase().endsWith('.docx')) {
      setSelectedFile(null)
      return
    }
    setSelectedFile(file)
    resetState()
  }

  const resetState = () => {
    setStatus('pendiente')
    setIsGenerating(false)
    setGenerationMessage('')
    setLogs([])
    setGeneratedDocuments([])
  }

  // Mock temporal: simula generación con setTimeout
  // Cuando se conecte el backend real, reemplazar por:
  // 1. POST /api/scripts/generate con FormData
  // 2. Polling GET /api/scripts/jobs/{jobId}
  const handleGenerate = async () => {
    if (!selectedFile || !selectedScriptType || isGenerating) return

    setIsGenerating(true)
    setLogs([])
    setGeneratedDocuments([])
    setStatus('pendiente')
    setGenerationMessage('Generando guion instruccional...')

    const mockSteps: ScriptGenerationStatus[] = [
      'leyendo gránulo',
      'extrayendo estructura',
      'preparando prompt',
      'generando guion',
      'finalizado',
    ]

    const mockLogMessages: Record<ScriptGenerationStatus, string> = {
      'pendiente': 'Iniciando proceso de generación...',
      'leyendo gránulo': `Leyendo archivo: ${selectedFile.name}`,
      'extrayendo estructura': 'Extrayendo estructura temática del gránulo...',
      'preparando prompt': `Preparando prompt para tipo: ${SCRIPT_TYPES.find(t => t.value === selectedScriptType)?.label}`,
      'generando guion': 'Generando guion instruccional con IA...',
      'finalizado': 'Guion generado exitosamente.',
      'error': 'Error durante la generación.',
    }

    for (let i = 0; i < mockSteps.length; i++) {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      const step = mockSteps[i]
      setStatus(step)
      setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${mockLogMessages[step]}`])

      if (step === 'error') {
        setIsGenerating(false)
        setGenerationMessage('La generación falló. Inténtalo de nuevo.')
        return
      }
    }

    setStatus('finalizado')
    setGeneratedDocuments(['Guion_G1.docx'])
    setIsGenerating(false)
    setGenerationMessage('Guion generado exitosamente.')
  }

  return (
    <div className="scripts-view">
      <div className="scripts-view-bg">
        <div className="bg-gradient-tl" />
        <div className="bg-grid-pattern" />
      </div>

      <div className="scripts-view-content">
        <div className="view-header">
          <BackButton onBack={onBack} />
          <div className="view-header-text">
            <h1 className="view-title">Creación de guiones</h1>
            <p className="view-subtitle">Genera guiones instruccionales a partir de un gránulo académico previamente creado.</p>
          </div>
        </div>

        <div className="scripts-layout">
          <div className="scripts-main">
            {/* Paso 1: Subir gránulo */}
            <article className="card scripts-step-card">
              <div className="scripts-step-header">
                <span className="scripts-step-badge">Paso 1</span>
                <h2>Cargar gránulo</h2>
              </div>
              <p className="card-description">Carga un gránulo académico generado previamente en formato .docx.</p>

              <label htmlFor="granule-file" className="file-input-label">
                Seleccionar gránulo .docx
              </label>
              <input id="granule-file" type="file" accept=".docx" onChange={handleFileSelect} className="file-input" />

              {selectedFile && (
                <div className="scripts-file-preview">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
                    <path d="M14 2v6h6" />
                  </svg>
                  <span className="scripts-file-name">{selectedFile.name}</span>
                  <span className="scripts-file-status">Listo para analizar</span>
                </div>
              )}
            </article>

            {/* Paso 2: Selector de tipo de guion */}
            <article className="card scripts-step-card">
              <div className="scripts-step-header">
                <span className="scripts-step-badge">Paso 2</span>
                <h2>Tipo de guion</h2>
              </div>
              <p className="card-description">Selecciona el formato de guion instruccional que deseas generar.</p>

              <div className="script-type-grid">
                {SCRIPT_TYPES.map((type) => (
                  <button
                    key={type.value}
                    type="button"
                    className={`script-type-card ${selectedScriptType === type.value ? 'script-type-card--selected' : ''}`}
                    onClick={() => setSelectedScriptType(type.value)}
                  >
                    <span className="script-type-icon">
                      {type.value === 'video' && (
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polygon points="5 3 19 12 5 21 5 3" />
                        </svg>
                      )}
                      {type.value === 'podcast' && (
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                          <line x1="12" y1="19" x2="12" y2="22" />
                        </svg>
                      )}
                      {type.value === 'interactive' && (
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="2" y="3" width="20" height="14" rx="2" />
                          <path d="M12 17v5" />
                          <path d="M8 22h8" />
                        </svg>
                      )}
                      {type.value === 'guided-class' && (
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2Z" />
                          <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7Z" />
                        </svg>
                      )}
                    </span>
                    <span className="script-type-label">{type.label}</span>
                    <span className="script-type-desc">{type.description}</span>
                  </button>
                ))}
              </div>
            </article>

            {/* Botón generar */}
            <section className="action-card scripts-generate-section">
              <p className="muted">{generationMessage || 'Configura el gránulo y tipo de guion para comenzar.'}</p>
              <button
                type="button"
                className="primary-button"
                onClick={handleGenerate}
                disabled={!selectedFile || !selectedScriptType || isGenerating}
              >
                {isGenerating ? 'Generando...' : 'Generar guion'}
              </button>
            </section>

            {/* Progreso mock */}
            {(isGenerating || status !== 'pendiente') && (
              <article className="card">
                <h2>Estado de procesamiento</h2>
                <p className="card-description">Seguimiento visual del flujo de generación de guiones.</p>

                <ol className="progress-list">
                  {SCRIPT_PIPELINE_STEPS.map((step, index) => {
                    const isCompleted = index < currentStepIndex
                    const isCurrent = step === status
                    const hasError = status === 'error'

                    return (
                      <li
                        key={step}
                        className={[
                          'progress-item',
                          isCompleted ? 'is-completed' : '',
                          isCurrent ? 'is-current' : '',
                          hasError && isCurrent ? 'is-error' : '',
                        ].join(' ')}
                      >
                        <span className="progress-dot" />
                        <span>{step}</span>
                      </li>
                    )
                  })}
                </ol>

                {logs.length > 0 && (
                  <div className="logs-box">
                    <pre>{logs.slice(-12).join('\n')}</pre>
                  </div>
                )}
              </article>
            )}

            {/* Resultado mock */}
            {status === 'finalizado' && generatedDocuments.length > 0 && (
              <article className="card">
                <h2>Resultados</h2>
                <p className="card-description">Guiones generados listos para descargar.</p>

                <ul className="results-list">
                  {generatedDocuments.map((fileName) => (
                    <li key={fileName}>
                      <span>{fileName}</span>
                      {/* Mock: URL ficticia. Cuando se conecte backend, usar:
                          /api/scripts/jobs/{jobId}/files/{filename} */}
                      <a className="secondary-button link-button" href="#" onClick={(e) => e.preventDefault()}>
                        Descargar
                      </a>
                    </li>
                  ))}
                </ul>
              </article>
            )}
          </div>

          {/* Panel lateral de resumen */}
          <aside className="scripts-sidebar">
            <article className="card scripts-summary-card">
              <h2>Resumen</h2>
              <div className="scripts-summary-grid">
                <div>
                  <span className="label">Archivo</span>
                  <p className="summary-value">{selectedFile ? selectedFile.name : 'Sin cargar'}</p>
                </div>
                <div>
                  <span className="label">Tipo de guion</span>
                  <p className="summary-value">
                    {selectedScriptType
                      ? SCRIPT_TYPES.find((t) => t.value === selectedScriptType)?.label
                      : 'Sin seleccionar'}
                  </p>
                </div>
                <div>
                  <span className="label">Estado</span>
                  <p className="summary-value">
                    <span className={`summary-status summary-status--${status}`}>
                      {status === 'pendiente' ? 'Listo para generar' : status}
                    </span>
                  </p>
                </div>
              </div>
            </article>
          </aside>
        </div>
      </div>
    </div>
  )
}

export default ScriptsView
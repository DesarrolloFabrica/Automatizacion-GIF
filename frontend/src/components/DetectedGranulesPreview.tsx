import { forwardRef } from 'react'
import type { GranuleTopic, PromptType } from '../types/granules'

interface DetectedGranulesPreviewProps {
  fileName: string | null
  subjectName: string
  selectedPrompt: PromptType
  granules: GranuleTopic[]
  isAnalyzing: boolean
  previewMessage: string
  generationMessage: string
  isGenerating: boolean
  canGenerate: boolean
  onGenerate: () => void
}

function formatPromptLabel(value: PromptType): string {
  if (value === 'pregrado') return 'Pregrado'
  if (value === 'especializacion') return 'Especialización'
  if (value === 'maestria') return 'Maestría'
  return 'Diplomado'
}

const DetectedGranulesPreview = forwardRef<HTMLElement, DetectedGranulesPreviewProps>(function DetectedGranulesPreview(
  {
    fileName,
    subjectName,
    selectedPrompt,
    granules,
    isAnalyzing,
    previewMessage,
    generationMessage,
    isGenerating,
    canGenerate,
    onGenerate,
  },
  ref,
) {
  const hasError = previewMessage.toLowerCase().includes('error') || previewMessage.toLowerCase().includes('failed')

  return (
    <article ref={ref} className="card granule-card pipeline-preview-card granules-pipeline-scroll-target">
      <div className="pipeline-preview-header">
        <div className="pipeline-preview-header-copy">
          <span className="pipeline-preview-badge">PIPELINE</span>
          <h2>Preview del pipeline</h2>
          <p>Vista previa de lo que el sistema detecta antes de generar los documentos.</p>
        </div>
        <div className="pipeline-preview-hero-icon" aria-hidden="true">
          ✦
        </div>
      </div>

      <div className="preview-grid preview-metric-grid pipeline-metric-grid">
        <div className="preview-metric-card pipeline-metric-card">
          <div className="pipeline-metric-top">
            <div className="pipeline-metric-icon" aria-hidden="true">📄</div>
            <span>ARCHIVO CARGADO</span>
          </div>
          <div className="pipeline-metric-copy fade-overflow">
            <strong>{fileName ?? 'Pendiente por cargar'}</strong>
          </div>
        </div>
        <div className="preview-metric-card pipeline-metric-card">
          <div className="pipeline-metric-top">
            <div className="pipeline-metric-icon" aria-hidden="true">🧠</div>
            <span>TIPO DE PROMPT</span>
          </div>
          <div className="pipeline-metric-copy">
            <strong>{formatPromptLabel(selectedPrompt)}</strong>
          </div>
        </div>
        <div className="preview-metric-card pipeline-metric-card">
          <div className="pipeline-metric-top">
            <div className="pipeline-metric-icon" aria-hidden="true">🎓</div>
            <span>ASIGNATURA DETECTADA</span>
          </div>
          <div className="pipeline-metric-copy fade-overflow">
            <strong>{subjectName || 'Sin detectar'}</strong>
          </div>
        </div>
        <div className="preview-metric-card pipeline-metric-card">
          <div className="pipeline-metric-top">
            <div className="pipeline-metric-icon" aria-hidden="true">#</div>
            <span>TOTAL DE GRÁNULOS</span>
          </div>
          <div className="pipeline-metric-copy">
            <strong>{granules.length}</strong>
          </div>
        </div>
      </div>

      {previewMessage && <p className={`preview-alert ${hasError ? 'is-error' : 'is-info'}`}>{previewMessage}</p>}

      {isAnalyzing ? (
        <p className="preview-alert is-info">Analizando estructura temática...</p>
      ) : (
        <ul className="granules-list pipeline-topics-list">
          {granules.map((topic) => (
            <li key={topic.id} className="pipeline-topic-row">
              <div className="pipeline-topic-left">
                <span className="pipeline-topic-badge">{topic.id}</span>
                <span className="pipeline-topic-title">{topic.label}</span>
              </div>
              <div className="pipeline-topic-action">→</div>
            </li>
          ))}
        </ul>
      )}

      <div className="pipeline-preview-footer">
        <span>ⓘ</span>
        <p>Estos son los elementos temáticos que el sistema identificó para construir el flujo de generación.</p>
      </div>

      <section className="pipeline-preview-action">
        <p className="muted">{generationMessage}</p>
        <button
          type="button"
          className="primary-button"
          onClick={onGenerate}
          disabled={!canGenerate || isGenerating || isAnalyzing}
        >
          {isGenerating ? 'Procesando...' : 'Generar gránulos'}
        </button>
      </section>
    </article>
  )
})

export default DetectedGranulesPreview

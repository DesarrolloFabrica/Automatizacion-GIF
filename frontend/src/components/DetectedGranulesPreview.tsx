import { forwardRef } from 'react'
import type { GranuleTopic, PromptType } from '../types/granules'

interface DetectedGranulesPreviewProps {
  fileName: string | null
  subjectName: string
  programName: string
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

function formatPreviewLabel(value: string | null | undefined, fallback: string): string {
  const normalized = (value ?? '').replace(/\s+/g, ' ').trim()
  return normalized || fallback
}

function PreviewMetricCard({
  icon,
  label,
  value,
  clamp = 2,
}: {
  icon: string
  label: string
  value: string | number
  clamp?: 2 | 3
}) {
  const displayValue = String(value)

  return (
    <div className="preview-metric-card pipeline-metric-card" title={displayValue}>
      <div className="pipeline-metric-top">
        <div className="pipeline-metric-icon" aria-hidden="true">{icon}</div>
        <span>{label}</span>
      </div>
      <div className={`pipeline-metric-copy pipeline-metric-copy--clamp-${clamp}`}>
        <strong>{displayValue}</strong>
      </div>
    </div>
  )
}

const DetectedGranulesPreview = forwardRef<HTMLElement, DetectedGranulesPreviewProps>(function DetectedGranulesPreview(
  {
    fileName,
    subjectName,
    programName,
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
  const previewMetrics = [
    {
      icon: '📄',
      label: 'ARCHIVO CARGADO',
      value: formatPreviewLabel(fileName, 'Pendiente por cargar'),
      clamp: 2 as const,
    },
    {
      icon: '🧠',
      label: 'TIPO DE PROMPT',
      value: formatPromptLabel(selectedPrompt),
      clamp: 2 as const,
    },
    {
      icon: '🎓',
      label: 'ASIGNATURA DETECTADA',
      value: formatPreviewLabel(subjectName, 'Sin detectar'),
      clamp: 3 as const,
    },
    {
      icon: '📚',
      label: 'PROGRAMA DETECTADO',
      value: formatPreviewLabel(programName, 'Sin detectar'),
      clamp: 3 as const,
    },
    {
      icon: '#',
      label: 'TOTAL DE GRÁNULOS',
      value: granules.length,
      clamp: 2 as const,
    },
  ]

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
        {previewMetrics.map((metric) => (
          <PreviewMetricCard
            key={metric.label}
            icon={metric.icon}
            label={metric.label}
            value={metric.value}
            clamp={metric.clamp}
          />
        ))}
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
          className={`primary-button ${isGenerating ? 'is-loading' : ''}`}
          onClick={onGenerate}
          disabled={!canGenerate || isGenerating || isAnalyzing}
        >
          {isGenerating && <span className="button-spinner" aria-hidden="true" />}
          {isGenerating ? 'Generando paquete...' : 'Generar gránulos'}
        </button>
      </section>
    </article>
  )
})

export default DetectedGranulesPreview

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
  if (value === 'curso_rapido') return 'Curso rápido'
  if (value === 'pregrado') return 'Pregrado'
  if (value === 'especializacion') return 'Especialización'
  if (value === 'maestria') return 'Maestría'
  if (value === 'curso_externos_profesional') return 'Curso externos profesional'
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
  accentColor,
}: {
  icon: string
  label: string
  value: string | number
  accentColor: string
}) {
  const displayValue = String(value)

  return (
    <div className="preview-metric-card pipeline-metric-card" title={displayValue}>
      <div className="pipeline-metric-top">
        <div className={`pipeline-metric-icon pipeline-metric-icon--${accentColor}`} aria-hidden="true">{icon}</div>
        <span>{label}</span>
      </div>
      <div className="pipeline-metric-copy">
        <strong>{displayValue}</strong>
      </div>
      <div className={`pipeline-metric-accent pipeline-metric-accent--${accentColor}`} />
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
      accentColor: 'blue',
    },
    {
      icon: '🧠',
      label: 'TIPO DE PROMPT',
      value: formatPromptLabel(selectedPrompt),
      accentColor: 'purple',
    },
    {
      icon: '🎓',
      label: 'ASIGNATURA DETECTADA',
      value: formatPreviewLabel(subjectName, 'Sin detectar'),
      accentColor: 'indigo',
    },
    {
      icon: '📚',
      label: 'PROGRAMA DETECTADO',
      value: formatPreviewLabel(programName, 'Sin detectar'),
      accentColor: 'violet',
    },
    {
      icon: '#',
      label: 'TOTAL DE GRÁNULOS',
      value: granules.length,
      accentColor: 'cyan',
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
            accentColor={metric.accentColor}
          />
        ))}
      </div>

      {isAnalyzing ? (
        <div className="preview-alert is-info is-analyzing">
          <div className="analyzing-spinner" aria-hidden="true" />
          <span>Analizando estructura temática del syllabus...</span>
        </div>
      ) : previewMessage ? (
        <p className={`preview-alert ${hasError ? 'is-error' : 'is-info'}`}>{previewMessage}</p>
      ) : null}

      {!isAnalyzing && granules.length > 0 && (
        <ul className="granules-list pipeline-topics-list">
          {granules.map((topic) => (
            <li key={topic.id} className="pipeline-topic-row">
              <div className="pipeline-topic-left">
                <span className="pipeline-topic-badge">{topic.id}</span>
                <span className="pipeline-topic-title">{topic.label}</span>
              </div>
              <div className="pipeline-topic-action">
                <span className="topic-arrow">→</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!isAnalyzing && granules.length === 0 && !previewMessage && (
        <div className="pipeline-empty-state">
          <span className="empty-icon" aria-hidden="true">📋</span>
          <p>Los gránulos aparecerán aquí una vez analizado el syllabus.</p>
        </div>
      )}

      {!isAnalyzing && granules.length > 0 && (
        <div className="pipeline-preview-footer">
          <span>ⓘ</span>
          <p>Estos son los elementos temáticos que el sistema identificó para construir el flujo de generación.</p>
        </div>
      )}

      <section className="pipeline-preview-action">
        <button
          type="button"
          className={`primary-button pipeline-generate-button ${isGenerating ? 'is-loading' : ''}`}
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

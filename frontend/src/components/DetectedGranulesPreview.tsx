import type { GranuleTopic, PromptType } from '../types/granules'

interface DetectedGranulesPreviewProps {
  fileName: string | null
  subjectName: string
  selectedPrompt: PromptType
  granules: GranuleTopic[]
  isAnalyzing: boolean
  previewMessage: string
}

function formatPromptLabel(value: PromptType): string {
  if (value === 'pregrado') return 'Pregrado'
  if (value === 'especializacion') return 'Especialización'
  if (value === 'maestria') return 'Maestría'
  return 'Diplomado'
}

function DetectedGranulesPreview({
  fileName,
  subjectName,
  selectedPrompt,
  granules,
  isAnalyzing,
  previewMessage,
}: DetectedGranulesPreviewProps) {
  return (
    <article className="card">
      <h2>Preview del pipeline</h2>
      <p className="card-description">Vista previa de lo que el sistema detecta antes de generar los documentos.</p>

      <div className="preview-grid">
        <div>
          <span className="label">Archivo cargado</span>
          <p>{fileName ?? 'Pendiente por cargar'}</p>
        </div>
        <div>
          <span className="label">Tipo de prompt</span>
          <p>{formatPromptLabel(selectedPrompt)}</p>
        </div>
        <div>
          <span className="label">Asignatura detectada</span>
          <p>{subjectName || 'Sin detectar'}</p>
        </div>
        <div>
          <span className="label">Total de gránulos</span>
          <p>{granules.length}</p>
        </div>
      </div>

      {previewMessage && <p className="muted">{previewMessage}</p>}

      {isAnalyzing ? (
        <p className="muted">Analizando estructura temática...</p>
      ) : (
        <ul className="granules-list">
          {granules.map((topic) => (
            <li key={topic.id}>
              <strong>{topic.id}:</strong> {topic.label}
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}

export default DetectedGranulesPreview

interface ResultsPanelProps {
  jobId: string | null
  documents: string[]
  isVisible: boolean
}

function ResultsPanel({ jobId, documents, isVisible }: ResultsPanelProps) {
  const apiBase = 'http://localhost:8000'

  return (
    <article className="card">
      <h2>Resultados temporales</h2>
      <p className="card-description">Archivos generados durante la prueba visual del MVP.</p>

      {!isVisible && <p className="muted">Los resultados aparecerán cuando la generación termine.</p>}

      {isVisible && (
        <>
          {/* Botones mock para definir la UX de descarga antes de conectar backend. */}
          <ul className="results-list">
            {documents.map((fileName) => (
              <li key={fileName}>
                <span>{fileName}</span>
                <a
                  className="secondary-button link-button"
                  href={`${apiBase}/api/jobs/${jobId}/files/${encodeURIComponent(fileName)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Descargar
                </a>
              </li>
            ))}
          </ul>
          <a
            className="secondary-button link-button"
            href={`${apiBase}/api/jobs/${jobId}/download-all`}
            target="_blank"
            rel="noreferrer"
          >
            Descargar todos
          </a>
        </>
      )}
    </article>
  )
}

export default ResultsPanel

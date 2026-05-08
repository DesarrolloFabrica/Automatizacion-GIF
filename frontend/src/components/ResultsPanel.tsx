import { forwardRef } from 'react'

interface ResultsPanelProps {
  jobId: string | null
  documents: string[]
  isVisible: boolean
}

const ResultsPanel = forwardRef<HTMLElement, ResultsPanelProps>(function ResultsPanel(
  { jobId, documents, isVisible },
  ref,
) {
  const apiBase = 'http://localhost:8000'
  const hasDocs = documents.length > 0

  return (
    <article ref={ref} className="card granule-card granules-results-scroll-target">
      <div className="granule-card-header">
        <span className="granule-card-kicker">RESULTADOS</span>
      </div>
      <div className="granule-card-body">
      <h2>Resultados temporales</h2>
      <p className="card-description">Archivos generados por el proceso actual.</p>

      {!isVisible && <p className="empty-state">Los resultados aparecerán cuando la generación termine.</p>}

      {isVisible && (
        <>
          {!hasDocs && <p className="empty-state">Aún no hay archivos disponibles para descarga.</p>}
          {hasDocs && (
            <>
              <ul className="results-list">
                {documents.map((fileName) => (
                  <li key={fileName}>
                    <span><strong>DOCX</strong> · {fileName}</span>
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
        </>
      )}
      </div>
    </article>
  )
})

export default ResultsPanel

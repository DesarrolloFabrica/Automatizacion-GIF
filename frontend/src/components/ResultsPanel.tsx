import { forwardRef, useMemo } from 'react'
import type { GranuleMaterials } from '../types/granules'

interface ResultsPanelProps {
  jobId: string | null
  documents: string[]
  materialesByGranule: GranuleMaterials[]
  isVisible: boolean
}

const ResultsPanel = forwardRef<HTMLElement, ResultsPanelProps>(function ResultsPanel(
  { jobId, documents, materialesByGranule, isVisible },
  ref,
) {
  const apiBase = 'http://localhost:8000'
  const hasDocs = documents.length > 0
  const hasMateriales = materialesByGranule.length > 0
  const totalMateriales = materialesByGranule.reduce((sum, g) => sum + g.totalMaterials, 0)

  const granuleFiles = useMemo(() => {
    return documents.filter((f) => /^G\d+_/.test(f))
  }, [documents])

  const academicFiles = useMemo(() => {
    return documents.filter((f) => f.startsWith('pipeline_local/'))
  }, [documents])

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
            {!hasDocs && !hasMateriales && <p className="empty-state">Aún no hay archivos disponibles para descarga.</p>}

            {hasDocs && (
              <section className="results-section">
                <h3>Gránulos generados ({granuleFiles.length})</h3>
                <ul className="results-list">
                  {granuleFiles.map((fileName) => (
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
              </section>
            )}

            {academicFiles.length > 0 && (
              <section className="results-section">
                <h3>Archivos académicos generados ({academicFiles.length})</h3>
                <p className="card-description">TXT y DOCX creados por el pipeline local existente. Están incluidos en el paquete completo.</p>
                <ul className="results-list">
                  {academicFiles.map((fileName) => (
                    <li key={fileName}>
                      <span><strong>{fileName.toLowerCase().endsWith('.txt') ? 'TXT' : 'DOCX'}</strong> · {fileName.replace('pipeline_local/', '')}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {hasMateriales && (
              <section className="results-section">
                <h3>Materiales de Especialización ({totalMateriales} archivos)</h3>
                {materialesByGranule.map((granuleMat) => (
                  <div key={granuleMat.granuleCode} className="granule-materials-group">
                    <h4>{granuleMat.granuleCode} — {granuleMat.granuleFolder} ({granuleMat.totalMaterials}/6 materiales)</h4>
                    <ul className="results-list">
                      {granuleMat.files.map((file) => (
                        <li key={file.relativePath}>
                          <span><strong>DOCX</strong> · {file.name}</span>
                          <a
                            className="secondary-button link-button"
                            href={`${apiBase}/api/jobs/${jobId}/files/${encodeURIComponent(file.name)}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Descargar
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </section>
            )}

            {(hasDocs || hasMateriales) && (
              <a
                className="secondary-button link-button"
                href={`${apiBase}/api/jobs/${jobId}/download-all`}
                target="_blank"
                rel="noreferrer"
              >
                Descargar todos
              </a>
            )}
          </>
        )}
      </div>
    </article>
  )
})

export default ResultsPanel

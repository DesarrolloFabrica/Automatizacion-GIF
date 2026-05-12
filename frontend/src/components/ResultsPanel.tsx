import { forwardRef, useMemo } from 'react'
import { API_BASE_URL } from '../lib/api'
import type { AvailableNextAction, CategoryConfig, GranuleMaterials, JobPhaseStatus } from '../types/granules'

interface ResultsPanelProps {
  jobId: string | null
  documents: string[]
  materialesByGranule: GranuleMaterials[]
  isVisible: boolean
  phaseStatus: JobPhaseStatus | null
  availableNextAction: AvailableNextAction
  isGenerating: boolean
  onGeneratePipelineLocal: () => void
  onGenerateSpecializationMaterials: () => void
  category?: CategoryConfig
}

const ResultsPanel = forwardRef<HTMLElement, ResultsPanelProps>(function ResultsPanel(
  {
    jobId,
    documents,
    materialesByGranule,
    isVisible,
    phaseStatus,
    availableNextAction,
    isGenerating,
    onGeneratePipelineLocal,
    onGenerateSpecializationMaterials,
    category,
  },
  ref,
) {
  const apiBase = API_BASE_URL
  const hasDocs = documents.length > 0
  const hasMateriales = materialesByGranule.length > 0
  const totalMateriales = materialesByGranule.reduce((sum, g) => sum + g.totalMaterials, 0)
  const categoryLabel = category?.label ?? 'la categoría'
  const materialsPerGranule = category?.expectedMaterialsPerGranule ?? 0

  const granuleFiles = useMemo(() => {
    return documents.filter((f) => /^G\d+_/.test(f))
  }, [documents])

  const academicFiles = useMemo(() => {
    return documents.filter((f) => f.startsWith('pipeline_local/'))
  }, [documents])

  const granulesStatus = phaseStatus?.granules.status ?? 'pending'
  const pipelineStatus = phaseStatus?.pipelineLocal.status ?? 'pending'
  const materialsStatus = phaseStatus?.specializationMaterials.status ?? 'pending'
  const canDownloadFullPackage = Boolean(
    jobId &&
    granulesStatus === 'completed' &&
    pipelineStatus === 'completed' &&
    materialsStatus === 'completed' &&
    availableNextAction === 'download_package' &&
    !isGenerating,
  )
  const folderSummary = [
    { name: 'SYLLABUS', fullName: 'SYLLABUS', icon: 'DOC', count: jobId ? 1 : 0, description: 'Fuente académica original.' },
    { name: 'CONTENIDOS', fullName: 'CONTENIDOS', icon: 'G1', count: granuleFiles.length, description: 'Gránulos G1-G5 generados.' },
    { name: 'ACTIVIDADES', fullName: 'ACTIVIDADES_MOODLE', icon: 'TXT', count: academicFiles.length, description: 'PDA, QUIZ, ACA, FORO y presentación.' },
    { name: 'RECURSOS', fullName: 'RECURSOS_COMPLEMENTARIOS', icon: '6x', count: totalMateriales, description: `Materiales de ${categoryLabel} por gránulo.` },
  ]

  return (
    <article ref={ref} className="results-console-panel">
      <div className="granule-card-body">
        <div className="results-command-header">
          <div>
            <h2>Entregables</h2>
            <p className="card-description">Assets generados y paquete final en un solo centro compacto.</p>
          </div>
          <span className={`results-readiness-pill ${canDownloadFullPackage ? 'is-ready' : ''}`}>
            {canDownloadFullPackage ? 'Paquete completo listo' : 'Construyendo paquete'}
          </span>
        </div>

        <div className="results-folder-grid">
          {folderSummary.map((folder) => (
            <article key={folder.fullName} className={folder.count > 0 ? 'is-ready' : ''} title={folder.fullName}>
              <i aria-hidden>{folder.icon}</i>
              <span>{folder.name}</span>
              <strong>{folder.count > 0 ? `${folder.count} elemento${folder.count === 1 ? '' : 's'}` : 'Pendiente'}</strong>
              <p>{folder.description}</p>
            </article>
          ))}
        </div>

        {!isVisible && <p className="empty-state results-pending-note">Entregables en espera. Se activan conforme avance el job.</p>}

        {isVisible && (
          <>
            {!hasDocs && !hasMateriales && <p className="empty-state">Aún no hay archivos disponibles para descarga.</p>}

            {hasDocs && (
              <details className="results-section results-details-section">
                <summary><span aria-hidden>G</span> Gránulos generados ({granuleFiles.length})</summary>
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
                {jobId && granuleFiles.length > 0 && (
                  <a className="secondary-button link-button" href={`${apiBase}/api/jobs/${jobId}/download/granules`} target="_blank" rel="noreferrer">
                    Descargar gránulos
                  </a>
                )}
              </details>
            )}

            {academicFiles.length > 0 && (
              <details className="results-section results-details-section">
                <summary><span aria-hidden>A</span> Actividades Moodle ({academicFiles.length})</summary>
                <ul className="results-list">
                  {academicFiles.map((fileName) => (
                    <li key={fileName}>
                      <span><strong>{fileName.toLowerCase().endsWith('.txt') ? 'TXT' : 'DOCX'}</strong> · {fileName.replace('pipeline_local/', '')}</span>
                    </li>
                  ))}
                </ul>
                {jobId && academicFiles.length > 0 && (
                  <a className="secondary-button link-button" href={`${apiBase}/api/jobs/${jobId}/download/pipeline-local`} target="_blank" rel="noreferrer">
                    Descargar TXT/DOCX académicos
                  </a>
                )}
              </details>
            )}

            {hasMateriales && (
              <details className="results-section results-details-section">
                <summary><span aria-hidden>R</span> Recursos complementarios ({totalMateriales})</summary>
                {materialesByGranule.map((granuleMat) => (
                  <div key={granuleMat.granuleCode} className="granule-materials-group">
                    <h4>{granuleMat.granuleCode} — {granuleMat.granuleFolder} ({granuleMat.totalMaterials}/{materialsPerGranule} materiales)</h4>
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
                {jobId && totalMateriales > 0 && (
                  <a className="secondary-button link-button" href={`${apiBase}/api/jobs/${jobId}/download/materials`} target="_blank" rel="noreferrer">
                    Descargar materiales de {categoryLabel}
                  </a>
                )}
              </details>
            )}

            {granulesStatus === 'completed' && pipelineStatus !== 'completed' && (
              <button
                type="button"
                className="primary-button"
                onClick={onGeneratePipelineLocal}
                disabled={isGenerating || availableNextAction === 'none'}
              >
                Generar TXT/DOCX
              </button>
            )}

            {pipelineStatus === 'completed' && materialsStatus !== 'completed' && (
              <button
                type="button"
                className="primary-button"
                onClick={onGenerateSpecializationMaterials}
                disabled={isGenerating || availableNextAction === 'none'}
              >
                Generar materiales por gránulo
              </button>
            )}

            {(hasDocs || hasMateriales) && canDownloadFullPackage && (
              <>
                <aside className="results-compat-note results-compat-note--compact">
                  <strong>ZIP compatible con Windows</strong>
                  <span>Nombres internos optimizados para extracción segura; las descargas individuales conservan nombres académicos completos.</span>
                </aside>
                <a
                  className="primary-button link-button results-package-button"
                  href={`${apiBase}/api/jobs/${jobId}/download-all`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Descargar paquete completo
                </a>
              </>
            )}

            {(hasDocs || hasMateriales) && !canDownloadFullPackage && (
              <button type="button" className="primary-button results-package-button" disabled>
                Disponible cuando finalicen todas las fases.
              </button>
            )}
          </>
        )}
      </div>
    </article>
  )
})

export default ResultsPanel

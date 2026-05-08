import { useEffect, useMemo, useRef, useState } from 'react'
import BackButton from '../components/BackButton'
import {
  SCRIPTS_PIPELINE_STEPS,
  SCRIPTS_LOCAL_PIPELINE_STEPS,
  extractFolderId,
  isValidDriveFolderInput,
  validateLocalGranulesSelection,
} from '../data/mockScripts'
import type {
  DriveUploadLink,
  LocalGeneratedFile,
  ScriptsJobStatusResponse,
  ScriptsLocalJobStatusResponse,
  ScriptsLocalProgressStep,
  ScriptsProgressStep,
} from '../data/mockScripts'

interface ScriptsViewProps {
  onBack: () => void
}

const API_BASE = 'http://localhost:8000'

async function readApiErrorDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    const d = payload.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d))
      return d
        .map((item: unknown) =>
          typeof item === 'object' && item !== null && 'msg' in item
            ? String((item as { msg: string }).msg)
            : JSON.stringify(item),
        )
        .join('; ')
    return 'Solicitud no válida.'
  } catch {
    return 'Error al procesar la respuesta del servidor.'
  }
}

function ScriptsView({ onBack }: ScriptsViewProps) {
  const [mode, setMode] = useState<'drive' | 'local' | null>('drive')

  const [driveFolderInput, setDriveFolderInput] = useState('')
  const [asignatura, setAsignatura] = useState('')
  const [programa, setPrograma] = useState('')

  const [status, setStatus] = useState<ScriptsProgressStep>('pendiente')
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationMessage, setGenerationMessage] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const [driveLinks, setDriveLinks] = useState<DriveUploadLink[]>([])
  const [jobId, setJobId] = useState<string | null>(null)

  const pollRef = useRef<number | null>(null)

  const [localFiles, setLocalFiles] = useState<File[]>([])
  const [localAsignatura, setLocalAsignatura] = useState('')
  const [localPrograma, setLocalPrograma] = useState('')
  const [localStatus, setLocalStatus] = useState<ScriptsLocalProgressStep>('pendiente')
  const [localIsGenerating, setLocalIsGenerating] = useState(false)
  const [localMessage, setLocalMessage] = useState('')
  const [localLogs, setLocalLogs] = useState<string[]>([])
  const [localGeneratedFiles, setLocalGeneratedFiles] = useState<LocalGeneratedFile[]>([])
  const [localJobId, setLocalJobId] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  const localPollRef = useRef<number | null>(null)

  const detectedFolderId = useMemo(() => extractFolderId(driveFolderInput), [driveFolderInput])

  const formValid =
    driveFolderInput.trim().length > 0 &&
    asignatura.trim().length > 0 &&
    programa.trim().length > 0 &&
    isValidDriveFolderInput(driveFolderInput)

  const localValidation = useMemo(() => validateLocalGranulesSelection(localFiles), [localFiles])
  const localFormValid =
    localValidation.ok && localAsignatura.trim().length > 0 && localPrograma.trim().length > 0

  const clearPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const clearLocalPolling = () => {
    if (localPollRef.current !== null) {
      window.clearInterval(localPollRef.current)
      localPollRef.current = null
    }
  }

  useEffect(() => () => clearPolling(), [])
  useEffect(() => () => clearLocalPolling(), [])

  const currentStepIndex = useMemo(() => {
    if (status === 'error') return -1
    const idx = SCRIPTS_PIPELINE_STEPS.findIndex((step) => step === status)
    return idx === -1 ? 0 : idx
  }, [status])

  const complementarioFolderUrl =
    detectedFolderId !== null ? `https://drive.google.com/drive/folders/${detectedFolderId}` : null

  const localCurrentStepIndex = useMemo(() => {
    if (localStatus === 'error') return -1
    const idx = SCRIPTS_LOCAL_PIPELINE_STEPS.findIndex((step) => step === localStatus)
    return idx === -1 ? 0 : idx
  }, [localStatus])

  const addFiles = (incoming: FileList | File[]) => {
    const next = Array.from(incoming)
    if (next.length === 0) return
    setLocalFiles((prev) => {
      const merged = [...prev]
      for (const file of next) {
        const exists = merged.some((item) => item.name === file.name && item.size === file.size)
        if (!exists) merged.push(file)
      }
      return merged
    })
  }

  const removeLocalFile = (index: number) => {
    setLocalFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleGenerate = async () => {
    if (!formValid || isGenerating) return

    clearPolling()
    setIsGenerating(true)
    setLogs([])
    setDriveLinks([])
    setJobId(null)
    setStatus('pendiente')
    setGenerationMessage('Iniciando pipeline desde Drive…')

    try {
      const formData = new FormData()
      formData.append('driveFolderInput', driveFolderInput.trim())
      formData.append('asignatura', asignatura.trim())
      formData.append('programa', programa.trim())

      const createResponse = await fetch(`${API_BASE}/api/scripts/jobs`, {
        method: 'POST',
        body: formData,
      })

      if (!createResponse.ok) {
        throw new Error(await readApiErrorDetail(createResponse))
      }

      const created = (await createResponse.json()) as { jobId: string }
      setJobId(created.jobId)

      pollRef.current = window.setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/api/scripts/jobs/${created.jobId}`)
          if (!res.ok) return

          const payload = (await res.json()) as ScriptsJobStatusResponse
          setLogs(payload.logs ?? [])
          const step = payload.progressStep as ScriptsProgressStep
          setStatus(step === 'error' ? 'error' : step)

          if (payload.status === 'completed') {
            setDriveLinks(payload.driveLinks ?? [])
            setStatus('finalizado')
            setIsGenerating(false)
            setGenerationMessage('Generación completada.')
            clearPolling()
          }

          if (payload.status === 'failed') {
            setStatus('error')
            setIsGenerating(false)
            setGenerationMessage('El proceso falló. Revisa el registro de actividad.')
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
      setGenerationMessage(error instanceof Error ? error.message : 'Error al iniciar el proceso.')
    }
  }

  const handleGenerateLocal = async () => {
    if (!localFormValid || localIsGenerating) return

    clearLocalPolling()
    setLocalIsGenerating(true)
    setLocalLogs([])
    setLocalGeneratedFiles([])
    setLocalJobId(null)
    setLocalStatus('cargando granulos')
    setLocalMessage('Subiendo gránulos al backend...')

    try {
      const formData = new FormData()
      localFiles.forEach((file) => formData.append('granules', file))
      formData.append('asignatura', localAsignatura.trim())
      formData.append('programa', localPrograma.trim())

      const createResponse = await fetch(`${API_BASE}/api/scripts/local/jobs`, {
        method: 'POST',
        body: formData,
      })

      if (!createResponse.ok) {
        throw new Error(await readApiErrorDetail(createResponse))
      }

      const created = (await createResponse.json()) as { jobId: string }
      setLocalJobId(created.jobId)
      setLocalStatus('validando estructura')
      setLocalMessage('Procesando gránulos locales...')

      localPollRef.current = window.setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/api/scripts/local/jobs/${created.jobId}`)
          if (!res.ok) return

          const payload = (await res.json()) as ScriptsLocalJobStatusResponse
          setLocalLogs(payload.logs ?? [])
          const step = payload.progressStep as ScriptsLocalProgressStep
          setLocalStatus(step === 'error' ? 'error' : step)

          if (payload.status === 'completed') {
            setLocalGeneratedFiles(payload.files ?? [])
            setLocalStatus('finalizado')
            setLocalIsGenerating(false)
            setLocalMessage('Generación local completada.')
            clearLocalPolling()
          }

          if (payload.status === 'failed') {
            setLocalStatus('error')
            setLocalIsGenerating(false)
            setLocalMessage('El proceso local falló. Revisa el registro de actividad.')
            clearLocalPolling()
          }
        } catch {
          setLocalStatus('error')
          setLocalIsGenerating(false)
          setLocalMessage('No fue posible consultar el estado del job local.')
          clearLocalPolling()
        }
      }, 4000)
    } catch (error) {
      setLocalStatus('error')
      setLocalIsGenerating(false)
      setLocalMessage(error instanceof Error ? error.message : 'Error al iniciar el proceso local.')
    }
  }

  const txtLinks = driveLinks.filter((l) => l.kind === 'txt')
  const docxLinks = driveLinks.filter((l) => l.kind === 'docx')
  const localTxtFiles = localGeneratedFiles.filter((f) => f.kind === 'txt')
  const localDocxFiles = localGeneratedFiles.filter((f) => f.kind === 'docx')

  return (
    <div className="scripts-view">
      <div className="scripts-view-content">
        <div className="view-header">
          <BackButton onBack={onBack} />
          <div className="view-header-text">
            <h1 className="view-title">Creación de guiones</h1>
            <p className="view-subtitle">
              Genera materiales (TXT y DOCX) a partir de los documentos fuente en una carpeta de Google Drive.
            </p>
          </div>
        </div>

        <div className="scripts-banner muted" style={{ marginBottom: '1rem', padding: '0.75rem 1rem', borderRadius: 8, background: 'rgba(59, 130, 246, 0.08)' }}>
          El proceso puede tardar varios minutos. No cierres esta pestaña.
        </div>

        <section style={{ display: 'grid', gap: '1rem', marginBottom: '1rem' }}>
          <article className="card scripts-step-card">
            <button
              type="button"
              onClick={() => setMode((prev) => (prev === 'drive' ? null : 'drive'))}
              style={{ all: 'unset', display: 'block', cursor: 'pointer', width: '100%' }}
            >
              <div className="scripts-step-header">
                <span className="scripts-step-badge">Modalidad 1</span>
                <h2>Generar desde Google Drive</h2>
              </div>
              <p className="card-description">
                Usa una carpeta de Drive con los gránulos fuente y sube automáticamente los materiales generados.
              </p>
            </button>
            {mode === 'drive' && (
              <>
                <input
                  type="text"
                  className="select-input"
                  placeholder="Pega el link o ID de la carpeta de Drive"
                  value={driveFolderInput}
                  onChange={(event) => setDriveFolderInput(event.target.value)}
                  disabled={isGenerating}
                />
                {detectedFolderId && (
                  <p className="muted" style={{ marginTop: 8, fontSize: '0.85rem' }}>
                    ID detectado: <code>{detectedFolderId}</code>
                  </p>
                )}
                {driveFolderInput.trim() && !isValidDriveFolderInput(driveFolderInput) && (
                  <p style={{ marginTop: 8, color: '#b91c1c', fontSize: '0.85rem' }}>
                    Formato de link o ID no reconocido.
                  </p>
                )}

                <div style={{ marginTop: 14 }}>
                  <label className="label-block" style={{ display: 'block', marginTop: 12 }}>
                    Asignatura
                    <input
                      type="text"
                      className="select-input"
                      value={asignatura}
                      onChange={(event) => setAsignatura(event.target.value)}
                      placeholder="Ej: INTELIGENCIA ARTIFICIAL Y ANALÍTICA AVANZADA..."
                      disabled={isGenerating}
                    />
                  </label>
                  <label className="label-block" style={{ display: 'block', marginTop: 12 }}>
                    Programa
                    <input
                      type="text"
                      className="select-input"
                      value={programa}
                      onChange={(event) => setPrograma(event.target.value)}
                      placeholder="Ej: QUÍMICA FARMACÉUTICA"
                      disabled={isGenerating}
                    />
                  </label>

                  <section className="action-card scripts-generate-section" style={{ marginTop: 12 }}>
                    <p className="muted">{generationMessage || 'Completa los campos para generar materiales.'}</p>
                    <button
                      type="button"
                      className="primary-button"
                      onClick={handleGenerate}
                      disabled={!formValid || isGenerating}
                    >
                      {isGenerating ? 'Generando materiales…' : 'Generar materiales'}
                    </button>
                  </section>
                </div>
              </>
            )}
          </article>

          {mode !== 'drive' && (
            <article className="card scripts-step-card">
            <button
              type="button"
              onClick={() => setMode((prev) => (prev === 'local' ? null : 'local'))}
              style={{ all: 'unset', display: 'block', cursor: 'pointer', width: '100%' }}
            >
              <div className="scripts-step-header">
                <span className="scripts-step-badge">Modalidad 2</span>
                <h2>Generar desde archivos locales</h2>
              </div>
              <p className="card-description">
                Sube los gránulos académicos desde tu computador y descarga los materiales generados al finalizar.
              </p>
            </button>
            {mode === 'local' && (
              <div
                onDragOver={(event) => {
                  event.preventDefault()
                  setIsDragging(true)
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setIsDragging(false)
                  addFiles(event.dataTransfer.files)
                }}
                style={{
                  marginTop: 12,
                  border: `2px dashed ${isDragging ? '#2563eb' : '#cbd5e1'}`,
                  borderRadius: 10,
                  padding: '0.9rem',
                }}
              >
                <label className="file-input-label" htmlFor="local-granules-input">
                  Subir múltiples gránulos .docx
                </label>
                <input
                  id="local-granules-input"
                  type="file"
                  multiple
                  accept=".docx"
                  onChange={(event) => addFiles(event.target.files ?? [])}
                  className="file-input"
                />
                <p className="muted" style={{ marginTop: 8 }}>
                  Arrastra aquí tus archivos o haz clic para seleccionarlos.
                </p>
                {localValidation.reason && (
                  <p
                    style={{
                      marginTop: 8,
                      color:
                        localValidation.level === 'success'
                          ? '#166534'
                          : localValidation.level === 'warning'
                            ? '#a16207'
                            : '#b91c1c',
                    }}
                  >
                    {localValidation.reason}
                  </p>
                )}
                {localFiles.length > 0 && (
                  <ul className="results-list" style={{ marginTop: 10 }}>
                    {localFiles.map((file, index) => (
                      <li key={`${file.name}-${file.size}`}>
                        <span>{file.name}</span>
                        <button type="button" className="secondary-button" onClick={() => removeLocalFile(index)}>
                          Quitar
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                <div style={{ marginTop: 14 }}>
                  <label className="label-block" style={{ display: 'block', marginTop: 12 }}>
                    Asignatura
                    <input
                      type="text"
                      className="select-input"
                      value={localAsignatura}
                      onChange={(event) => setLocalAsignatura(event.target.value)}
                      placeholder="Ej: INTELIGENCIA ARTIFICIAL Y ANALÍTICA AVANZADA..."
                      disabled={localIsGenerating}
                    />
                  </label>
                  <label className="label-block" style={{ display: 'block', marginTop: 12 }}>
                    Programa
                    <input
                      type="text"
                      className="select-input"
                      value={localPrograma}
                      onChange={(event) => setLocalPrograma(event.target.value)}
                      placeholder="Ej: QUÍMICA FARMACÉUTICA"
                      disabled={localIsGenerating}
                    />
                  </label>

                  <section className="action-card scripts-generate-section" style={{ marginTop: 12 }}>
                    <p className="muted">{localMessage || 'Completa los campos para generar materiales localmente.'}</p>
                    <button
                      type="button"
                      className="primary-button"
                      onClick={handleGenerateLocal}
                      disabled={!localFormValid || localIsGenerating}
                    >
                      {localIsGenerating ? 'Generando materiales…' : 'Generar materiales'}
                    </button>
                  </section>
                </div>
              </div>
            )}
            </article>
          )}
        </section>

        {false && mode === 'drive' && (
          <div className="scripts-layout">
            <div className="scripts-main">
              <article className="card scripts-step-card">
                <div className="scripts-step-header">
                  <span className="scripts-step-badge">Metadatos</span>
                  <h2>Asignatura y programa</h2>
                </div>
                <p className="card-description">Estos valores se usan en la generación y en la validación de los materiales.</p>
                <label className="label-block" style={{ display: 'block', marginTop: 12 }}>
                  Asignatura
                  <input
                    type="text"
                    className="select-input"
                    value={asignatura}
                    onChange={(event) => setAsignatura(event.target.value)}
                    placeholder="Ej: INTELIGENCIA ARTIFICIAL Y ANALÍTICA AVANZADA..."
                    disabled={isGenerating}
                  />
                </label>
                <label className="label-block" style={{ display: 'block', marginTop: 12 }}>
                  Programa
                  <input
                    type="text"
                    className="select-input"
                    value={programa}
                    onChange={(event) => setPrograma(event.target.value)}
                    placeholder="Ej: QUÍMICA FARMACÉUTICA"
                    disabled={isGenerating}
                  />
                </label>
              </article>

              <section className="action-card scripts-generate-section">
                <p className="muted">{generationMessage || 'Completa los campos para generar materiales.'}</p>
                <button
                  type="button"
                  className="primary-button"
                  onClick={handleGenerate}
                  disabled={!formValid || isGenerating}
                >
                  {isGenerating ? 'Generando materiales…' : 'Generar materiales'}
                </button>
              </section>

              {(isGenerating || status !== 'pendiente') && (
                <article className="card">
                  <h2>Estado de procesamiento</h2>
                  <p className="card-description">Seguimiento del pipeline Drive (logs del servidor).</p>

                  <ol className="progress-list">
                    {SCRIPTS_PIPELINE_STEPS.map((step, index) => {
                      const isCompleted = status !== 'error' && index < currentStepIndex
                      const isCurrent = status !== 'error' && step === status
                      const hasError = status === 'error'

                      return (
                        <li
                          key={step}
                          className={[
                            'progress-item',
                            isCompleted ? 'is-completed' : '',
                            isCurrent ? 'is-current' : '',
                            hasError && step === 'finalizado' ? 'is-error' : '',
                          ].join(' ')}
                        >
                          <span className="progress-dot" />
                          <span>{step}</span>
                        </li>
                      )
                    })}
                  </ol>

                  {status === 'error' && (
                    <p style={{ color: '#b91c1c', marginTop: 8 }}>El proceso terminó con error.</p>
                  )}

                  {logs.length > 0 && (
                    <div className="logs-box">
                      <pre>{logs.slice(-40).join('\n')}</pre>
                    </div>
                  )}
                </article>
              )}

              {status === 'finalizado' && driveLinks.length > 0 && (
                <article className="card">
                  <h2>Archivos en Drive</h2>
                  <p className="card-description">Enlaces a los materiales generados (abren en una nueva pestaña).</p>

                  {txtLinks.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 12, fontSize: '1rem' }}>TXT</h3>
                      <ul className="results-list">
                        {txtLinks.map((item) => (
                          <li key={`txt-${item.link}`}>
                            <span>{item.name}</span>
                            <a className="secondary-button link-button" href={item.link} target="_blank" rel="noreferrer">
                              Abrir en Drive
                            </a>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}

                  {docxLinks.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 16, fontSize: '1rem' }}>DOCX</h3>
                      <ul className="results-list">
                        {docxLinks.map((item) => (
                          <li key={`docx-${item.link}`}>
                            <span>{item.name}</span>
                            <a className="secondary-button link-button" href={item.link} target="_blank" rel="noreferrer">
                              Abrir en Drive
                            </a>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}

                  {complementarioFolderUrl && (
                    <div style={{ marginTop: 20 }}>
                      <a
                        className="primary-button"
                        href={complementarioFolderUrl ?? undefined}
                        target="_blank"
                        rel="noreferrer"
                        style={{ display: 'inline-block', textDecoration: 'none', textAlign: 'center' }}
                      >
                        Abrir contenido complementario en Drive
                      </a>
                    </div>
                  )}
                </article>
              )}
            </div>

            <aside className="scripts-sidebar">
              <article className="card scripts-summary-card">
                <h2>Resumen</h2>
                <div className="scripts-summary-grid">
                  <div>
                    <span className="label">Modo</span>
                    <p className="summary-value">Drive</p>
                  </div>
                  <div>
                    <span className="label">Carpeta</span>
                    <p className="summary-value">{detectedFolderId ?? '—'}</p>
                  </div>
                  <div>
                    <span className="label">Asignatura</span>
                    <p className="summary-value">{asignatura.trim() || '—'}</p>
                  </div>
                  <div>
                    <span className="label">Programa</span>
                    <p className="summary-value">{programa.trim() || '—'}</p>
                  </div>
                  <div>
                    <span className="label">Job</span>
                    <p className="summary-value">{jobId ?? '—'}</p>
                  </div>
                  <div>
                    <span className="label">Estado</span>
                    <p className="summary-value">
                      <span className={`summary-status summary-status--${status}`}>{status}</span>
                    </p>
                  </div>
                </div>
              </article>
            </aside>
          </div>
        )}

        {mode === 'drive' && (
          <article className="card scripts-step-card" style={{ marginBottom: '1rem' }}>
            <button
              type="button"
              onClick={() => setMode((prev) => (prev === 'local' ? null : 'local'))}
              style={{ all: 'unset', display: 'block', cursor: 'pointer', width: '100%' }}
            >
              <div className="scripts-step-header">
                <span className="scripts-step-badge">Modalidad 2</span>
                <h2>Generar desde archivos locales</h2>
              </div>
              <p className="card-description">
                Sube los gránulos académicos desde tu computador y descarga los materiales generados al finalizar.
              </p>
            </button>
          </article>
        )}

        {false && mode === 'local' && (
          <div className="scripts-layout">
            <div className="scripts-main">
              <article className="card scripts-step-card">
                <div className="scripts-step-header">
                  <span className="scripts-step-badge">Metadatos</span>
                  <h2>Asignatura y programa</h2>
                </div>
                <p className="card-description">Estos valores se usan en la generación y en la validación de los materiales.</p>
                <label className="label-block" style={{ display: 'block', marginTop: 12 }}>
                  Asignatura
                  <input
                    type="text"
                    className="select-input"
                    value={localAsignatura}
                    onChange={(event) => setLocalAsignatura(event.target.value)}
                    placeholder="Ej: INTELIGENCIA ARTIFICIAL Y ANALÍTICA AVANZADA..."
                    disabled={localIsGenerating}
                  />
                </label>
                <label className="label-block" style={{ display: 'block', marginTop: 12 }}>
                  Programa
                  <input
                    type="text"
                    className="select-input"
                    value={localPrograma}
                    onChange={(event) => setLocalPrograma(event.target.value)}
                    placeholder="Ej: QUÍMICA FARMACÉUTICA"
                    disabled={localIsGenerating}
                  />
                </label>
              </article>

              <section className="action-card scripts-generate-section">
                <p className="muted">{localMessage || 'Completa los campos para generar materiales localmente.'}</p>
                <button
                  type="button"
                  className="primary-button"
                  onClick={handleGenerateLocal}
                  disabled={!localFormValid || localIsGenerating}
                >
                  {localIsGenerating ? 'Generando materiales…' : 'Generar materiales'}
                </button>
              </section>

              {(localIsGenerating || localStatus !== 'pendiente') && (
                <article className="card">
                  <h2>Estado de procesamiento local</h2>
                  <p className="card-description">Seguimiento del pipeline local (logs del servidor).</p>

                  <ol className="progress-list">
                    {SCRIPTS_LOCAL_PIPELINE_STEPS.map((step, index) => {
                      const isCompleted = localStatus !== 'error' && index < localCurrentStepIndex
                      const isCurrent = localStatus !== 'error' && step === localStatus
                      const hasError = localStatus === 'error'

                      return (
                        <li
                          key={step}
                          className={[
                            'progress-item',
                            isCompleted ? 'is-completed' : '',
                            isCurrent ? 'is-current' : '',
                            hasError && step === 'finalizado' ? 'is-error' : '',
                          ].join(' ')}
                        >
                          <span className="progress-dot" />
                          <span>{step}</span>
                        </li>
                      )
                    })}
                  </ol>

                  {localStatus === 'error' && (
                    <p style={{ color: '#b91c1c', marginTop: 8 }}>El proceso terminó con error.</p>
                  )}

                  {localLogs.length > 0 && (
                    <div className="logs-box">
                      <pre>{localLogs.slice(-40).join('\n')}</pre>
                    </div>
                  )}
                </article>
              )}

              {localStatus === 'finalizado' && localGeneratedFiles.length > 0 && (
                <article className="card">
                  <h2>Archivos generados localmente</h2>
                  <p className="card-description">Descarga los materiales generados desde el backend.</p>

                  {localTxtFiles.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 12, fontSize: '1rem' }}>TXT</h3>
                      <ul className="results-list">
                        {localTxtFiles.map((file) => (
                          <li key={`local-txt-${file.name}`}>
                            <span>{file.name}</span>
                            <a
                              className="secondary-button link-button"
                              href={`${API_BASE}/api/scripts/local/jobs/${localJobId}/files/${encodeURIComponent(file.name)}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Descargar
                            </a>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}

                  {localDocxFiles.length > 0 && (
                    <>
                      <h3 style={{ marginTop: 16, fontSize: '1rem' }}>DOCX</h3>
                      <ul className="results-list">
                        {localDocxFiles.map((file) => (
                          <li key={`local-docx-${file.name}`}>
                            <span>{file.name}</span>
                            <a
                              className="secondary-button link-button"
                              href={`${API_BASE}/api/scripts/local/jobs/${localJobId}/files/${encodeURIComponent(file.name)}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Descargar
                            </a>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}

                  <div style={{ marginTop: 20 }}>
                    <a
                      className="primary-button"
                      href={`${API_BASE}/api/scripts/local/jobs/${localJobId}/download-all`}
                      target="_blank"
                      rel="noreferrer"
                      style={{ display: 'inline-block', textDecoration: 'none', textAlign: 'center' }}
                    >
                      Descargar todo (.zip)
                    </a>
                  </div>
                </article>
              )}
            </div>

            <aside className="scripts-sidebar">
              <article className="card scripts-summary-card">
                <h2>Resumen</h2>
                <div className="scripts-summary-grid">
                  <div>
                    <span className="label">Modo</span>
                    <p className="summary-value">Local</p>
                  </div>
                  <div>
                    <span className="label">Gránulos</span>
                    <p className="summary-value">{localFiles.length}</p>
                  </div>
                  <div>
                    <span className="label">Asignatura</span>
                    <p className="summary-value">{localAsignatura.trim() || '—'}</p>
                  </div>
                  <div>
                    <span className="label">Programa</span>
                    <p className="summary-value">{localPrograma.trim() || '—'}</p>
                  </div>
                  <div>
                    <span className="label">Job</span>
                    <p className="summary-value">{localJobId ?? '—'}</p>
                  </div>
                  <div>
                    <span className="label">Estado</span>
                    <p className="summary-value">
                      <span className={`summary-status summary-status--${localStatus}`}>{localStatus}</span>
                    </p>
                  </div>
                </div>
              </article>
            </aside>
          </div>
        )}
      </div>
    </div>
  )
}

export default ScriptsView

import type { GenerationStatus } from '../types/granules'

interface GenerationProgressProps {
  status: GenerationStatus
  currentStepIndex: number
  steps: GenerationStatus[]
  hasError: boolean
  logs: string[]
}

function GenerationProgress({ status, currentStepIndex, steps, hasError, logs }: GenerationProgressProps) {
  return (
    <article className="card">
      <h2>Estado de procesamiento</h2>
      <p className="card-description">Seguimiento visual del flujo: leer, detectar, preparar, generar y finalizar.</p>

      {/* El timeline comunica en qué fase va la ejecución del pipeline. */}
      <ol className="progress-list">
        {steps.map((step, index) => {
          const isCompleted = index < currentStepIndex
          const isCurrent = step === status

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

      {/* Logs simples para monitorear el proceso real desde FastAPI polling. */}
      <div className="logs-box">
        {logs.length === 0 ? (
          <p className="muted">Aún no hay logs de ejecución.</p>
        ) : (
          <pre>{logs.slice(-12).join('\n')}</pre>
        )}
      </div>
    </article>
  )
}

export default GenerationProgress

import type { ReactNode } from 'react'

interface FlowCardProps {
  icon: ReactNode
  title: string
  description: string
  bullets: string[]
  ctaLabel: string
  statusLabel: string
  statusVariant: 'available' | 'preview'
  onClick: () => void
  disabled?: boolean
}

/** Marca de agua académica solo en la tarjeta de gránulos (`public/img`). */
const GRANULES_CARD_BOOK_SRC = `/img/${encodeURIComponent('ChatGPT Image 8 may 2026, 07_11_19 a.m..png')}`

function FlowCard({ icon, title, description, bullets, ctaLabel, statusLabel, statusVariant, onClick, disabled = false }: FlowCardProps) {
  const flowKind = statusVariant === 'available' ? 'granules' : 'scripts'
  const flowSteps = statusVariant === 'available' ? ['Syllabus', 'IA', 'ZIP'] : ['Drive', 'Cloud', 'Soon']

  return (
    <article className={`flow-card flow-card--${flowKind} ${disabled ? 'flow-card--disabled' : ''}`}>
      <div className="flow-card-orbit" aria-hidden />
      {flowKind === 'granules' ? (
        <div className="flow-card-book-deco" aria-hidden>
          <img src={GRANULES_CARD_BOOK_SRC} alt="" className="flow-card-book-deco__img" draggable={false} />
        </div>
      ) : null}

      <div className="flow-card-top">
        <div className="flow-card-icon" aria-hidden>
          {icon}
        </div>
        <span className="flow-card-status">{statusLabel}</span>
      </div>

      <div className="flow-card-copy">
        <h2>{title}</h2>
        <p>{description}</p>
      </div>

      <div className="flow-card-mini-pipeline" aria-label="Resumen visual del flujo">
        {flowSteps.map((step) => (
          <span key={step}>{step}</span>
        ))}
      </div>

      <ul className="flow-card-features">
        {bullets.map((bullet) => (
          <li key={bullet}>
            <span className="flow-card-feature-icon" aria-hidden>
              {statusVariant === 'available' ? '✓' : '·'}
            </span>
            <span>{bullet}</span>
          </li>
        ))}
      </ul>

      <button type="button" className="flow-card-button" onClick={onClick} disabled={disabled}>
        <span className="flow-card-button-icon" aria-hidden>
          →
        </span>
        {ctaLabel}
      </button>
    </article>
  )
}

export default FlowCard

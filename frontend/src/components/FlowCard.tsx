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
}

function FlowCard({ icon, title, description, bullets, ctaLabel, statusLabel, statusVariant, onClick }: FlowCardProps) {
  const flowKind = statusVariant === 'available' ? 'granules' : 'scripts'

  return (
    <article className={`flow-card flow-card--${flowKind}`}>
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

      <ul className="flow-card-features">
        {bullets.map((bullet) => (
          <li key={bullet}>
            <span className="flow-card-feature-icon" aria-hidden>
              ✦
            </span>
            <span>{bullet}</span>
          </li>
        ))}
      </ul>

      <button type="button" className="flow-card-button" onClick={onClick}>
        <span className="flow-card-button-icon" aria-hidden>
          →
        </span>
        {ctaLabel}
      </button>
    </article>
  )
}

export default FlowCard

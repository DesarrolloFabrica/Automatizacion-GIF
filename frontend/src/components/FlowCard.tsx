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
  return (
    <article className="flow-card" onClick={onClick}>
      <div className="flow-card-header">
        <div className={`flow-card-icon flow-card-icon--${statusVariant}`}>
          {icon}
        </div>
        <span className={`status-chip status-chip--${statusVariant}`}>
          {statusLabel}
        </span>
      </div>
      <h3 className="flow-card-title">{title}</h3>
      <p className="flow-card-description">{description}</p>
      <ul className="flow-card-bullets">
        {bullets.map((bullet) => (
          <li key={bullet}>{bullet}</li>
        ))}
      </ul>
      <button type="button" className="flow-card-cta">
        {ctaLabel}
      </button>
    </article>
  )
}

export default FlowCard
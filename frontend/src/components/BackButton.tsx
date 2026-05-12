interface BackButtonProps {
  onBack: () => void
}

function BackButton({ onBack }: BackButtonProps) {
  return (
    <button type="button" className="back-button" onClick={onBack}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M19 12H5" />
        <path d="M12 19l-7-7 7-7" />
      </svg>
      Volver al inicio
    </button>
  )
}

export default BackButton
import type { PromptType } from '../types/granules'

interface PromptSelectorProps {
  selectedPrompt: PromptType
  onSelectPrompt: (prompt: PromptType) => void
}

const promptOptions: Array<{ value: PromptType; label: string }> = [
  { value: 'pregrado', label: 'Pregrado' },
  { value: 'especializacion', label: 'Especialización' },
  { value: 'maestria', label: 'Maestría' },
  { value: 'diplomado', label: 'Diplomado' },
]

function PromptSelector({ selectedPrompt, onSelectPrompt }: PromptSelectorProps) {
  return (
    <article className="card">
      <h2>Tipo de prompt</h2>
      <p className="card-description">Selecciona el nivel académico para definir el prompt que se usará en la generación.</p>

      {/* Select controlado para reflejar siempre el estado actual en el preview. */}
      <select
        value={selectedPrompt}
        onChange={(event) => onSelectPrompt(event.target.value as PromptType)}
        className="select-input"
      >
        {promptOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </article>
  )
}

export default PromptSelector

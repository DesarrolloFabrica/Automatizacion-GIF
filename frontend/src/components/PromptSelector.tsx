import type { PromptType } from '../types/granules'

interface PromptSelectorProps {
  selectedPrompt: PromptType | ''
  onSelectPrompt: (prompt: PromptType | '') => void
}

const promptOptions: Array<{ value: PromptType; label: string }> = [
  { value: 'pregrado', label: 'Pregrado' },
  { value: 'especializacion', label: 'Especialización' },
  { value: 'maestria', label: 'Maestría' },
  { value: 'diplomado', label: 'Diplomado' },
]

function PromptSelector({ selectedPrompt, onSelectPrompt }: PromptSelectorProps) {
  return (
    <article className="config-choice-card config-choice-card--prompt">
      <div className="config-choice-top">
        <span className="config-choice-badge">CONFIGURACIÓN</span>
        <span className="config-choice-step">Paso 1</span>
      </div>

      <div className="config-choice-content">
        <h2>Tipo de prompt</h2>
        <p>Selecciona el nivel académico para definir el prompt que se usará en la generación.</p>
      </div>

      <select
        value={selectedPrompt}
        onChange={(event) => onSelectPrompt(event.target.value as PromptType | '')}
        className="config-choice-select"
      >
        <option value="">Selecciona un tipo de prompt</option>
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

import type { PromptType } from '../types/granules'

interface PromptSelectorProps {
  selectedPrompt: PromptType | ''
  onSelectPrompt: (prompt: PromptType | '') => void
}

const promptOptions: Array<{ value: PromptType | ''; label: string; disabled: boolean }> = [
  { value: '', label: 'Selecciona un tipo de prompt', disabled: false },
  { value: 'especializacion', label: 'Especialización', disabled: false },
  { value: 'pregrado', label: 'Pregrado — Próximamente', disabled: true },
  { value: 'maestria', label: 'Maestría — Próximamente', disabled: true },
  { value: 'diplomado', label: 'Diplomado — Próximamente', disabled: true },
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
        {promptOptions.map((option) => (
          <option key={option.value || 'placeholder'} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </article>
  )
}

export default PromptSelector

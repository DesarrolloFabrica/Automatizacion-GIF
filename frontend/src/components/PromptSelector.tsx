import type { PromptType } from '../types/granules'
import type { CategoryConfig } from '../types/granules'
import { CATEGORY_CONFIGS } from '../data/categories'

interface PromptSelectorProps {
  selectedPrompt: PromptType | ''
  onSelectPrompt: (prompt: PromptType | '') => void
  categories?: CategoryConfig[]
}

function buildPromptOptions(categories: CategoryConfig[]): Array<{ value: PromptType | ''; label: string; disabled: boolean }> {
  return [{ value: '', label: 'Selecciona un tipo de prompt', disabled: false }, ...categories.map((category) => ({
    value: category.key,
    label: category.enabledForPackage ? category.label : `${category.label} — Pendiente de prompt de materiales`,
    disabled: !category.enabledForPackage,
  }))]
}

function PromptSelector({ selectedPrompt, onSelectPrompt, categories = CATEGORY_CONFIGS }: PromptSelectorProps) {
  const promptOptions = buildPromptOptions(categories)
  return (
    <article className="config-choice-card config-choice-card--prompt prompt-console-card">
      <div className="config-choice-top">
        <span className="config-choice-badge">CONFIGURACIÓN</span>
        <span className="config-choice-step">Nivel</span>
      </div>

      <div className="config-choice-content">
        <h2>Categoría académica</h2>
        <p>Selecciona la categoría activa. Maestría queda visible, pero bloqueada hasta tener prompt de materiales.</p>
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
      <div className="prompt-level-pills" aria-label="Niveles académicos disponibles">
        {promptOptions.filter((option) => option.value).map((option) => (
          <span key={option.value} className={option.disabled ? 'is-disabled' : selectedPrompt === option.value ? 'is-active' : ''}>
            {option.label.replace(' — Próximamente', '')}
          </span>
        ))}
      </div>
    </article>
  )
}

export default PromptSelector

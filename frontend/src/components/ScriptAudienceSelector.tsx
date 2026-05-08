import type { ScriptType } from '../types/granules'

interface ScriptAudienceSelectorProps {
  selectedType: ScriptType | ''
  onSelectType: (value: ScriptType | '') => void
}

const scriptTypeOptions: Array<{ value: ScriptType; label: string; description: string }> = [
  {
    value: 'analistas',
    label: 'Analistas',
    description: 'Enfoque para materiales preparados para análisis y desarrollo académico.',
  },
  {
    value: 'presentadoras',
    label: 'Presentadoras',
    description: 'Enfoque para materiales orientados a presentación y comunicación del contenido.',
  },
]

function ScriptAudienceSelector({ selectedType, onSelectType }: ScriptAudienceSelectorProps) {
  return (
    <article className="config-choice-card config-choice-card--script">
      <div className="config-choice-top">
        <span className="config-choice-badge">ENFOQUE</span>
        <span className="config-choice-step">Paso 2</span>
      </div>

      <div className="config-choice-content">
        <h2>Tipo de guion</h2>
        <p>Selecciona el enfoque con el que se prepararán los gránulos.</p>
      </div>

      <select
        className="config-choice-select"
        value={selectedType}
        onChange={(event) => onSelectType(event.target.value as ScriptType | '')}
      >
        <option value="">Selecciona un tipo de guion</option>
        {scriptTypeOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </article>
  )
}

export default ScriptAudienceSelector

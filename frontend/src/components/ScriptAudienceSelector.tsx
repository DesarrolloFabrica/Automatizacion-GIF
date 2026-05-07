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
    <article className="card">
      <h2>Tipo de guion</h2>
      <p className="card-description">Define el estilo de preparación de los materiales.</p>
      <select
        className="select-input"
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
      {selectedType && (
        <p className="muted" style={{ marginTop: '0.75rem' }}>
          {scriptTypeOptions.find((item) => item.value === selectedType)?.description}
        </p>
      )}
    </article>
  )
}

export default ScriptAudienceSelector

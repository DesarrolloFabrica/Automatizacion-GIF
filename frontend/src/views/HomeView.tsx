import FlowCard from '../components/FlowCard'

interface HomeViewProps {
  onNavigate: (view: 'granules' | 'scripts') => void
}

const scriptShortcuts = [
  {
    title: 'Crear solo gránulos',
    description: 'Sube un syllabus y genera G1-G5.',
    status: 'Conectado localmente',
  },
  {
    title: 'Crear TXT/DOCX desde gránulos',
    description: 'Sube gránulos existentes y ejecuta el pipeline local.',
    status: 'Conectado',
  },
  {
    title: 'Crear materiales por gránulo',
    description: 'Genera los 6 recursos editoriales por cada gránulo.',
    status: 'Disponible dentro de paquete local',
  },
]

function HomeView({ onNavigate }: HomeViewProps) {
  return (
    <div className="home-view">
      <div className="home-content">
        <header className="home-hero">
          <span className="home-badge">Plataforma académica</span>
          <h1 className="home-title">Automatización académica inteligente</h1>
          <p className="home-subtitle">Genera paquetes académicos completos o ejecuta scripts individuales según tu necesidad.</p>
          <div className="home-hero-flow" aria-label="Flujo principal de generación">
            <span>Subir syllabus</span>
            <span>IA procesa</span>
            <span>Contenidos</span>
            <span>Actividades</span>
            <span>ZIP final</span>
          </div>
        </header>

        <div className="flow-cards-grid">
          <FlowCard
            icon={
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
                <path d="M14 2v6h6" />
                <path d="M16 13H8" />
                <path d="M16 17H8" />
                <path d="M10 9H8" />
              </svg>
            }
            title="Generar paquete local"
            description="Flujo principal validado: syllabus, gránulos, TXT/DOCX académicos, materiales por gránulo y ZIP final."
            bullets={[
              'Subida de syllabus .docx',
              'Selector de categoría/nivel académico',
              'Fases locales G1-G5, TXT/DOCX y materiales',
              'ZIP institucional descargable',
            ]}
            ctaLabel="Iniciar paquete local"
            statusLabel="DISPONIBLE"
            statusVariant="available"
            onClick={() => onNavigate('granules')}
          />

          <FlowCard
            icon={
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            }
            title="Generar paquete en Drive"
            description="Este flujo creará la misma estructura directamente en Google Drive. Disponible próximamente."
            bullets={[
              'Misma estructura institucional',
              'Carpetas creadas en Google Drive',
              'Sin descarga manual intermedia',
              'Disponible próximamente',
            ]}
            ctaLabel="Próximamente"
            statusLabel="PRÓXIMAMENTE"
            statusVariant="preview"
            onClick={() => undefined}
            disabled
          />
        </div>

        <section className="home-scripts-section">
          <div className="home-section-heading">
            <span className="home-badge">Sección secundaria</span>
            <h2>Ejecutar scripts individuales</h2>
            <p>Accesos rápidos para ejecutar partes del flujo cuando no necesitas el paquete completo.</p>
          </div>
          <div className="home-script-shortcuts">
            {scriptShortcuts.map((item) => (
              <button key={item.title} type="button" className="home-script-shortcut" onClick={() => onNavigate('scripts')}>
                <strong>{item.title}</strong>
                <span>{item.description}</span>
                <small>{item.status}</small>
              </button>
            ))}
          </div>
        </section>

        <div className="capability-chips">
          <span className="cap-chip">Word .docx</span>
          <span className="cap-chip">IA</span>
          <span className="cap-chip">FastAPI</span>
          <span className="cap-chip">Google Drive próximamente</span>
          <span className="cap-chip">Moodle-ready</span>
          <span className="cap-chip">Flujo académico</span>
        </div>

        <footer className="home-footer">
          <p>Automatización académica inteligente — Plataforma de generación de materiales educativos</p>
        </footer>
      </div>
    </div>
  )
}

export default HomeView

import FlowCard from '../components/FlowCard'

interface HomeViewProps {
  onNavigate: (view: 'granules' | 'scripts') => void
}

function HomeView({ onNavigate }: HomeViewProps) {
  return (
    <div className="home-view">
      <div className="home-content">
        <header className="home-hero">
          <span className="home-badge">Automatización académica inteligente</span>
          <h1 className="home-title">Selecciona el flujo de trabajo</h1>
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
            title="Crear gránulos"
            description="Genera documentos académicos estructurados a partir de un syllabus .docx."
            bullets={[
              'Detección automática de contenidos',
              'Prompts por nivel académico',
              'Generación real con Python + IA',
              'Descarga individual o masiva',
            ]}
            ctaLabel="Iniciar creación de gránulos"
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
            title="Crear guiones"
            description="Genera guiones instruccionales a partir de un gránulo académico previamente creado."
            bullets={[
              'Video educativo, podcast, interactivos',
              'Clase guiada estructurada',
              'Basado en gránulo existente',
              'Flujo académico coherente',
            ]}
            ctaLabel="Iniciar creación de guiones"
            statusLabel="VISTA INICIAL PREPARADA"
            statusVariant="preview"
            onClick={() => onNavigate('scripts')}
          />
        </div>

        <div className="capability-chips">
          <span className="cap-chip">Word .docx</span>
          <span className="cap-chip">IA</span>
          <span className="cap-chip">FastAPI</span>
          <span className="cap-chip">Google Drive</span>
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
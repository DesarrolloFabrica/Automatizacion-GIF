import FlowCard from '../components/FlowCard'

interface HomeViewProps {
  onNavigate: (view: 'granules' | 'scripts') => void
}

function HomeView({ onNavigate }: HomeViewProps) {
  return (
    <div className="home-view">
      <div className="home-bg-decorations">
        <div className="bg-gradient-tl" />
        <div className="bg-gradient-br" />
        <div className="bg-grid-pattern" />
      </div>

      <div className="home-content">
        <header className="home-hero">
          <span className="home-badge">Automatización académica inteligente</span>
          <h1 className="home-title">Selecciona el flujo de trabajo</h1>
          <p className="home-subtitle">
            Genera materiales académicos estructurados desde syllabus o gránulos previamente creados.
          </p>
        </header>

        <div className="pipeline-visual">
          <div className="pipeline-step">
            <span className="pipeline-icon">📄</span>
            <span className="pipeline-label">Syllabus</span>
          </div>
          <div className="pipeline-arrow">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14" />
              <path d="M12 5l7 7-7 7" />
            </svg>
          </div>
          <div className="pipeline-step">
            <span className="pipeline-icon">🔬</span>
            <span className="pipeline-label">Gránulos</span>
          </div>
          <div className="pipeline-arrow">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14" />
              <path d="M12 5l7 7-7 7" />
            </svg>
          </div>
          <div className="pipeline-step">
            <span className="pipeline-icon">🎬</span>
            <span className="pipeline-label">Guiones</span>
          </div>
        </div>

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
            statusLabel="Disponible"
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
            statusLabel="Vista inicial preparada"
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

        <section className="home-how-it-works">
          <h2 className="how-title">Cómo funciona</h2>
          <p className="how-subtitle">
            Primero convierte un syllabus en gránulos. Luego convierte cada gránulo en guiones instruccionales.
          </p>
          <div className="how-steps">
            <div className="how-step">
              <div className="how-step-number">1</div>
              <h3 className="how-step-title">Carga</h3>
              <p className="how-step-desc">Sube tu syllabus o gránulo en formato .docx</p>
            </div>
            <div className="how-step">
              <div className="how-step-number">2</div>
              <h3 className="how-step-title">Procesamiento IA</h3>
              <p className="how-step-desc">El sistema analiza la estructura y prepara los prompts</p>
            </div>
            <div className="how-step">
              <div className="how-step-number">3</div>
              <h3 className="how-step-title">Documentos listos</h3>
              <p className="how-step-desc">Descarga los documentos generados listos para usar</p>
            </div>
          </div>
        </section>

        <footer className="home-footer">
          <p>Automatización académica inteligente — Plataforma de generación de materiales educativos</p>
        </footer>
      </div>
    </div>
  )
}

export default HomeView
import { useState } from 'react'
import HomeView from './views/HomeView'
import GranulesView from './views/GranulesView'
import ScriptsView from './views/ScriptsView'

// Controlador simple de vistas mientras no se use router
type CurrentView = 'home' | 'granules' | 'scripts'

function App() {
  const [currentView, setCurrentView] = useState<CurrentView>('home')

  if (currentView === 'granules') {
    return <GranulesView onBack={() => setCurrentView('home')} />
  }

  if (currentView === 'scripts') {
    return <ScriptsView onBack={() => setCurrentView('home')} />
  }

  return <HomeView onNavigate={setCurrentView} />
}

export default App
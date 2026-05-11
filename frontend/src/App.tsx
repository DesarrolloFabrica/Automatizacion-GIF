import { useEffect, useState } from 'react'
import HomeView from './views/HomeView'
import DrivePackageView from './views/DrivePackageView'
import GranulesView from './views/GranulesView'
import ScriptsView from './views/ScriptsView'

// Controlador simple de vistas mientras no se use router
type CurrentView = 'home' | 'granules' | 'package-drive' | 'scripts'

const viewPaths: Record<CurrentView, string> = {
  home: '/',
  granules: '/package-local',
  'package-drive': '/package-drive',
  scripts: '/scripts',
}

const getInitialView = (): CurrentView => {
  if (window.location.pathname === '/package-local') return 'granules'
  if (window.location.pathname === '/package-drive') return 'package-drive'
  if (window.location.pathname === '/scripts') return 'scripts'
  return 'home'
}

function App() {
  const [currentView, setCurrentView] = useState<CurrentView>(getInitialView)

  const navigateTo = (view: CurrentView) => {
    window.history.pushState({}, '', viewPaths[view])
    setCurrentView(view)
  }

  useEffect(() => {
    const handlePopState = () => setCurrentView(getInitialView())
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  if (currentView === 'granules') {
    return <GranulesView onBack={() => navigateTo('home')} />
  }

  if (currentView === 'package-drive') {
    return <DrivePackageView onBack={() => navigateTo('home')} />
  }

  if (currentView === 'scripts') {
    return <ScriptsView onBack={() => navigateTo('home')} />
  }

  return <HomeView onNavigate={navigateTo} />
}

export default App

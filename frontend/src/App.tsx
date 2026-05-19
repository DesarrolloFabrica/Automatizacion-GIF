import { useEffect, useState } from 'react'
import HomeView from './views/HomeView'
import DrivePackageView from './views/DrivePackageView'
import GranulesView from './views/GranulesView'
import ScriptsView from './views/ScriptsView'

type CurrentView = 'home' | 'granules' | 'package-drive' | 'scripts'
type ScriptModule = 'granules' | 'txtdocx' | 'materials'

const viewPaths: Record<CurrentView, string> = {
  home: '/',
  granules: '/package-local',
  'package-drive': '/package-drive',
  scripts: '/scripts-individuales',
}

const SCRIPT_MODULE_PATHS: Record<ScriptModule, string> = {
  granules: '/scripts-individuales/granules',
  txtdocx: '/scripts-individuales/txt-docx',
  materials: '/scripts-individuales/materials',
}

const resolveScriptModuleFromPath = (pathname: string): ScriptModule => {
  if (pathname === '/scripts-individuales/granules') return 'granules'
  if (pathname === '/scripts-individuales/txt-docx') return 'txtdocx'
  if (pathname === '/scripts-individuales/materials') return 'materials'
  const params = new URLSearchParams(window.location.search)
  const script = params.get('script')
  if (script === 'txtdocx') return 'txtdocx'
  if (script === 'materials') return 'materials'
  return 'granules'
}

const getInitialView = (): CurrentView => {
  const path = window.location.pathname
  if (path === '/package-local') return 'granules'
  if (path === '/package-drive') return 'package-drive'
  if (path.startsWith('/scripts-individuales')) return 'scripts'
  if (path === '/scripts') return 'scripts'
  return 'home'
}

const getInitialScriptModule = (): ScriptModule => {
  return resolveScriptModuleFromPath(window.location.pathname)
}

function App() {
  const [currentView, setCurrentView] = useState<CurrentView>(getInitialView)
  const [scriptModule, setScriptModule] = useState<ScriptModule>(getInitialScriptModule)

  const navigateTo = (view: CurrentView, module?: ScriptModule) => {
    const path = viewPaths[view]
    if (view === 'scripts' && module) {
      window.history.pushState({}, '', SCRIPT_MODULE_PATHS[module])
    } else {
      window.history.pushState({}, '', path)
    }
    setCurrentView(view)
    if (module) setScriptModule(module)
  }

  useEffect(() => {
    const handlePopState = () => {
      setCurrentView(getInitialView())
      setScriptModule(getInitialScriptModule())
    }
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
    return <ScriptsView onBack={() => navigateTo('home')} initialMode={scriptModule} onModeChange={(m) => navigateTo('scripts', m)} />
  }

  return <HomeView onNavigate={(view, module) => navigateTo(view, module as ScriptModule | undefined)} />
}

export default App

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { applyTheme, loadTheme } from './shell/theme'
import './styles.css'

// Before React mounts, so there is no flash of the wrong theme.
applyTheme(loadTheme())

const container = document.getElementById('root')
if (!container) throw new Error('no #root element')

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
)

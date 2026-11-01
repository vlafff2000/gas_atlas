import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './desktopDownload'
import './resources.css'
import '@fontsource/pt-sans/cyrillic-400.css'
import '@fontsource/pt-sans/cyrillic-700.css'
import '@fontsource/pt-sans/latin-400.css'
import '@fontsource/pt-sans/latin-700.css'
import './styles.css'
import './datagrid.css'
import './filepicker.css'
import './passport.css'
import './logbutton.css'
import './busybar.css'
import { App } from './App'
import { mountLogButton } from './LogButton'
import { mountBusyBar } from './BusyBar'

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
mountLogButton()
mountBusyBar()

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

// холст ECharts не перерисуется сам, когда шрифт догрузится, поэтому узкий шрифт ждём до первой отрисовки (не дольше 1,5 с)
const narrow = Promise.all(['400', '700'].map(w => document.fonts.load(`${w} 14px 'Atlas Sans Narrow'`))).catch(() => undefined)
Promise.race([narrow, new Promise(r => setTimeout(r, 1500))]).then(() => {
  createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
})
mountLogButton()
mountBusyBar()

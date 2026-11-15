// Формат тепловых карт и полос: та же панель «Формат» и то же хранилище оформления, что у обычных графиков (ChartView).
import { useMemo, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import type { Chart } from './api'
import { applyFormat, chartKey, mergeFormats, type ChartFormat } from './chartFormat'
import { chartFont, formatScope, projectFormats, usePref } from './chartPrefs'
import { fontCss } from './chartTheme'
import { FormatPane, type FormatElement } from './FormatPane'
import { formatDoc, setFormatDoc } from './projectLooks'
import { frameStyle, titleStyle } from './ChartView'

export function useSpecialFormat(given: Chart, module: string | undefined) {
  const store = usePref(projectFormats)
  const baseFont = usePref(chartFont)
  const scope = usePref(formatScope)
  const [open, setOpen] = useState(false)
  const [element, setElement] = useState<FormatElement>('chart')
  const general = useMemo<ChartFormat | undefined>(() => baseFont === 'base' ? undefined : { chart: { font: baseFont } }, [baseFont])
  const chart = useMemo(() => applyFormat(given, mergeFormats(general, { chart: store.theme?.chart, axes: store.theme?.axes },
    module ? store.types?.[module] : undefined, module ? store.charts?.[chartKey(module, given.id)] : undefined)), [given, store, module, general])
  const st = chart.style
  const frame: CSSProperties = { ...frameStyle(st), ...(st?.background ? { background: st.background } : {}), ...(st?.text_color ? { color: st.text_color } : {}),
    ...(st?.font ? { fontFamily: fontCss(st.font) } : {}) }
  const button = (
    <button type="button" className={'icon' + (open ? ' on' : '')} aria-pressed={open} onClick={() => setOpen(v => !v)}
      title="Формат графика: заголовок, шрифты, фон и рамка — как у остальных графиков">
      <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="2.2" /><path d="M8 1.8v1.9M8 12.3v1.9M1.8 8h1.9M12.3 8h1.9M3.6 3.6l1.3 1.3M11.1 11.1l1.3 1.3M3.6 12.4l1.3-1.3M11.1 4.9l1.3-1.3" /></svg>
    </button>
  )
  const pane = open ? createPortal(
    <FormatPane chart={chart} element={element} onElement={setElement} scope={module ? scope : 'project'} onScope={module ? v => formatScope.set(v) : () => {}}
      doc={formatDoc(store, module ? scope : 'project', module ?? '', given.id)}
      onDoc={doc => setFormatDoc(module ? scope : 'project', module ?? '', doc, given.id)} colorOf={() => '#888'} looks={{}} onLooks={() => {}}
      onReplace={d => setFormatDoc(module ? scope : 'project', module ?? '', d, given.id)} onClose={() => setOpen(false)} plain />, document.body) : null
  return { chart, button, pane, frame, title: titleStyle(st), open: () => setOpen(true) }
}

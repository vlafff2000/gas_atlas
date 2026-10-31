// Предпросмотр листа Word: рядом с настройками, на весь экран и в отдельном окне (на второй монитор), масштаб 100 % = лист в натуральную величину.
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { WordPreview } from './api_projects'

/** Пикселей CSS в миллиметре при масштабе 100 % (96 точек на дюйм): лист A4 на экране — 794 × 1123. */
export const PX_PER_MM = 96 / 25.4
const ZOOMS: [string, string][] = [['fit', 'По ширине'], ['0.5', '50 %'], ['0.75', '75 %'], ['1', '100 % (1:1)'], ['1.25', '125 %'], ['1.5', '150 %'], ['2', '200 %']]

interface Props {
  shot: WordPreview | null; busy: boolean; error: string | null; page: number; setPage: (f: (p: number) => number) => void
  doc: number; setDoc: (d: number) => void; per: number
}

/** Лист и панель управления; один и тот же вид показывается в странице, на весь экран и в отдельном окне. */
function Viewer({ shot, busy, error, page, setPage, doc, setDoc, per, zoom, setZoom, extra, onKey }: Props & {
  zoom: string; setZoom: (z: string) => void; extra?: React.ReactNode; onKey?: (root: HTMLElement | null) => void
}) {
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => { onKey?.(root.current) }, [onKey])
  const width = zoom === 'fit' || !shot ? '100%' : `${Math.round(shot.page_mm[0] * PX_PER_MM * Number(zoom))}px`
  return (
    <div className="word-viewer" ref={root}>
      <div className="toolbar">
        {shot && shot.documents.length > 1 && (
          <label className="field"><span className="field-label">Документ</span>
            <select value={doc} onChange={e => { setDoc(Number(e.target.value)); setPage(() => 1) }}>
              {shot.documents.map((d, i) => <option key={d.id} value={i}>{d.label} ({d.charts})</option>)}
            </select>
          </label>
        )}
        <button type="button" className="quiet" disabled={!shot || page <= 1} onClick={() => setPage(p => p - 1)}>← Лист</button>
        <span>{shot ? `Лист ${shot.page} из ${shot.exact ? '' : '≈'}${shot.pages}` : '…'}</span>
        <button type="button" className="quiet" disabled={!shot || page >= shot.pages} onClick={() => setPage(p => p + 1)}>Лист →</button>
        <label className="field inline"><span className="field-label">Масштаб</span>
          <select value={zoom} onChange={e => setZoom(e.target.value)}>{ZOOMS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        {extra}
        {busy && <span className="pulse">Строим лист…</span>}
      </div>
      {error && <div className="note warning" role="alert">{error}</div>}
      {shot && (
        <>
          <div className="word-scroll">
            <img className="word-sheet" style={{ width, maxWidth: zoom === 'fit' ? '100%' : 'none' }} src={shot.png} alt={`Предпросмотр листа ${shot.page}`} draggable={false} />
          </div>
          <p className="muted">Лист {Math.round(shot.page_mm[0])}×{Math.round(shot.page_mm[1])} мм; график {shot.image_mm[0]}×{shot.image_mm[1]} мм
            {per ? `; ${per} на листе` : '; число листов приблизительное — точное решит Word'}.</p>
        </>
      )}
    </div>
  )
}

/** Предпросмотр с кнопками «На весь экран» и «В отдельное окно»: окно живое, обновляется вместе с настройками. */
export function WordViewerPane(props: Props) {
  const [zoom, setZoom] = useState('1')
  const [big, setBig] = useState(false)
  const [popup, setPopup] = useState<{ win: Window; host: HTMLElement } | null>(null)
  const [popupZoom, setPopupZoom] = useState('1')
  const [note, setNote] = useState<string | null>(null)
  const { page, setPage, shot } = props

  // стрелки и Esc: листать листы и закрывать крупный вид
  const keys = (e: KeyboardEvent) => {
    if ((e.target as HTMLElement | null)?.closest?.('input, select, textarea')) return
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') { if (page > 1) setPage(p => p - 1) }
    else if (e.key === 'ArrowRight' || e.key === 'PageDown') { if (shot && page < shot.pages) setPage(p => p + 1) }
    else if (e.key === 'Escape') setBig(false)
  }
  const keysRef = useRef(keys)
  keysRef.current = keys
  useEffect(() => {
    if (!big) return
    const on = (e: KeyboardEvent) => keysRef.current(e)
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [big])
  useEffect(() => {
    if (!popup) return
    const on = (e: KeyboardEvent) => keysRef.current(e)
    popup.win.addEventListener('keydown', on)
    return () => popup.win.removeEventListener('keydown', on)
  }, [popup])
  useEffect(() => () => { popup?.win.close() }, [])      // eslint-disable-line react-hooks/exhaustive-deps

  const openWindow = () => {
    if (popup && !popup.win.closed) { popup.win.focus(); return }
    const win = window.open('', 'atlas-word-preview', 'popup=yes,width=1100,height=1250')
    if (!win) { setNote('Браузер не открыл отдельное окно: разрешите всплывающие окна для этой страницы или используйте «На весь экран».'); setBig(true); return }
    win.document.title = 'Предпросмотр Word'
    document.querySelectorAll('link[rel="stylesheet"], style').forEach(n => win.document.head.appendChild(n.cloneNode(true)))
    for (const a of Array.from(document.documentElement.attributes)) win.document.documentElement.setAttribute(a.name, a.value)
    win.document.body.className = document.body.className
    win.document.body.classList.add('word-popup')
    const host = win.document.createElement('div')
    host.className = 'word-popup-host'
    win.document.body.appendChild(host)
    win.addEventListener('pagehide', () => setPopup(null))
    setPopup({ win, host })
    setNote(null)
  }
  const buttons = (
    <>
      <button type="button" className="quiet" onClick={() => setBig(true)} title="Лист крупно поверх страницы (Esc — закрыть)">На весь экран</button>
      <button type="button" className="quiet" onClick={openWindow} title="Отдельное окно: можно перенести на соседний монитор">В отдельное окно</button>
    </>
  )
  return (
    <>
      {popup && !popup.win.closed ? (
        <>
          <p className="muted">Предпросмотр открыт в отдельном окне и обновляется вместе с настройками.
            {' '}<button type="button" className="quiet small" onClick={() => popup.win.close()}>Вернуть сюда</button></p>
          {createPortal(<Viewer {...props} zoom={popupZoom} setZoom={setPopupZoom} />, popup.host)}
        </>
      ) : <Viewer {...props} zoom={zoom} setZoom={setZoom} extra={buttons} />}
      {note && <div className="note warning" role="status">{note}</div>}
      {big && (
        <div className="word-overlay" role="dialog" aria-label="Предпросмотр Word">
          <Viewer {...props} zoom={zoom} setZoom={setZoom}
            extra={<button type="button" className="primary" onClick={() => setBig(false)}>Закрыть (Esc)</button>} />
        </div>
      )}
    </>
  )
}

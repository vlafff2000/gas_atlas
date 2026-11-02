// Кнопка «Лог» в углу окна: открыть/скачать лог программы и собрать zip для отправки (pxg_core/runlog.py). Общая для трёх приложений.
// Подключение: mountLogButton() в main.tsx.
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { collectReport, trackRequests } from './problemReport'

interface Info { dir: string; files: { name: string; size: number }[]; current: string }
interface Bundle { name: string; path: string; size: number; url: string; error?: string }

function LogButton() {
  const [open, setOpen] = useState(false)
  const [info, setInfo] = useState<Info | null>(null)
  const [bundle, setBundle] = useState<Bundle | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [text, setText] = useState('')
  const [withCharts, setWithCharts] = useState(true)

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (!next) return
    try { setInfo(await (await fetch('/api/log/info')).json()) } catch { setNote('Не удалось узнать, где лежит лог.') }
  }
  const pack = async () => {
    setBusy(true); setNote(''); setBundle(null)
    try {
      const b = (await (await fetch('/api/log/bundle', { method: 'POST' })).json()) as Bundle
      if (b.error) setNote(b.error); else setBundle(b)
    } catch { setNote('Не удалось собрать пакет.') }
    setBusy(false)
  }
  const sendReport = async () => {
    setBusy(true); setNote(''); setBundle(null)
    try {
      const r = await fetch('/api/log/report', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectReport(text, withCharts)) })
      const b = (await r.json()) as Bundle
      if (b.error) setNote(b.error); else setBundle(b)
    } catch { setNote('Не удалось собрать отчёт.') }
    setBusy(false)
  }
  const openFolder = async () => {
    try {
      const r = await (await fetch('/api/log/open-folder', { method: 'POST' })).json()
      setNote(r.error ? r.error + (r.dir ? ' Папка: ' + r.dir : '') : '')
    } catch { setNote('Не удалось открыть папку.') }
  }
  return (
    <div className="pxg-log">
      {open && (
        <div className="pxg-log-pop" role="dialog" aria-label="Лог работы программы">
          <b>Лог работы программы</b>
          <p className="muted">Лог только информирует: что запускали, сколько заняло, где были предупреждения. Содержимое файлов в него не попадает.</p>
          {info && <p className="muted small">Папка: <code>{info.dir}</code></p>}
          <div className="pxg-log-row">
            <a className="btn" href="/api/log/download" download>Скачать лог</a>
            <button type="button" onClick={openFolder}>Открыть папку</button>
            <button type="button" className="primary" onClick={pack} disabled={busy}>{busy ? 'Собираю…' : 'Собрать пакет для отправки'}</button>
          </div>
          <b className="pxg-log-sub">Сообщить о проблеме</b>
          <textarea className="pxg-log-text" rows={3} value={text} onChange={e => setText(e.target.value)}
            placeholder="Что делали и что пошло не так?" />
          <label className="pxg-log-check"><input type="checkbox" checked={withCharts} onChange={e => setWithCharts(e.target.checked)} />
            Приложить графики на экране (настройки и снимок)</label>
          <div className="pxg-log-row">
            <button type="button" className="primary" onClick={sendReport} disabled={busy || !text.trim()}>{busy ? 'Собираю…' : 'Собрать отчёт о проблеме'}</button>
          </div>
          {bundle && <p>Готово: <a href={bundle.url} download>{bundle.name}</a> ({Math.max(1, Math.round(bundle.size / 1024))} КБ).
            Лежит в <code>{bundle.path}</code>. Загрузите этот файл в чат проекта.</p>}
          {note && <p className="pxg-log-note">{note}</p>}
        </div>)}
      <button type="button" className="pxg-log-btn" onClick={toggle} aria-expanded={open} title="Лог работы программы">Лог</button>
    </div>
  )
}

export function mountLogButton() {
  trackRequests()
  const el = document.createElement('div')
  document.body.appendChild(el)
  createRoot(el).render(<LogButton />)
}

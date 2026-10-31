// Шкала выполнения: кружок, название этапа, время и (если расчёт сообщает шаги) полоса с процентами. Общая для приложений ПХГ.
// Следит за всеми запросами к /api/*: если запрос идёт дольше 0,6 с, показывает карточку внизу по центру;
// название и шаги берёт у сервера (GET /api/progress, pxg_core/progress.py). Подключение: mountBusyBar() в main.tsx.
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

interface Task { id: number; label: string; done: number; total: number | null; text: string; elapsed: number }

const SHOW_AFTER_MS = 600
const QUIET = ['/api/progress', '/api/log', '/api/fs', '/api/jobs/', '/api/state']   // опрос состояния и проводник шкалу не показывают
const subs = new Set<() => void>()
const pending = new Map<number, { path: string; started: number }>()
let seq = 0

function patchFetch() {
  const w = window as unknown as { __pxgBusy?: boolean }
  if (w.__pxgBusy) return
  w.__pxgBusy = true
  const orig = window.fetch.bind(window)
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    let path = ''
    try { path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href).pathname } catch { /* не разобрали - не следим */ }
    if (!path.startsWith('/api/') || QUIET.some((p) => path.startsWith(p))) return orig(input, init)
    const id = ++seq
    pending.set(id, { path, started: Date.now() })
    subs.forEach((f) => f())
    return orig(input, init).finally(() => { pending.delete(id); subs.forEach((f) => f()) })
  }
}

function fmt(sec: number) {
  const s = Math.floor(sec)
  return s < 60 ? s + ' с' : Math.floor(s / 60) + ' мин ' + String(s % 60).padStart(2, '0') + ' с'
}

function BusyBar() {
  const [count, setCount] = useState(0)
  const [visible, setVisible] = useState(false)
  const [tasks, setTasks] = useState<Task[]>([])
  const [since, setSince] = useState(0)
  const [, tick] = useState(0)

  useEffect(() => {
    const f = () => {
      setCount(pending.size)
      setSince(pending.size ? Math.min(...[...pending.values()].map((p) => p.started)) : 0)
    }
    subs.add(f)
    return () => { subs.delete(f) }
  }, [])

  useEffect(() => {
    if (!count) { setVisible(false); setTasks([]); return }
    const show = window.setTimeout(() => setVisible(true), Math.max(0, SHOW_AFTER_MS - (Date.now() - since)))
    return () => window.clearTimeout(show)
  }, [count, since])

  useEffect(() => {
    if (!visible) return
    let stop = false
    const poll = async () => {
      try {
        const r = await orig('/api/progress')
        const j = (await r.json()) as { tasks: Task[] }
        if (!stop) setTasks(j.tasks || [])
      } catch { /* сервер занят - покажем кружок и время */ }
    }
    poll()
    const a = window.setInterval(poll, 800)
    const b = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => { stop = true; window.clearInterval(a); window.clearInterval(b) }
  }, [visible])

  if (!visible || !count) return null
  const t = tasks.length ? tasks[tasks.length - 1] : null
  const pct = t && t.total ? Math.min(100, Math.round((100 * t.done) / t.total)) : null
  const label = t ? t.label : 'Выполняется расчёт…'
  return (
    <div className="pxg-busy" role="status" aria-live="polite">
      <span className="pxg-busy-spin" aria-hidden="true" />
      <div className="pxg-busy-body">
        <div className="pxg-busy-row">
          <b>{label}</b>
          <span className="pxg-busy-time">{fmt(t ? t.elapsed : (Date.now() - since) / 1000)}</span>
        </div>
        <div className={'pxg-busy-bar' + (pct === null ? ' indet' : '')}><i style={pct === null ? undefined : { width: pct + '%' }} /></div>
        <div className="pxg-busy-sub">
          {t && t.total ? `${t.done} из ${t.total}${t.text ? ' · ' + t.text : ''} · ${pct}%` : (t && t.text) || 'Идёт расчёт, дождитесь результата'}
          {tasks.length > 1 ? ` · ещё задач: ${tasks.length - 1}` : ''}
        </div>
      </div>
    </div>
  )
}

const orig = (input: RequestInfo | URL) => (window as unknown as { __pxgFetch?: typeof fetch }).__pxgFetch!(input)

export function mountBusyBar() {
  ;(window as unknown as { __pxgFetch: typeof fetch }).__pxgFetch = window.fetch.bind(window)
  patchFetch()
  const el = document.createElement('div')
  document.body.appendChild(el)
  createRoot(el).render(<BusyBar />)
}

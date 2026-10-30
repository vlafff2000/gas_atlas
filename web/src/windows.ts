import { useEffect, useRef } from 'react'
import { pref } from './chartPrefs'

/** Связь окон: выбранная скважина, сезон и окно дат совпадают в обоих окнах (BroadcastChannel; оба окна открыты с одного сервера). */
export const linkWindows = pref<boolean>('atlas.linkWindows', true)

const CHANNEL = 'atlas.windows'
let chan: BroadcastChannel | null = null
try { chan = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel(CHANNEL) : null } catch { chan = null }

/** Значение живёт в обоих окнах: локальное изменение уходит в другое окно, пришедшее — применяется без эха.
 *  Новое окно при открытии просит текущие значения (hello), а своё начальное значение не рассылает. */
export function useShared<T>(name: string, value: T, apply: (v: T) => void) {
  const last = useRef(JSON.stringify(value))
  const cur = useRef(value)
  cur.current = value
  const applyRef = useRef(apply)
  applyRef.current = apply
  useEffect(() => {
    if (!chan) return
    const ch = chan
    const onMsg = (e: MessageEvent) => {
      const m = e.data as { name?: string; value?: T; hello?: boolean } | null
      if (!m || m.name !== name || !linkWindows.get()) return
      if (m.hello) { last.current = JSON.stringify(cur.current); ch.postMessage({ name, value: cur.current }); return }
      const raw = JSON.stringify(m.value)
      if (raw === last.current) return
      last.current = raw
      applyRef.current(m.value as T)
    }
    ch.addEventListener('message', onMsg)
    ch.postMessage({ name, hello: true })
    return () => ch.removeEventListener('message', onMsg)
  }, [name])
  useEffect(() => {
    if (!chan || !linkWindows.get()) return
    const raw = JSON.stringify(value)
    if (raw === last.current) return
    last.current = raw
    chan.postMessage({ name, value })
  }, [name, value])
}

/** Открыть второе окно: сервер откроет окно приложения; если нечем (сервер без окна), — окно браузера. */
export async function openSecondWindow(page: string): Promise<void> {
  const hash = '/' + page
  try {
    const r = await fetch('/api/second-window', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ hash }) })
    if (r.ok && (await r.json()).opened) return
  } catch { /* сервер недоступен: пробуем окно браузера */ }
  window.open(location.pathname + '#' + hash, 'pxg-window-2', 'popup=yes,width=1280,height=860')
}

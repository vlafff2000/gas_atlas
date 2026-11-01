import { useEffect, useState } from 'react'

type Size = { bytes: number; full: boolean } | null
type Resources = {
  ram: { used: number | null; total: number | null }
  project: Size
  all: Size
  cpu: { busy: number; threads: number; workers: number | null }
}

/** Байты по-русски: 1,5 ГБ, 320 МБ. */
export function formatBytes(n: number): string {
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']
  let v = n, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return (i < 2 ? Math.round(v) : v.toFixed(1).replace('.', ',')) + ' ' + units[i]
}

const sizeText = (s: Size) => s ? (s.full ? '' : '≥ ') + formatBytes(s.bytes) : '…'

/** Плашка внизу левой панели: ОЗУ программы, размер проекта и всех проектов, занятые потоки процессора.
 *  Общая для всех программ; адрес по умолчанию /api/resources. Обновляется раз в 10 секунд, пока вкладка видна. */
export function ResourceBadge({ url = '/api/resources' }: { url?: string }) {
  const [r, setR] = useState<Resources | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => {
      if (document.hidden) return
      fetch(url).then(x => x.ok ? x.json() : null).then(j => { if (alive && j) setR(j) }).catch(() => undefined)
    }
    load()
    const t = window.setInterval(load, 10000)
    return () => { alive = false; window.clearInterval(t) }
  }, [url])
  if (!r) return null
  const ram = r.ram.used == null ? '—' : formatBytes(r.ram.used) + (r.ram.total ? ' из ' + formatBytes(r.ram.total) : '')
  const busy = r.cpu.busy.toFixed(1).replace('.', ',')
  return (
    <dl className="resource-badge side-label" aria-label="Ресурсы компьютера">
      <div title="Память, занятая программой и её расчётными процессами"><dt>ОЗУ</dt><dd>{ram}</dd></div>
      <div title="Размер файлов открытого проекта"><dt>Проект</dt><dd>{sizeText(r.project)}</dd></div>
      {r.all && <div title="Размер всех проектов вместе"><dt>Все проекты</dt><dd>{sizeText(r.all)}</dd></div>}
      <div title={'Занято потоков процессора из ' + r.cpu.threads + (r.cpu.workers ? '; расчётных процессов до ' + r.cpu.workers : '')}>
        <dt>Потоки ЦП</dt><dd>{busy} из {r.cpu.threads}</dd></div>
    </dl>
  )
}

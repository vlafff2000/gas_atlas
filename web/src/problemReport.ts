// Сбор сведений для «Сообщить о проблеме»: последние запросы к ядру (без тел), настройки и снимки видимых графиков.
import * as echarts from 'echarts'

export interface RequestNote { time: string; method: string; path: string; status: number | string; ms: number }
const recent: RequestNote[] = []
const LIMIT = 40

/** Один раз оборачивает fetch: помнит последние запросы (метод, адрес, статус, время). Тела запросов не сохраняются. */
export function trackRequests() {
  const w = window as unknown as { __pxgTracked?: boolean }
  if (w.__pxgTracked) return
  w.__pxgTracked = true
  const original = window.fetch.bind(window)
  window.fetch = async (input, init) => {
    const started = performance.now()
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const method = (init?.method ?? (typeof input === 'object' && 'method' in input ? input.method : 'GET')).toUpperCase()
    const note = (status: number | string) => {
      if (url.startsWith('/api/log') || url.startsWith('/api/progress')) return
      recent.push({ time: new Date().toISOString(), method, path: url.split('?')[0], status, ms: Math.round(performance.now() - started) })
      if (recent.length > LIMIT) recent.shift()
    }
    try {
      const r = await original(input, init)
      note(r.status)
      return r
    } catch (e) {
      note((e as Error).name === 'AbortError' ? 'отмена' : 'нет связи')
      throw e
    }
  }
}

export interface ChartSnapshot { title: string; option: unknown; png: string }

/** Все графики ECharts на экране: настройки (option) и снимок. */
export function collectCharts(): ChartSnapshot[] {
  const out: ChartSnapshot[] = []
  document.querySelectorAll<HTMLElement>('[_echarts_instance_]').forEach((el, i) => {
    const chart = echarts.getInstanceByDom(el)
    if (!chart || chart.isDisposed()) return
    const opt = chart.getOption() as { title?: { text?: string }[] }
    let png = ''
    try { png = chart.getDataURL({ type: 'png', pixelRatio: 1, backgroundColor: '#fff' }) } catch { /* график не отдал снимок */ }
    out.push({ title: opt.title?.[0]?.text ?? `График ${i + 1}`, option: opt, png })
  })
  return out
}

export function collectReport(description: string, withCharts: boolean) {
  return {
    description,
    page: location.pathname + location.hash,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    requests: [...recent],
    charts: withCharts ? collectCharts() : [],
  }
}

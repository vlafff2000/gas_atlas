import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, BoxplotChart, LineChart, ScatterChart } from 'echarts/charts'
import { AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, ToolboxComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { Cell, Chart, Series } from './api'
import { axisTitle, escapeHtml, formatDate, formatNumber } from './format'

echarts.use([BarChart, BoxplotChart, LineChart, ScatterChart, GridComponent, LegendComponent, ToolboxComponent, TooltipComponent,
  DataZoomComponent, AxisPointerComponent, CanvasRenderer])

// Палитра 5.8 (app/core/config.py COLORS): цвета исследований остаются привычными.
export const PALETTE = ['#dc3545', '#2563eb', '#169b62', '#ed8b23', '#9955cc', '#149ba5', '#bd548d', '#8c7542']
const SYMBOL = { circle: 'circle', square: 'rect', diamond: 'diamond', triangle: 'triangle' } as const
const DASH: Record<string, string | number[]> = {
  solid: 'solid', dash: 'dashed', dot: 'dotted', dashdot: [8, 3, 2, 3], longdash: [12, 4],
}
const INK = '#1b2a31', MUTED = '#5f7178', LINE = '#dbe3e5'

/** Подпись деления на оси времени: ММ.ГГГГ, как в выгрузке графиков. */
function dateTick(value: number) {
  const d = new Date(value)
  return `${String(d.getUTCMonth() + 1).padStart(2, '0')}.${d.getUTCFullYear()}`
}

interface Props {
  chart: Chart
  excludeMode: boolean
  onExclude: (dataset: string, id: string) => void
  onDownload: (format: string, dpi: number) => Promise<void>
}

function toOption(chart: Chart, excludeMode: boolean): echarts.EChartsCoreOption {
  const key = (s: Series) => s.group || s.name
  const groups = [...new Set(chart.series.map(key))]
  const color = (s: Series) => s.color || PALETTE[groups.indexOf(key(s)) % PALETTE.length]
  const tips = new Map<string, string[]>()
  for (const s of chart.series) {
    if (!s.tooltip) continue
    const text = s.kind === 'line' ? `${s.name}: ${s.tooltip}` : s.tooltip
    tips.set(key(s), [...(tips.get(key(s)) ?? []), text])
  }
  const legend = groups.filter(g => chart.series.some(s => key(s) === g && s.legend))

  const axis = (a: Chart['x'], position: 'x' | 'y') => ({
    type: a.scale, inverse: a.inverse, scale: !a.from_zero,
    min: a.scale === 'category' ? undefined : a.minimum ?? (a.from_zero ? 0 : undefined),
    max: a.scale === 'category' ? undefined : a.maximum ?? undefined,
    interval: a.step && a.scale === 'value' ? a.step : undefined,
    data: a.scale === 'category' ? a.categories ?? [] : undefined,
    name: axisTitle(a.label, a.unit), nameLocation: 'middle', nameGap: position === 'x' ? 30 : 56,
    nameTextStyle: { color: MUTED, fontSize: 12 },
    axisLine: { lineStyle: { color: LINE } }, axisTick: { lineStyle: { color: LINE } },
    axisLabel: {
      color: MUTED, hideOverlap: true,
      ...(a.scale === 'time' ? { formatter: (v: number) => dateTick(v), showMinLabel: false, showMaxLabel: false }
        : a.scale === 'category' ? {} : { formatter: (v: number) => formatNumber(v) }),
    },
    splitLine: { lineStyle: { color: '#eef2f3' } },
    axisPointer: {
      show: chart.crosshair, type: 'line', triggerTooltip: false, snap: false,
      lineStyle: { color: '#637782', type: 'dotted' },
      label: { backgroundColor: '#637782', formatter: (p: { value: number }) => formatNumber(p.value) },
    },
  })

  return {
    animation: false,
    textStyle: { fontFamily: 'PT Sans, sans-serif', color: INK },
    grid: { left: 72, right: 24, top: 40, bottom: 92 },
    xAxis: axis(chart.x, 'x'),
    yAxis: axis(chart.y, 'y'),
    legend: { bottom: 0, left: 0, type: 'scroll', data: legend, textStyle: { color: INK }, itemWidth: 14, itemHeight: 10 },
    tooltip: {
      trigger: 'item', borderColor: LINE, textStyle: { color: INK, fontSize: 12 }, confine: true,
      formatter: (p: { seriesName: string; seriesType: string; name: string; data: [Cell, Cell, string, string] }) => {
        if (p.seriesType === 'boxplot') {
          const names = ['Нижний ус', 'Q1', 'Медиана', 'Q3', 'Верхний ус']
          return [`<b>${escapeHtml(p.seriesName)}</b>`, escapeHtml(p.name),
            ...(p.data as unknown as number[]).slice(-5).map((v, i) => `${names[i]}: ${formatNumber(v)}`)].join('<br>')
        }
        const [x, y, id, label] = p.data
        const at = (a: Chart['x'], v: Cell) =>
          v === null ? '' : a.scale === 'time' && typeof v === 'string' ? formatDate(v)
            : a.scale === 'category' || typeof v !== 'number' ? String(v) : formatNumber(v)
        return [`<b>${escapeHtml(p.seriesName)}</b>`,
          `${escapeHtml(axisTitle(chart.x.label, chart.x.unit))}: ${escapeHtml(at(chart.x, x))}`,
          `${escapeHtml(axisTitle(chart.y.label, chart.y.unit))}: ${escapeHtml(at(chart.y, y))}`,
          ...(label ? label.split(' · ').map(escapeHtml) : []),
          ...(tips.get(p.seriesName) ?? []).map(escapeHtml),
          ...(excludeMode && id ? ['<i>Щелчок исключит точку</i>'] : [])].join('<br>')
      },
    },
    toolbox: {
      right: 8, top: 0, itemSize: 14, iconStyle: { borderColor: MUTED },
      feature: {
        // filterMode 'none': линия, выходящая за границы оси, обрезается, а не пропадает целиком
        dataZoom: { filterMode: 'none', title: { zoom: 'Увеличить область', back: 'Назад' } },
        restore: { title: 'Сбросить масштаб' },
      },
    },
    series: chart.series.map(s => {
      if (s.kind === 'box') {     // y — пять чисел на категорию оси X; пустая категория — без ящика
        const empty = ['-', '-', '-', '-', '-']
        return { name: key(s), type: 'boxplot', color: color(s), data: s.y.map(v => Array.isArray(v) ? v : empty),
          itemStyle: { color: color(s) + '55', borderColor: color(s) }, boxWidth: [6, 40] }
      }
      const data = s.x.map((x, j) => [x, s.y[j], s.ids?.[j] ?? '', s.labels?.[j] ?? ''])
        .filter(([x, y]) => s.kind !== 'points' || (x !== null && y !== null))
      const common = { name: key(s), data, color: color(s) }
      if (s.kind === 'bar') {
        return { ...common, type: 'bar', barMaxWidth: 48, itemStyle: { color: color(s) }, emphasis: { focus: 'series' } }
      }
      const selectable = excludeMode && !!s.ids
      if (s.kind === 'line') {
        const hoverable = !!s.labels || !!s.ids      // линия с подписями точек: подсказка при наведении
        return { ...common, type: 'line', z: 1, silent: !hoverable, connectNulls: false,
          showSymbol: hoverable, symbol: 'circle', symbolSize: selectable ? 7 : 6,
          itemStyle: { color: color(s), opacity: selectable ? 1 : 0 },
          emphasis: hoverable ? { scale: 1.6, itemStyle: { opacity: 1, borderColor: '#fff', borderWidth: 1 } } : undefined,
          cursor: selectable ? 'crosshair' : 'default',
          lineStyle: { width: s.width || 1.6, type: DASH[s.dash || (s.dashed ? 'dash' : 'solid')] } }
      }
      return { ...common, type: 'scatter', z: s.hollow ? 3 : 2, symbol: SYMBOL[s.symbol], symbolSize: s.hollow ? 10 : 8,
        large: data.length > 2000, cursor: selectable ? 'crosshair' : 'default',
        itemStyle: s.hollow
          ? { color: 'rgba(255,255,255,0)', borderColor: color(s), borderWidth: 2 }
          : { borderColor: '#fff', borderWidth: 1 },
        emphasis: selectable ? { scale: 1.8, itemStyle: { borderColor: INK, borderWidth: 2 } } : undefined }
    }),
  }
}

export function ChartView({ chart, excludeMode, onExclude, onDownload }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const instance = useRef<echarts.ECharts | null>(null)
  const currentChart = useRef<Chart | null>(null)
  const handlers = useRef({ excludeMode, onExclude })
  handlers.current = { excludeMode, onExclude }

  useEffect(() => {
    const el = box.current!
    const ch = echarts.init(el, undefined, { renderer: 'canvas' })
    instance.current = ch
    ;(el as unknown as { __echart?: echarts.ECharts }).__echart = ch     // для отладки и проверок в браузере
    ch.on('click', (p: { seriesIndex?: number; data?: unknown }) => {
      const { excludeMode, onExclude } = handlers.current
      const series = p.seriesIndex === undefined ? undefined : currentChart.current?.series[p.seriesIndex]
      const id = Array.isArray(p.data) ? (p.data[2] as string | undefined) : undefined
      if (excludeMode && series?.dataset && id) onExclude(series.dataset, id)
    })
    const observer = new ResizeObserver(() => ch.resize())
    observer.observe(el)
    return () => { observer.disconnect(); ch.dispose(); instance.current = null }
  }, [])

  useEffect(() => {
    currentChart.current = chart
    instance.current?.setOption(toOption(chart, excludeMode), { notMerge: true })
  }, [chart, excludeMode])

  return (
    <figure className={'chart' + (excludeMode ? ' exclude-mode' : '')}>
      <figcaption>
        <span>{chart.title}</span>
        <DownloadMenu onDownload={onDownload} />
      </figcaption>
      <div ref={box} className="chart-canvas" role="img" aria-label={chart.title} />
    </figure>
  )
}

function DownloadMenu({ onDownload }: { onDownload: (format: string, dpi: number) => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [format, setFormat] = useState('svg')
  const [dpi, setDpi] = useState(300)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const go = async () => {
    setBusy(true); setFailure('')
    try { await onDownload(format, dpi); setOpen(false) } catch (e) { setFailure((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="download" ref={root}>
      <button type="button" className="quiet small" aria-expanded={open} onClick={() => setOpen(o => !o)}>Скачать</button>
      {open && (
        <div className="popover right">
          <label className="inline-field">Формат
            <select value={format} onChange={e => setFormat(e.target.value)}>
              <option value="svg">SVG</option><option value="pdf">PDF</option><option value="png">PNG</option>
            </select>
          </label>
          <label className="inline-field">DPI
            <select value={dpi} onChange={e => setDpi(Number(e.target.value))}>
              {[300, 600, 1200].map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <button type="button" className="primary" disabled={busy} onClick={go}>{busy ? 'Готовлю файл…' : `Скачать ${format.toUpperCase()}`}</button>
          {failure && <p className="field-error">{failure}</p>}
        </div>
      )}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, BoxplotChart, LineChart, ScatterChart } from 'echarts/charts'
import { AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, ToolboxComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { Axis, Chart, Series } from './api'
import { axisTitle, escapeHtml, formatDate, formatNumber } from './format'
import { alpha, chartTokens, FONT, PALETTE, seriesColor, type ChartTokens } from './chartTheme'
import { buildTracks, decimalsFor, hover, toNumber, type Hover, type HoverMode, type Track, type View } from './chartHover'
import { setHoverMode, useHoverMode } from './chartPrefs'
import './chart.css'

echarts.use([BarChart, BoxplotChart, LineChart, ScatterChart, GridComponent, LegendComponent, ToolboxComponent, TooltipComponent,
  DataZoomComponent, AxisPointerComponent, CanvasRenderer])

export { PALETTE }
const SYMBOL = { circle: 'circle', square: 'rect', diamond: 'diamond', triangle: 'triangle' } as const
const DASH: Record<string, string | number[]> = {
  solid: 'solid', dash: [6, 4], dot: [1.5, 3.5], dashdot: [8, 3, 2, 3], longdash: [12, 4],
}
const LARGE = 5000          // точек в серии: дальше облако рисуется пакетно, линия — с прореживанием LTTB
const BLUR_LIMIT = 200_000  // при наведении остальные кривые приглушаются, пока точек на графике не больше этого

interface Props {
  chart: Chart
  excludeMode: boolean
  onExclude: (dataset: string, id: string) => void
  onDownload: (format: string, dpi: number) => Promise<void>
}

const key = (s: Series) => s.group || s.name
/** Отметки замеров на линии: заданы модулем, нужны для исключения кликом или включён вид «Замеры». */
const hasMarkers = (s: Series, excludeMode: boolean, mode: HoverMode) =>
  s.markers || (excludeMode && !!s.ids) || (mode === 'facts' && s.x.length <= LARGE)
const dashOf = (s: Series) => DASH[s.dash || (s.dashed ? 'dash' : 'solid')]

function colorOf(chart: Chart) {
  const groups = [...new Set(chart.series.map(key))]
  return (s: Series) => s.color ? seriesColor(s.color) : PALETTE[groups.indexOf(key(s)) % PALETTE.length]
}

/** Подпись значения оси: время — дата, остальное — число с точностью по размаху оси. */
function formatter(a: Axis, span: number) {
  const decimals = decimalsFor(span)
  return (v: number | string | null) => {
    if (v === null || v === '') return ''
    if (a.scale === 'time') {
      const ms = typeof v === 'number' ? v : toNumber(v, 'time')
      if (!Number.isFinite(ms)) return String(v)
      const iso = new Date(ms).toISOString()
      return formatDate(span < 3 * 86400e3 ? iso.slice(0, 16) : iso.slice(0, 10))
    }
    if (typeof v !== 'number') return String(v)
    return formatNumber(v, Math.abs(v) >= 1e4 ? Math.min(decimals, 1) : decimals).replace(/(,\d*?)0+$/, '$1').replace(/,$/, '')
  }
}

function toOption(chart: Chart, excludeMode: boolean, tk: ChartTokens, custom: boolean, mode: HoverMode): echarts.EChartsCoreOption {
  const color = colorOf(chart)
  const tips = new Map<string, string[]>()
  for (const s of chart.series) {
    if (!s.tooltip) continue
    tips.set(key(s), [...(tips.get(key(s)) ?? []), s.kind === 'line' ? `${s.name}: ${s.tooltip}` : s.tooltip])
  }
  const legend = [...new Set(chart.series.map(key))].filter(g => chart.series.some(s => key(s) === g && s.legend))
  const total = chart.series.reduce((n, s) => n + s.x.length, 0)
  const time = chart.x.scale === 'time'

  const axis = (a: Axis, position: 'x' | 'y' | 'y2') => {
    const y = position !== 'x'
    return {
      type: a.scale, inverse: a.inverse, scale: !a.from_zero,
      min: a.scale === 'category' ? undefined : a.minimum ?? (a.from_zero ? 0 : undefined),
      max: a.scale === 'category' ? undefined : a.maximum ?? undefined,
      interval: a.step && a.scale === 'value' ? a.step : undefined,
      data: a.scale === 'category' ? a.categories ?? [] : undefined,
      name: axisTitle(a.label, a.unit),
      // подпись шкалы Y — горизонтально над осью, читается без наклона головы
      nameLocation: y ? (a.inverse ? 'start' : 'end') : 'middle', nameGap: y ? 14 : 30,
      nameTextStyle: y
        ? { color: tk.muted, fontSize: 12, align: position === 'y2' ? 'right' : 'left', padding: position === 'y2' ? [0, -8, 0, 0] : [0, 0, 0, -44] }
        : { color: tk.muted, fontSize: 12 },
      axisLine: { show: !y, lineStyle: { color: tk.axis } },
      axisTick: { show: false },
      axisLabel: {
        color: tk.muted, fontSize: 11, hideOverlap: true, margin: 10,
        ...(a.scale === 'time'
          ? { formatter: { year: '{yyyy}', month: '{MM}.{yyyy}', day: '{dd}.{MM}', hour: '{HH}:{mm}', minute: '{HH}:{mm}', second: '{HH}:{mm}:{ss}', none: '{dd}.{MM}.{yyyy}' } }
          : a.scale === 'category' ? {} : { formatter: (v: number) => formatNumber(v) }),
      },
      splitLine: { show: position !== 'y2' && (y || a.scale !== 'category'), lineStyle: { color: tk.grid, width: 1 } },
    }
  }

  const category = chart.x.scale === 'category'
  let lo = 0, hi = 0
  if (category) for (const s of chart.series) for (const v of s.y) if (typeof v === 'number') { lo = Math.min(lo, v); hi = Math.max(hi, v) }
  const barFmt = formatter(chart.y, hi - lo || 1)
  const hasBox = chart.series.some(s => s.kind === 'box')
  return {
    animation: false,
    useUTC: true,
    textStyle: { fontFamily: FONT, color: tk.ink },
    grid: { left: 64, right: chart.y2 ? 64 : 20, top: 34, bottom: legend.length ? 76 : 44 },
    xAxis: axis(chart.x, 'x'),
    yAxis: chart.y2 ? [axis(chart.y, 'y'), axis(chart.y2, 'y2')] : axis(chart.y, 'y'),
    legend: {
      show: legend.length > 1 || chart.series.length > 1, bottom: 2, left: 4, right: 4, type: 'scroll',
      // у линии без отметок в легенде только штрих её стиля, без кружка
      data: legend.map(name => {
        const s = chart.series.find(o => key(o) === name && o.legend)!
        const plain = s.kind === 'line' && !hasMarkers(s, excludeMode, mode)
        return plain ? { name, itemStyle: { opacity: 0 } } : { name }
      }),
      textStyle: { color: tk.ink, fontSize: 12 }, itemWidth: 18, itemHeight: 10, itemGap: 18,
      pageIconColor: tk.muted, pageIconInactiveColor: tk.grid, pageTextStyle: { color: tk.muted },
      inactiveColor: tk.axis,
    },
    tooltip: custom ? { show: false } : {
      trigger: hasBox ? 'item' : 'axis', confine: true, className: 'atlas-tip', padding: 0, borderWidth: 0,
      backgroundColor: 'transparent', extraCssText: 'box-shadow:none;',
      axisPointer: { type: 'shadow', shadowStyle: { color: alpha(tk.ink, 0.05) } },
      formatter: (raw: unknown) => {
        const list = (Array.isArray(raw) ? raw : [raw]) as { seriesName: string; seriesIndex: number; seriesType: string; name: string; data: unknown; color: string }[]
        if (!list.length) return ''
        if (list[0].seriesType === 'boxplot') {
          const p = list[0], names = ['Верхний ус', 'Q3', 'Медиана', 'Q1', 'Нижний ус']
          const v = (p.data as number[]).slice(-5).reverse()
          return tipHtml(escapeHtml(p.name), [{ name: p.seriesName, color: p.color, dash: false, value: '' }],
            names.map((n, i) => `${n}: <b>${formatNumber(v[i])}</b>`))
        }
        const yAxis = (i: number) => chart.series[i]?.axis === 'y2' && chart.y2 ? chart.y2 : chart.y
        return tipHtml(escapeHtml(list[0].name), list.filter(p => Array.isArray(p.data) && p.data[1] !== null).map(p => ({
          name: p.seriesName, color: p.color, dash: false,
          value: '<b>' + barFmt((p.data as number[])[1]) + '</b>' + (yAxis(p.seriesIndex).unit ? ' ' + yAxis(p.seriesIndex).unit : ''),
        })), [])
      },
    },
    dataZoom: category ? [] : [
      // Ctrl + колесо — масштаб, перетаскивание — сдвиг; страница при этом прокручивается колесом как обычно
      { type: 'inside', xAxisIndex: 0, filterMode: 'none', zoomOnMouseWheel: 'ctrl', moveOnMouseWheel: false, moveOnMouseMove: true, preventDefaultMouseMove: false },
      ...(time ? [] : [{ type: 'inside', yAxisIndex: chart.y2 ? [0, 1] : 0, filterMode: 'none', zoomOnMouseWheel: 'ctrl', moveOnMouseWheel: false, moveOnMouseMove: true, preventDefaultMouseMove: false }]),
    ],
    // кнопки масштаба — в заголовке графика (ChartView), панель ECharts скрыта и даёт только выделение области
    toolbox: {
      show: false,
      feature: {
        // filterMode 'none': линия, выходящая за границы оси, обрезается, а не пропадает целиком
        dataZoom: { filterMode: 'none', title: { zoom: 'Увеличить область', back: 'Назад' } },
        restore: { title: 'Сбросить масштаб' },
      },
    },
    series: chart.series.map(s => {
      const c = color(s)
      const blur = total <= BLUR_LIMIT
      const emphasis = { focus: blur ? 'series' : 'none', blurScope: 'coordinateSystem' }
      const blurred = { lineStyle: { opacity: 0.25 }, itemStyle: { opacity: 0.25 } }
      if (s.kind === 'box') {     // y — пять чисел на категорию оси X; пустая категория — без ящика
        const empty = ['-', '-', '-', '-', '-']
        return { name: key(s), type: 'boxplot', color: c, data: s.y.map(v => Array.isArray(v) ? v : empty),
          itemStyle: { color: alpha(c, 0.16), borderColor: c, borderWidth: 1.5 }, boxWidth: [6, 36],
          emphasis: { itemStyle: { color: alpha(c, 0.3), borderWidth: 2 } } }
      }
      const xs = time ? s.x.map(v => { const n = toNumber(v, 'time'); return Number.isFinite(n) ? n : null }) : s.x
      const rich = !!(s.ids || s.labels)
      const data = rich
        ? xs.map((x, j) => [x, s.y[j], s.ids?.[j] ?? '', s.labels?.[j] ?? ''])
        : xs.map((x, j) => [x, s.y[j]])
      const rows = s.kind === 'points' ? data.filter(([x, y]) => x !== null && y !== null) : data
      const common = { name: key(s), data: rows, color: c, yAxisIndex: s.axis === 'y2' && chart.y2 ? 1 : 0,
        silent: custom, emphasis, blur: blurred }
      if (s.kind === 'bar') {
        return { ...common, type: 'bar', barMaxWidth: 24, barGap: '12%', itemStyle: { color: c, borderRadius: [4, 4, 0, 0] },
          emphasis: { focus: 'none', itemStyle: { color: c } } }
      }
      const width = s.width || 2
      if (s.kind === 'line') {
        // в режиме «Только замеры» на линиях видны сами замеры (перекрывающиеся ECharts скрывает)
        const markers = hasMarkers(s, excludeMode, mode)
        return { ...common, type: 'line', z: s.markers ? 3 : 2, connectNulls: false,
          sampling: rows.length > LARGE && !markers ? 'lttb' : undefined,
          showSymbol: markers, showAllSymbol: 'auto', symbol: markers ? SYMBOL[s.symbol] : 'none', symbolSize: rows.length > 150 ? 4 : s.markers ? 7 : 5,
          itemStyle: s.hollow ? { color: tk.surface, borderColor: c, borderWidth: 1.8 } : { color: c, borderColor: tk.surface, borderWidth: 1.5 },
          lineStyle: { color: c, width, type: dashOf(s), cap: 'round', join: 'round' },
          emphasis: { ...emphasis, lineStyle: { width: width + 1 } } }
      }
      const big = rows.length > LARGE
      return { ...common, type: 'scatter', z: s.hollow ? 4 : 3, symbol: SYMBOL[s.symbol], symbolSize: big ? 5 : s.hollow ? 10 : 9,
        large: big, largeThreshold: LARGE, progressive: 0,
        itemStyle: s.hollow
          ? { color: 'rgba(255,255,255,0)', borderColor: c, borderWidth: 1.8 }
          : big ? { color: alpha(c, 0.55) } : { color: c, borderColor: tk.surface, borderWidth: 1.5 } }
    }),
  }
}

interface TipRow { name: string; color: string; dash: boolean; value: string; strong?: boolean; symbol?: string }

function keyHtml(r: TipRow) {
  return r.symbol
    ? `<i class="tip-dot" style="background:${r.color}"></i>`
    : `<i class="tip-key${r.dash ? ' dashed' : ''}" style="--c:${r.color}"></i>`
}

/** Карточка подсказки: значение крупно, название серии тише (подписи из данных экранируются). */
function tipHtml(head: string, rows: TipRow[], extra: string[], foot = '') {
  return `<div class="tip-card">${head ? `<div class="tip-head">${head}</div>` : ''}`
    + rows.map(r => `<div class="tip-row${r.strong ? ' strong' : ''}">${keyHtml(r)}<span class="tip-name">${escapeHtml(r.name)}</span>`
      + `<span class="tip-value">${r.value}</span></div>`).join('')
    + (extra.length ? `<div class="tip-extra">${extra.join('<br>')}</div>` : '')
    + (foot ? `<div class="tip-foot">${foot}</div>` : '') + '</div>'
}

const MAX_ROWS = 10

export function ChartView({ chart, excludeMode, onExclude, onDownload }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const tip = useRef<HTMLDivElement>(null)
  const instance = useRef<echarts.ECharts | null>(null)
  const state = useRef({
    chart, excludeMode, onExclude, tracks: [] as Track[], selected: {} as Record<string, boolean>,
    current: null as Hover | null, focused: -1, mouse: null as [number, number] | null, down: null as [number, number] | null,
    mode: 'smooth' as HoverMode, map: { x: (v: number) => v, y: [(v: number) => v, (v: number) => v] as [(v: number) => number, (v: number) => number] }, frame: 0, tokens: null as ChartTokens | null, spans: { x: 1, y: 1, y2: 1 }, blur: true, draw: (() => {}) as () => void,
  })
  const mode = useHoverMode()
  const [boxZoom, setBoxZoom] = useState(false)
  const boxRef = useRef(false)
  boxRef.current = boxZoom
  const toggleBoxZoom = () => {
    const on = !boxZoom
    setBoxZoom(on)
    instance.current?.dispatchAction({ type: 'takeGlobalCursor', key: 'dataZoomSelect', dataZoomSelectActive: on })
  }
  const resetZoom = () => instance.current?.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })
  state.current.excludeMode = excludeMode
  state.current.mode = mode
  state.current.onExclude = onExclude

  useEffect(() => {
    const el = box.current!
    const ch = echarts.init(el, undefined, { renderer: 'canvas' })
    instance.current = ch
    ;(el as unknown as { __echart?: echarts.ECharts }).__echart = ch     // для отладки и проверок в браузере
    const st = state.current
    const canvas = overlay.current!, card = tip.current!

    const gridRect = () => {
      const grid = (ch as unknown as { getModel(): { getComponent(t: string): { coordinateSystem?: { getRect(): { x: number; y: number; width: number; height: number } } } | undefined } })
        .getModel().getComponent('grid')?.coordinateSystem
      return grid?.getRect() ?? null
    }
    const view: View = {
      // перевод в пиксели — линейная формула, снятая с осей раз за кадр (calibrate): convertToPixel
      // на каждую из тысяч точек-кандидатов слишком медленный для миллиона точек
      toPixel: (x, y, a) => [st.map.x(x), st.map.y[a](y)],
      fromPixel: (px, py) => ch.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [px, py]) as [number, number],
      visible: t => st.selected[key(t.series)] !== false,
    }

    /** Пиксель = a + b · значение (у логарифмической оси — от log10 значения), по двум краям сетки. */
    const calibrate = (rect: { x: number; y: number; width: number; height: number }) => {
      const chart = st.chart
      const line = (p0: number, p1: number, v0: number, v1: number, log: boolean) => {
        const f = log ? Math.log10 : (v: number) => v
        const b = (p1 - p0) / (f(v1) - f(v0)), a = p0 - b * f(v0)
        return (v: number) => a + b * f(v)
      }
      const corner = (a: 0 | 1, px: number, py: number) =>
        ch.convertFromPixel({ xAxisIndex: 0, yAxisIndex: a }, [px, py]) as [number, number]
      const left = rect.x, right = rect.x + rect.width, top = rect.y, bottom = rect.y + rect.height
      const [x0, y0] = corner(0, left, bottom), [x1, y1] = corner(0, right, top)
      st.map.x = line(left, right, x0, x1, chart.x.scale === 'log')
      st.map.y[0] = line(bottom, top, y0, y1, chart.y.scale === 'log')
      if (chart.y2) {
        const [, u0] = corner(1, left, bottom), [, u1] = corner(1, right, top)
        st.map.y[1] = line(bottom, top, u0, u1, chart.y2.scale === 'log')
      } else st.map.y[1] = st.map.y[0]
    }

    const clear = () => {
      const g = canvas.getContext('2d')!
      g.setTransform(1, 0, 0, 1, 0, 0)
      g.clearRect(0, 0, canvas.width, canvas.height)
      card.hidden = true
      el.style.cursor = ''
      if (st.focused >= 0) { ch.dispatchAction({ type: 'downplay' }); st.focused = -1 }
      st.current = null
    }

    const draw = () => {
      st.frame = 0
      const tk = st.tokens!, chart = st.chart
      const m = st.mouse, rect = gridRect()
      if (!m || !rect || !st.tracks.length || st.down
        || m[0] < rect.x || m[0] > rect.x + rect.width || m[1] < rect.y || m[1] > rect.y + rect.height) { clear(); return }
      calibrate(rect)
      const h = hover(st.tracks, view, m[0], m[1], chart.x.scale, a => (a && chart.y2 ? chart.y2 : chart.y).scale, st.mode)
      st.current = h
      const dpr = window.devicePixelRatio || 1
      const w = el.clientWidth, hh = el.clientHeight
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(hh * dpr)) {
        canvas.width = Math.round(w * dpr); canvas.height = Math.round(hh * dpr)
        canvas.style.width = w + 'px'; canvas.style.height = hh + 'px'
      }
      const g = canvas.getContext('2d')!
      g.setTransform(dpr, 0, 0, dpr, 0, 0)
      g.clearRect(0, 0, w, hh)
      const fmtX = formatter(chart.x, st.spans.x)
      const fmtY = (a: 0 | 1) => formatter(a && chart.y2 ? chart.y2 : chart.y, a ? st.spans.y2 : st.spans.y)
      const unit = (a: 0 | 1) => (a && chart.y2 ? chart.y2 : chart.y).unit
      const colors = colorOf(chart)

      // перекрестие: вертикаль у кривых, полное — где раздел его включает
      const cx = h.point ? h.point.px : st.mode === 'facts' && h.focus ? h.focus.px : m[0]
      const vertical = chart.crosshair || h.values.some(v => v.track.curve)
      g.lineWidth = 1
      g.strokeStyle = alpha(tk.ink, 0.28)
      if (vertical) { g.beginPath(); g.moveTo(Math.round(cx) + 0.5, rect.y); g.lineTo(Math.round(cx) + 0.5, rect.y + rect.height); g.stroke() }
      if (chart.crosshair) {
        const cy = h.point ? h.point.py : m[1]
        g.beginPath(); g.moveTo(rect.x, Math.round(cy) + 0.5); g.lineTo(rect.x + rect.width, Math.round(cy) + 0.5); g.stroke()
        const [, yv] = view.fromPixel(cx, cy)
        pill(g, fmtY(0)(yv), rect.x - 4, cy, 'right', tk)
        pill(g, fmtX(view.fromPixel(cx, cy)[0]), cx, rect.y + rect.height + 4, 'top', tk)
      }
      // отметки на кривых в позиции курсора
      for (const v of h.values) {
        const c = colors(v.track.series), focus = v === h.focus && !h.point
        if (focus) { g.fillStyle = alpha(c, 0.18); g.beginPath(); g.arc(v.px, v.py, 10, 0, Math.PI * 2); g.fill() }
        g.fillStyle = c; g.strokeStyle = tk.surface; g.lineWidth = 2
        g.beginPath(); g.arc(v.px, v.py, focus ? 5 : 3.5, 0, Math.PI * 2); g.fill(); g.stroke()
      }
      if (h.point) {
        const c = colors(h.point.track.series)
        g.fillStyle = alpha(c, 0.2); g.beginPath(); g.arc(h.point.px, h.point.py, 12, 0, Math.PI * 2); g.fill()
        g.strokeStyle = c; g.lineWidth = 2; g.beginPath(); g.arc(h.point.px, h.point.py, 7, 0, Math.PI * 2); g.stroke()
      }

      // какая серия выделена
      const focusTrack = h.point?.track ?? h.focus?.track ?? null
      const fi = focusTrack ? focusTrack.index : -1
      if (st.blur && fi !== st.focused) {
        if (st.focused >= 0) ch.dispatchAction({ type: 'downplay' })
        if (fi >= 0) ch.dispatchAction({ type: 'highlight', seriesIndex: fi })
        st.focused = fi
      }
      const selectable = !!(h.point && st.excludeMode && h.point.track.series.ids && h.point.track.series.dataset)
      el.style.cursor = selectable ? 'pointer' : ''

      // подсказка
      const xTitle = axisTitle(chart.x.label, chart.x.unit)
      let html = ''
      if (h.point) {
        const p = h.point, s = p.track.series, j = p.track.src[p.k]
        const label = s.labels?.[j] ?? ''
        const yTitle = axisTitle((p.track.axis && chart.y2 ? chart.y2 : chart.y).label, '')
        html = tipHtml(`<span>${escapeHtml(xTitle)}</span><b>${escapeHtml(fmtX(p.x))}</b>`,
          [{ name: s.name, color: colors(s), dash: false, symbol: s.symbol, value: '', strong: true },
            { name: yTitle, color: 'transparent', dash: false, value: `<b>${escapeHtml(fmtY(p.track.axis)(p.y))}</b> ${escapeHtml(unit(p.track.axis))}` }],
          [...(label ? label.split(' · ').map(escapeHtml) : []), ...(tipsOf(chart, s)).map(escapeHtml)],
          selectable ? 'Щелчок исключит точку' : '')
      } else if (h.values.length) {
        const curves = h.values
        const focus = h.focus
        const others = curves.filter(v => v !== focus)
          .sort((a, b) => Math.abs(a.py - m[1]) - Math.abs(b.py - m[1])).slice(0, focus ? MAX_ROWS - 1 : MAX_ROWS)
          .sort((a, b) => a.py - b.py)
        const row = (v: typeof curves[number], strong = false): TipRow => ({
          name: v.track.series.name, color: colors(v.track.series), dash: dashOf(v.track.series) !== 'solid', strong,
          value: `<b>${escapeHtml(fmtY(v.track.axis)(v.y))}</b>${unit(v.track.axis) ? ' <small>' + escapeHtml(unit(v.track.axis)) + '</small>' : ''}`,
        })
        const extra: string[] = []
        if (focus) {
          const s = focus.track.series, j = focus.track.src[focus.k]
          const near = focus.track.xs[focus.k]
          const exact = st.mode === 'facts' || near === focus.x
          if (!exact) extra.push('<span class="tip-sub">≈ между замерами (интерполяция)</span>')
          if (s.labels?.[j] || s.ids) {
            if (!exact) extra.push(`<span class="tip-sub">Ближайший замер · ${escapeHtml(fmtX(near))}</span>`)
            if (s.labels?.[j]) extra.push(...s.labels[j].split(' · ').map(escapeHtml))
          }
          extra.push(...tipsOf(chart, s).map(escapeHtml))
        }
        const hidden = curves.length - others.length - (focus ? 1 : 0)
        const rows = [...(focus ? [row(focus, true)] : []), ...others.map(v => row(v))]
        html = tipHtml(`<span>${escapeHtml(xTitle)}</span><b>${escapeHtml(fmtX(h.focus?.x ?? h.x))}</b>`, rows,
          extra, hidden > 0 ? `ещё ${hidden} — ближе к курсору, чтобы увидеть` : '')
      }
      if (!html) { card.hidden = true; return }
      card.innerHTML = html
      card.hidden = false
      const bw = card.offsetWidth, bh = card.offsetHeight
      const ax = h.point?.px ?? h.focus?.px ?? m[0], ay = h.point?.py ?? h.focus?.py ?? m[1]
      let left = ax + 18, top = ay - bh / 2
      if (left + bw > w - 4) left = ax - 18 - bw
      if (left < 4) left = Math.max(4, Math.min(w - bw - 4, ax - bw / 2))
      top = Math.max(4, Math.min(hh - bh - 4, top))
      card.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`
    }
    st.draw = draw
    const schedule = () => { if (!st.frame) st.frame = requestAnimationFrame(draw) }

    const zr = ch.getZr()
    zr.on('mousemove', (e: { offsetX: number; offsetY: number }) => { st.mouse = [e.offsetX, e.offsetY]; schedule() })
    zr.on('globalout', () => { st.mouse = null; schedule() })
    zr.on('mousedown', (e: { offsetX: number; offsetY: number }) => { st.down = [e.offsetX, e.offsetY] })
    zr.on('mouseup', (e: { offsetX: number; offsetY: number }) => {
      const d = st.down
      st.down = null
      const moved = !d || Math.hypot(e.offsetX - d[0], e.offsetY - d[1]) > 4
      const p = st.current?.point
      if (!moved && p && st.excludeMode && p.track.series.dataset && p.track.series.ids) {
        const id = p.track.series.ids[p.track.src[p.k]]
        if (id) st.onExclude(p.track.series.dataset, id)
      }
      schedule()
    })
    zr.on('dblclick', () => ch.dispatchAction({ type: 'dataZoom', start: 0, end: 100 }))
    ch.on('legendselectchanged', (e: unknown) => { st.selected = { ...(e as { selected: Record<string, boolean> }).selected }; schedule() })
    ch.on('datazoom', schedule)
    // столбцы и ящики (ось категорий): щелчок по точке-выбросу тоже исключает её
    ch.on('click', (p: { seriesIndex?: number; data?: unknown }) => {
      if (st.tracks.length) return
      const series = p.seriesIndex === undefined ? undefined : st.chart.series[p.seriesIndex]
      const id = Array.isArray(p.data) ? (p.data[2] as string | undefined) : undefined
      if (st.excludeMode && series?.dataset && id) st.onExclude(series.dataset, id)
    })
    const observer = new ResizeObserver(() => { ch.resize(); schedule() })
    observer.observe(el)
    return () => { observer.disconnect(); if (st.frame) cancelAnimationFrame(st.frame); ch.dispose(); instance.current = null }
  }, [])

  useEffect(() => {
    const st = state.current, el = box.current!
    st.chart = chart
    st.tokens = chartTokens(el)
    st.tracks = buildTracks(chart.series, chart.x, !!chart.y2, s => hasMarkers(s, excludeMode, mode))
    const span = (t: Track[], f: (t: Track) => Float64Array) => {
      let lo = Infinity, hi = -Infinity
      for (const tr of t) for (const v of f(tr)) if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v }
      return hi - lo
    }
    st.spans = { x: span(st.tracks, t => t.xs), y: span(st.tracks.filter(t => !t.axis), t => t.ys), y2: span(st.tracks.filter(t => t.axis), t => t.ys) }
    st.blur = chart.series.reduce((n, s) => n + s.x.length, 0) <= BLUR_LIMIT
    st.focused = -1
    // легенда: скрытые серии остаются скрытыми после пересчёта, если они есть на новом графике
    instance.current?.setOption(toOption(chart, excludeMode, st.tokens, st.tracks.length > 0, mode), { notMerge: true })
    const names = new Set(chart.series.map(key))
    const hidden = Object.entries(st.selected).filter(([n, on]) => !on && names.has(n)).map(([n]) => n)
    for (const name of hidden) instance.current?.dispatchAction({ type: 'legendUnSelect', name })
    st.selected = Object.fromEntries(hidden.map(n => [n, false]))
    if (boxRef.current) instance.current?.dispatchAction({ type: 'takeGlobalCursor', key: 'dataZoomSelect', dataZoomSelectActive: true })
    st.draw()
  }, [chart, excludeMode, mode])

  return (
    <figure className={'chart' + (excludeMode ? ' exclude-mode' : '')}>
      <figcaption>
        <span title={chart.title}>{chart.title}</span>
        <span className="chart-actions">
          {chart.x.scale !== 'category' && <>
            <span className="chart-tools">
              <button type="button" className={'icon' + (boxZoom ? ' on' : '')} aria-pressed={boxZoom} onClick={toggleBoxZoom}
                title="Увеличить область: выделите её мышью. Ещё: Ctrl + колесо — масштаб, перетаскивание — сдвиг">
                <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.5" y="2.5" width="11" height="11" rx="1.5" strokeDasharray="2.5 2" /><path d="M8 5.5v5M5.5 8h5" /></svg>
              </button>
              <button type="button" className="icon" onClick={resetZoom} title="Сбросить масштаб (или двойной щелчок по графику)">
                <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8a5 5 0 1 0 1.6-3.7" /><path d="M3 2.5v3h3" /></svg>
              </button>
            </span>
            <span className="segmented" role="radiogroup" aria-label="Подсказка на кривых">
              <button type="button" role="radio" aria-checked={mode === 'smooth'} onClick={() => setHoverMode('smooth')}
                title="Значения между замерами — по линии (интерполяция)">Плавно</button>
              <button type="button" role="radio" aria-checked={mode === 'facts'} onClick={() => setHoverMode('facts')}
                title="Только фактические замеры, точки видны на линиях">Замеры</button>
            </span>
          </>}
          <DownloadMenu onDownload={onDownload} />
        </span>
      </figcaption>
      <div className="chart-stage">
        <div ref={box} className="chart-canvas" role="img" aria-label={chart.title} />
        <canvas ref={overlay} className="chart-overlay" aria-hidden="true" />
        <div ref={tip} className="atlas-tip floating" hidden />
      </div>
    </figure>
  )
}

function tipsOf(chart: Chart, s: Series) {
  return chart.series.filter(o => key(o) === key(s) && o.tooltip).map(o => o.kind === 'line' ? `${o.name}: ${o.tooltip}` : o.tooltip)
}

/** Подпись значения на оси у перекрестия. */
function pill(g: CanvasRenderingContext2D, text: string, x: number, y: number, side: 'right' | 'top', tk: ChartTokens) {
  g.font = `600 11px ${FONT}`
  const w = g.measureText(text).width + 12, h = 20
  const left = side === 'right' ? x - w : x - w / 2, top = side === 'right' ? y - h / 2 : y
  g.fillStyle = tk.ink
  g.beginPath(); g.roundRect(left, top, w, h, 4); g.fill()
  g.fillStyle = tk.surface; g.textBaseline = 'middle'; g.textAlign = 'center'
  g.fillText(text, left + w / 2, top + h / 2 + 0.5)
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

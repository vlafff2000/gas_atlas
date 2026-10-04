import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, BoxplotChart, LineChart, ScatterChart } from 'echarts/charts'
import { AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, ToolboxComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { Axis, Chart, ChartEvent, Series, WindowReply } from './api'
import { axisTitle, escapeHtml, formatDate, formatNumber } from './format'
import { alpha, chartTokens, FONT, PALETTE, palette, seriesColor, setDarkPalette, type ChartTokens } from './chartTheme'
import { buildTracks, decimalsFor, hover, toNumber, type Hover, type HoverMode, type Track, type View } from './chartHover'
import { hiddenEvents, setHoverMode, useAppliedTheme, useHoverMode, usePref } from './chartPrefs'
import { nextSyncId, pinShared, publish, sharedPins, subscribe, synced, unpinShared } from './chartSync'
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
const NAVIGATOR_SPAN = 180 * 86400e3   // ползунок времени под графиком, если ряды длиннее полугода
const MAX_PINS = 3                     // закреплённых подсказок на графике
const EVENT_RADIUS = 6                 // пикселей: событие у курсора попадает в подсказку

export const EVENT_KINDS: { kind: ChartEvent['kind']; label: string }[] = [
  { kind: 'regime', label: 'Смена режима' }, { kind: 'gdi', label: 'ГДИ' },
  { kind: 'repair', label: 'Ремонт' }, { kind: 'other', label: 'Прочее' },
]
const eventColor = (kind: ChartEvent['kind'], tk: ChartTokens) =>
  kind === 'regime' ? tk.muted : kind === 'gdi' ? tk.accent : kind === 'repair' ? '#d9480f' : tk.faint

interface Props {
  chart: Chart
  excludeMode: boolean
  onExclude: (dataset: string, id: string) => void
  /** Кроссплот давлений: щелчок по кнопке в закреплённой подсказке открывает динамику скважины. */
  onOpenWell?: (well: string, date: string) => void
  onDownload: (format: string, dpi: number) => Promise<void>
  /** Точки линий в окне оси X: при увеличении (и в режимах «Замеры» / «Исключать точки») прореженная линия заменяется точками окна. */
  fetchWindow?: (x0: number, x1: number, raw: boolean) => Promise<WindowReply>
}

/** Подгруженное окно: серии с точками в границах [from, to] поверх прореженного графика `base`. */
interface Patch { base: Chart; from: number; to: number; raw: boolean; series: WindowReply['series'] }
/** Оси после подгрузки окна остаются прежними: X — на весь график (сброс масштаба возвращает всё), Y — как её видел пользователь. */
type AxisPin = { x: [number, number] | null; y: [number, number] | null; y2: [number, number] | null }

const key = (s: Series) => s.group || s.name
/** Отметки замеров на линии: заданы модулем, нужны для исключения кликом или включён вид «Замеры».
 *  Расчётные линии (аппроксимация, модель) без ids — не замеры, их отметки не показываются. */
const hasMarkers = (s: Series, excludeMode: boolean, mode: HoverMode) =>
  s.markers || (!!s.ids && (excludeMode || (mode === 'facts' && s.x.length <= LARGE)))
const dashOf = (s: Series) => DASH[s.dash || (s.dashed ? 'dash' : 'solid')]

function colorOf(chart: Chart) {
  const groups = [...new Set(chart.series.map(key))]
  const p = palette()
  return (s: Series) => s.color ? seriesColor(s.color) : p[groups.indexOf(key(s)) % p.length]
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

/** Размах оси времени в мс по всем сериям (для решения, нужен ли ползунок). */
function timeSpan(chart: Chart) {
  if (chart.x.scale !== 'time') return 0
  let lo = Infinity, hi = -Infinity
  for (const s of chart.series) {
    for (const v of [s.x[0], s.x[s.x.length - 1]]) {
      const n = toNumber(v ?? null, 'time')
      if (Number.isFinite(n)) { lo = Math.min(lo, n); hi = Math.max(hi, n) }
    }
  }
  return hi > lo ? hi - lo : 0
}
export const hasNavigator = (chart: Chart) => timeSpan(chart) > NAVIGATOR_SPAN

/** Холст рисуется минимум в двойном разрешении: на обычных мониторах (масштаб 100%) линии и подписи иначе выходят «мыльными». */
function pixelRatio() { return Math.max(2, window.devicePixelRatio || 1) }

function toOption(chart: Chart, excludeMode: boolean, tk: ChartTokens, custom: boolean, mode: HoverMode, pin: AxisPin | null, base: Chart): echarts.EChartsCoreOption {
  const color = colorOf(chart)
  const tips = new Map<string, string[]>()
  for (const s of chart.series) {
    if (!s.tooltip) continue
    tips.set(key(s), [...(tips.get(key(s)) ?? []), s.kind === 'line' ? `${s.name}: ${s.tooltip}` : s.tooltip])
  }
  const legend = [...new Set(chart.series.map(key))].filter(g => chart.series.some(s => key(s) === g && s.legend))
  const total = chart.series.reduce((n, s) => n + s.x.length, 0)
  const time = chart.x.scale === 'time'
  const navigator = hasNavigator(base)      // по полному графику: подгрузка окна не должна убирать навигатор

  const axis = (a: Axis, position: 'x' | 'y' | 'y2') => {
    const plain = axisBase(a, position), fixed = pin?.[position]
    return fixed ? { ...plain, min: fixed[0], max: fixed[1] } : plain
  }
  const axisBase = (a: Axis, position: 'x' | 'y' | 'y2') => {
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
    grid: { left: 64, right: chart.y2 ? 64 : 20, top: 34, bottom: navigator ? 80 : 44 },
    xAxis: axis(chart.x, 'x'),
    yAxis: chart.y2 ? [axis(chart.y, 'y'), axis(chart.y2, 'y2')] : axis(chart.y, 'y'),
    // легенда — своя, под графиком (ChartLegend); компонент ECharts скрыт и только хранит, какие серии видны
    legend: { show: false, data: legend },
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
      // навигатор: весь период тенью и выбранное окно, его края и середину можно тянуть
      ...(navigator ? [{
        type: 'slider', xAxisIndex: 0, filterMode: 'none', height: 22, bottom: 8, left: 64, right: chart.y2 ? 64 : 20,
        brushSelect: false, showDataShadow: true, showDetail: false, borderColor: tk.axis, backgroundColor: 'transparent', borderRadius: 4,
        fillerColor: alpha(tk.accent, 0.12),
        dataBackground: { lineStyle: { color: tk.faint, width: 1 }, areaStyle: { color: alpha(tk.faint, 0.18) } },
        selectedDataBackground: { lineStyle: { color: tk.accent, width: 1 }, areaStyle: { color: alpha(tk.accent, 0.18) } },
        handleSize: '110%', handleStyle: { color: tk.surface, borderColor: tk.accent, borderWidth: 1.5 },
        moveHandleSize: 5, moveHandleStyle: { color: alpha(tk.accent, 0.45) },
        emphasis: { handleStyle: { borderColor: tk.ink }, moveHandleStyle: { color: tk.accent } },
        textStyle: { color: tk.muted, fontSize: 11 },
        labelFormatter: (v: number) => formatDate(new Date(v).toISOString().slice(0, 10)),
      }] : []),
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
          lineStyle: { color: c, width, type: dashOf(s), cap: 'round', join: 'round', ...(s.opacity < 1 ? { opacity: s.opacity } : {}) },
          emphasis: { ...emphasis, lineStyle: { width: width + 1 } } }
      }
      const big = rows.length > LARGE
      return { ...common, type: 'scatter', z: s.hollow ? 4 : 3, symbol: SYMBOL[s.symbol], symbolSize: big ? 5 : s.hollow ? 10 : 9,
        large: big, largeThreshold: LARGE, progressive: 0,
        itemStyle: {
          ...(s.hollow
            ? { color: 'rgba(255,255,255,0)', borderColor: c, borderWidth: 1.8 }
            : big ? { color: alpha(c, 0.55) } : { color: c, borderColor: tk.surface, borderWidth: 1.5 }),
          ...(s.opacity < 1 ? { opacity: s.opacity } : {}) } }
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

/** Закреплённая подсказка; off — сдвиг карточки от её точки в пикселях, если карточку перетащили. */
interface Pin { x: number; y: number; axis: 0 | 1; html: string; el: HTMLDivElement; off: [number, number] | null
  token: number; shared: boolean; own: boolean }   // token — запись в общем списке; own — закреплена на этом графике, а не пришла с другого

/** Ближайшая к точке (px, py) точка прямоугольника карточки — конец линии-выноски. */
const nearestOnBox = (px: number, py: number, l: number, t: number, w: number, h: number): [number, number] =>
  [Math.max(l, Math.min(l + w, px)), Math.max(t, Math.min(t + h, py))]
interface Plotted { x: number; label: string; kind: ChartEvent['kind'] }

/** Ключ общего перекрестия: все графики по времени — вместе, остальные — с той же подписью и единицей оси X. */
const syncKey = (chart: Chart) =>
  chart.x.scale === 'category' ? null : chart.x.scale === 'time' ? 'time' : `${chart.x.scale}|${chart.x.label}|${chart.x.unit}`

export function ChartView({ chart: given, excludeMode, onExclude, onOpenWell, onDownload, fetchWindow }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const tip = useRef<HTMLDivElement>(null)
  const stage = useRef<HTMLDivElement>(null)
  const instance = useRef<echarts.ECharts | null>(null)
  const [patch, setPatch] = useState<Patch | null>(null)
  const chart = useMemo<Chart>(() => {
    if (!patch || patch.base !== given) return given
    return { ...given, series: given.series.map((s, i) => { const w = patch.series[i]; return w ? { ...s, x: w.x, y: w.y, ids: w.ids, labels: w.labels, total: w.total } : s }) }
  }, [given, patch])
  const thinned = given.series.map((s, i) => [s, i] as const).filter(([s]) => s.total > s.x.length)
  const state = useRef({
    chart: given, base: given, fetchWindow, patch: null as Patch | null, pin: null as AxisPin | null, ensure: (() => {}) as () => void,
    edges: (() => null) as () => [number, number] | null,
    excludeMode, onExclude, onOpenWell: onOpenWell as Props['onOpenWell'], tracks: [] as Track[], selected: {} as Record<string, boolean>,
    current: null as Hover | null, focused: -1, mouse: null as [number, number] | null, down: null as [number, number] | null,
    mode: 'smooth' as HoverMode, map: { x: (v: number) => v, y: [(v: number) => v, (v: number) => v] as [(v: number) => number, (v: number) => number] }, frame: 0, tokens: null as ChartTokens | null, spans: { x: 1, y: 1, y2: 1 }, blur: true, draw: (() => {}) as () => void,
    id: nextSyncId(), sync: syncKey(chart), events: [] as Plotted[], hiddenEvents: new Set<string>(), pins: [] as Pin[],
    renderPins: (() => {}) as () => void, reconcile: (() => {}) as () => void,
  })
  const mode = useHoverMode()
  const theme = useAppliedTheme()
  const offEvents = usePref(hiddenEvents)
  const [boxZoom, setBoxZoom] = useState(false)
  const [hidden, setHidden] = useState<Set<string>>(new Set())       // скрытые пункты легенды (ключи серий)
  const [facetOff, setFacetOff] = useState<Set<string>>(new Set())   // скрытые значения признаков: 'Период\u0001 2024'
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
  state.current.onOpenWell = onOpenWell
  state.current.base = given
  state.current.fetchWindow = fetchWindow
  state.current.hiddenEvents = new Set(offEvents)

  useEffect(() => {
    const el = box.current!
    const ch = echarts.init(el, undefined, { renderer: 'canvas', devicePixelRatio: pixelRatio() })
    instance.current = ch
    ;(el as unknown as { __echart?: echarts.ECharts }).__echart = ch     // для отладки и проверок в браузере
    const st = state.current
    const canvas = overlay.current!, card = tip.current!, host = stage.current!

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

    const fmtX = () => formatter(st.chart.x, st.spans.x)
    const fmtY = (a: 0 | 1) => formatter(a && st.chart.y2 ? st.chart.y2 : st.chart.y, a ? st.spans.y2 : st.spans.y)
    const unit = (a: 0 | 1) => (a && st.chart.y2 ? st.chart.y2 : st.chart.y).unit

    /** Закреплённые подсказки: номер, карточка, разница с первой, крестик. */
    const renderPins = () => {
      const first = st.pins[0]
      st.pins.forEach((p, i) => {
        let delta = ''
        if (i > 0 && first) {
          const dx = p.x - first.x
          const xs = st.chart.x.scale === 'time'
            ? `${dx >= 0 ? '+' : '−'}${formatNumber(Math.abs(dx) / 86400e3, 0)} сут`
            : `${dx >= 0 ? '+' : '−'}${fmtX()(Math.abs(dx))}`
          const ys = p.axis === first.axis
            ? `${p.y - first.y >= 0 ? '+' : '−'}${fmtY(p.axis)(Math.abs(p.y - first.y))}${unit(p.axis) ? ' ' + unit(p.axis) : ''}` : ''
          delta = `<div class="tip-delta"><span>к №1</span><b>${escapeHtml(xs)}</b>${ys ? `<b>${escapeHtml(ys)}</b>` : ''}</div>`
        }
        p.el.innerHTML = `<span class="pin-badge">${i + 1}</span>`
          + `<button type="button" class="pin-close" data-unpin="${i}" title="Открепить" aria-label="Открепить подсказку">×</button>`
          + p.html.replace(/<\/div>$/, delta + '</div>')
      })
    }
    st.renderPins = renderPins
    const addPin = (x: number, y: number, axis: 0 | 1) => {
      if (card.hidden || !card.innerHTML) return
      const copy = document.createElement('div')
      copy.innerHTML = card.innerHTML
      copy.querySelectorAll('.tip-foot').forEach(n => n.remove())
      // кроссплот давлений: из подсказки точки («Скв. 74 · … · 01.02.2021 · …») — к динамике этой скважины
      const pt = st.current?.point
      const where = /^Скв\. (\S+) .*?(\d{2}\.\d{2}\.\d{4})/.exec(pt?.track.series.labels?.[pt.track.src[pt.k]] ?? '')
      if (st.onOpenWell && st.chart.id === 'pressure-cross' && where) {
        (copy.lastElementChild ?? copy).insertAdjacentHTML('beforeend',
          `<button type="button" class="tip-go" data-open-well="${escapeHtml(where[1])}|${where[2]}">Динамика скважины</button>`)
      }
      const el = document.createElement('div')
      el.className = 'atlas-tip pinned'
      host.appendChild(el)
      const token = st.sync ? pinShared(st.id, st.sync, x, MAX_PINS) : nextSyncId()
      st.pins.push({ x, y, axis, html: copy.innerHTML, el, off: null, token, shared: !!st.sync, own: true })
      while (st.pins.length > MAX_PINS) { const old = st.pins.shift()!; old.el.remove(); if (old.shared) unpinShared(old.token) }
      renderPins()
    }
    const onUnpin = (e: MouseEvent) => {
      const b = (e.target as HTMLElement).closest('[data-unpin]')
      if (!b) return
      const i = Number(b.getAttribute('data-unpin'))
      const gone = st.pins.splice(i, 1)[0]
      gone?.el.remove()
      if (gone?.shared) unpinShared(gone.token)
      renderPins(); schedule()
    }
    host.addEventListener('click', onUnpin)
    const onOpen = (e: MouseEvent) => {
      const b = (e.target as HTMLElement).closest('[data-open-well]')
      if (!b) return
      const [well, date] = (b.getAttribute('data-open-well') ?? '').split('|')
      st.onOpenWell?.(well, date)
    }
    host.addEventListener('click', onOpen)
    // перетаскивание карточки за номер или заголовок: точка остаётся на месте, к ней ведёт линия-выноска
    let drag: { pin: Pin; dx: number; dy: number; id: number } | null = null
    const onGrab = (e: PointerEvent) => {
      const t = e.target as HTMLElement
      if (e.button !== 0 || t.closest('.pin-close') || !t.closest('.pin-badge, .tip-head')) return
      const pin = st.pins.find(p => p.el.contains(t))
      if (!pin) return
      const b = pin.el.getBoundingClientRect()
      drag = { pin, dx: e.clientX - b.left, dy: e.clientY - b.top, id: e.pointerId }
      host.setPointerCapture(e.pointerId)
      pin.el.classList.add('dragging')
      e.preventDefault(); e.stopPropagation()
    }
    const onDrag = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.id) return
      const { pin } = drag
      const r = host.getBoundingClientRect()
      const [px, py] = view.toPixel(pin.x, pin.y, pin.axis)
      const bw = pin.el.offsetWidth, bh = pin.el.offsetHeight
      const left = Math.max(4, Math.min(el.clientWidth - bw - 4, e.clientX - r.left - drag.dx))
      const top = Math.max(4, Math.min(el.clientHeight - bh - 4, e.clientY - r.top - drag.dy))
      pin.off = [left - px, top - py]
      schedule()
    }
    const onDrop = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.id) return
      drag.pin.el.classList.remove('dragging')
      if (host.hasPointerCapture(e.pointerId)) host.releasePointerCapture(e.pointerId)
      drag = null
    }
    host.addEventListener('pointerdown', onGrab)
    host.addEventListener('pointermove', onDrag)
    host.addEventListener('pointerup', onDrop)
    host.addEventListener('pointercancel', onDrop)

    /** События у курсора по X: строки для подсказки. */
    const nearEvents = (px: number) => {
      const out: string[] = []
      let more = 0
      for (const e of st.events) {
        if (st.hiddenEvents.has(e.kind)) continue
        if (Math.abs(st.map.x(e.x) - px) > EVENT_RADIUS) continue
        if (out.length < 4) out.push(`<span class="tip-event" style="--c:${eventColor(e.kind, st.tokens!)}">${escapeHtml(e.label)}</span>`)
        else more++
      }
      if (more) out.push(`<span class="tip-sub">и ещё событий: ${more}</span>`)
      return out
    }

    /** Подсказка по кривым в положении h; py — вертикаль, к которой ближе всего выбираются строки. */
    const valuesTip = (h: Hover, py: number, events: string[], foot: string) => {
      const chart = st.chart, colors = colorOf(chart)
      const xTitle = axisTitle(chart.x.label, chart.x.unit)
        const curves = h.values
        const focus = h.focus
        const others = curves.filter(v => v !== focus)
          .sort((a, b) => Math.abs(a.py - py) - Math.abs(b.py - py)).slice(0, focus ? MAX_ROWS - 1 : MAX_ROWS)
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
            if (!exact) extra.push(`<span class="tip-sub">Ближайший замер · ${escapeHtml(fmtX()(near))}</span>`)
            if (s.labels?.[j]) extra.push(...s.labels[j].split(' · ').map(escapeHtml))
          }
          extra.push(...tipsOf(chart, s).map(escapeHtml))
        }
        extra.push(...events)
        const hidden = curves.length - others.length - (focus ? 1 : 0)
        const rows = [...(focus ? [row(focus, true)] : []), ...others.map(v => row(v))]
        return tipHtml(`<span>${escapeHtml(xTitle)}</span><b>${escapeHtml(fmtX()(h.focus?.x ?? h.x))}</b>`, rows,
          extra, hidden > 0 ? `ещё ${hidden} — ближе к курсору, чтобы увидеть` : foot)
    }

    const draw = () => {
      st.frame = 0
      const tk = st.tokens!, chart = st.chart
      const m = st.mouse, rect = gridRect()
      const dpr = pixelRatio()
      const w = el.clientWidth, hh = el.clientHeight
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(hh * dpr)) {
        canvas.width = Math.round(w * dpr); canvas.height = Math.round(hh * dpr)
        canvas.style.width = w + 'px'; canvas.style.height = hh + 'px'
      }
      const g = canvas.getContext('2d')!
      g.setTransform(dpr, 0, 0, dpr, 0, 0)
      g.clearRect(0, 0, w, hh)
      if (!rect || !tk) { card.hidden = true; return }
      const ready = st.tracks.length > 0 || st.events.length > 0
      if (ready) calibrate(rect)
      const inside = (px: number, py: number) => px >= rect.x && px <= rect.x + rect.width && py >= rect.y && py <= rect.y + rect.height
      const colors = colorOf(chart)

      // события: пунктир смены режима через весь график, у остальных — флажок сверху и тонкая линия
      if (st.events.length) {
        let last = -Infinity, lastKind = ''
        // много событий — линии через весь график не нужны, остаются флажки сверху
        const crowded = st.events.filter(e => e.kind !== 'regime' && !st.hiddenEvents.has(e.kind)).length > 14
        for (const e of st.events) {
          if (st.hiddenEvents.has(e.kind)) continue
          const px = Math.round(st.map.x(e.x)) + 0.5
          if (px < rect.x || px > rect.x + rect.width) continue
          if (Math.abs(px - last) < 2 && lastKind === e.kind) continue
          last = px; lastKind = e.kind
          const c = eventColor(e.kind, tk)
          g.save()
          g.strokeStyle = alpha(c, e.kind === 'regime' ? 0.55 : 0.3); g.lineWidth = 1
          g.setLineDash(e.kind === 'regime' ? [5, 4] : [2, 3])
          if (e.kind === 'regime' || !crowded) { g.beginPath(); g.moveTo(px, rect.y); g.lineTo(px, rect.y + rect.height); g.stroke() }
          g.setLineDash([])
          g.fillStyle = c
          g.beginPath(); g.moveTo(px - 4, rect.y - 7); g.lineTo(px + 4, rect.y - 7); g.lineTo(px, rect.y - 1); g.closePath(); g.fill()
          g.restore()
        }
      }

      // закреплённые подсказки: отметка с номером и карточка рядом, следуют за масштабом
      st.pins.forEach((p, i) => {
        if (!Number.isFinite(p.y)) { p.el.hidden = true; return }
        const [px, py] = view.toPixel(p.x, p.y, p.axis)
        if (!inside(px, py)) { p.el.hidden = true; return }
        p.el.hidden = false
        const bw = p.el.offsetWidth, bh = p.el.offsetHeight
        let left: number, top: number
        if (p.off) {
          left = px + p.off[0]; top = py + p.off[1]
        } else {
          left = px + 14; top = py - 14 - bh
          if (left + bw > w - 4) left = px - 14 - bw
          if (top < 4) top = py + 14
        }
        left = Math.round(Math.max(4, Math.min(w - bw - 4, left)))
        top = Math.round(Math.max(4, Math.min(hh - bh - 4, top)))
        p.el.style.transform = `translate(${left}px, ${top}px)`
        // перенесённая карточка: тонкая линия от отметки до ближайшего края карточки
        if (p.off) {
          const [ex, ey] = nearestOnBox(px, py, left, top, bw, bh)
          if (Math.hypot(ex - px, ey - py) > 10) {
            g.save(); g.strokeStyle = alpha(tk.ink, 0.55); g.lineWidth = 1
            g.beginPath(); g.moveTo(px, py); g.lineTo(ex, ey); g.stroke(); g.restore()
          }
        }
        g.fillStyle = tk.ink; g.strokeStyle = tk.surface; g.lineWidth = 2
        g.beginPath(); g.arc(px, py, 8, 0, Math.PI * 2); g.fill(); g.stroke()
        g.fillStyle = tk.surface; g.font = `700 10px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'
        g.fillText(String(i + 1), px, py + 0.5)
      })

      const own = !!(m && !st.down && ready && inside(m[0], m[1]))
      if (!own) {
        card.hidden = true
        el.style.cursor = ''
        if (st.focused >= 0) { ch.dispatchAction({ type: 'downplay' }); st.focused = -1 }
        st.current = null
        publish(st.id, null, null)
        // общее перекрестие: курсор на другом графике с той же осью X
        const s = synced()
        if (s && s.source !== st.id && s.key === st.sync && st.tracks.length) {
          const px = st.map.x(s.x)
          if (px >= rect.x && px <= rect.x + rect.width) {
            g.save()
            g.strokeStyle = alpha(tk.accent, 0.7); g.lineWidth = 1; g.setLineDash([4, 3])
            g.beginPath(); g.moveTo(Math.round(px) + 0.5, rect.y); g.lineTo(Math.round(px) + 0.5, rect.y + rect.height); g.stroke()
            g.restore()
            const h = hover(st.tracks, view, px, rect.y + rect.height / 2, chart.x.scale, a => (a && chart.y2 ? chart.y2 : chart.y).scale, st.mode)
            for (const v of h.values) {
              if (!v.track.curve || !inside(v.px, v.py)) continue
              g.fillStyle = colors(v.track.series); g.strokeStyle = tk.surface; g.lineWidth = 2
              g.beginPath(); g.arc(v.px, v.py, 3.5, 0, Math.PI * 2); g.fill(); g.stroke()
            }
            pill(g, fmtX()(s.x), px, rect.y + rect.height + 4, 'top', tk)
          }
        }
        return
      }
      const h = hover(st.tracks, view, m![0], m![1], chart.x.scale, a => (a && chart.y2 ? chart.y2 : chart.y).scale, st.mode)
      st.current = h
      publish(st.id, st.sync, h.point?.x ?? (st.mode === 'facts' && h.focus ? h.focus.x : h.x))

      // перекрестие: вертикаль у кривых, полное — где раздел его включает
      const cx = h.point ? h.point.px : st.mode === 'facts' && h.focus ? h.focus.px : m![0]
      const vertical = chart.crosshair || h.values.some(v => v.track.curve)
      g.lineWidth = 1
      g.strokeStyle = alpha(tk.ink, 0.28)
      if (vertical) { g.beginPath(); g.moveTo(Math.round(cx) + 0.5, rect.y); g.lineTo(Math.round(cx) + 0.5, rect.y + rect.height); g.stroke() }
      if (chart.crosshair) {
        const cy = h.point ? h.point.py : m![1]
        g.beginPath(); g.moveTo(rect.x, Math.round(cy) + 0.5); g.lineTo(rect.x + rect.width, Math.round(cy) + 0.5); g.stroke()
        const [, yv] = view.fromPixel(cx, cy)
        pill(g, fmtY(0)(yv), rect.x - 4, cy, 'right', tk)
        pill(g, fmtX()(view.fromPixel(cx, cy)[0]), cx, rect.y + rect.height + 4, 'top', tk)
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
      const events = nearEvents(cx)
      const foot = selectable ? 'Щелчок исключит точку' : st.excludeMode ? '' : 'Щелчок закрепит подсказку'
      let html = ''
      if (h.point) {
        const p = h.point, s = p.track.series, j = p.track.src[p.k]
        const label = s.labels?.[j] ?? ''
        const yTitle = axisTitle((p.track.axis && chart.y2 ? chart.y2 : chart.y).label, '')
        html = tipHtml(`<span>${escapeHtml(xTitle)}</span><b>${escapeHtml(fmtX()(p.x))}</b>`,
          [{ name: s.name, color: colors(s), dash: false, symbol: s.symbol, value: '', strong: true },
            { name: yTitle, color: 'transparent', dash: false, value: `<b>${escapeHtml(fmtY(p.track.axis)(p.y))}</b> ${escapeHtml(unit(p.track.axis))}` }],
          [...(label ? label.split(' · ').map(escapeHtml) : []), ...(tipsOf(chart, s)).map(escapeHtml), ...events], foot)
      } else if (h.values.length) {
        html = valuesTip(h, m![1], events, foot)
      } else if (events.length) {
        html = tipHtml(`<span>${escapeHtml(xTitle)}</span><b>${escapeHtml(fmtX()(h.x))}</b>`, [], events)
      }
      if (!html) { card.hidden = true; return }
      card.innerHTML = html
      card.hidden = false
      const bw = card.offsetWidth, bh = card.offsetHeight
      const ax = h.point?.px ?? h.focus?.px ?? m![0], ay = h.point?.py ?? h.focus?.py ?? m![1]
      let left = ax + 18, top = ay - bh / 2
      if (left + bw > w - 4) left = ax - 18 - bw
      if (left < 4) left = Math.max(4, Math.min(w - bw - 4, ax - bw / 2))
      top = Math.max(4, Math.min(hh - bh - 4, top))
      card.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`
    }
    /** Карточка, закреплённая на другом графике с той же осью X: значения наших кривых в этой точке. */
    const addRemote = (x: number, token: number) => {
      const rect = gridRect()
      if (!rect || !st.tracks.length) return
      calibrate(rect)
      const py = rect.y + rect.height / 2
      const h = hover(st.tracks, view, st.map.x(x), py, st.chart.x.scale, a => (a && st.chart.y2 ? st.chart.y2 : st.chart.y).scale, st.mode)
      const v = h.focus ?? h.values[0]
      if (!v) return
      const el = document.createElement('div')
      el.className = 'atlas-tip pinned'
      host.appendChild(el)
      st.pins.push({ x, y: v.y, axis: v.track.axis, html: valuesTip(h, py, [], ''), el, off: null, token, shared: true, own: false })
    }
    /** Сверка с общим списком: чужие закрепления появляются, снятые — исчезают. */
    st.reconcile = () => {
      if (!st.sync) return
      const list = sharedPins(st.sync)
      const live = new Set(list.map(e => e.token))
      let changed = false
      st.pins = st.pins.filter(p => {
        if (!p.shared || live.has(p.token)) return true
        p.el.remove(); changed = true; return false
      })
      for (const e of list) {
        if (e.source === st.id || st.pins.some(p => p.token === e.token)) continue
        const n = st.pins.length
        addRemote(e.x, e.token)
        if (st.pins.length > n) changed = true
      }
      if (changed) {
        const order = new Map(list.map((e, i) => [e.token, i]))
        st.pins.sort((a, b) => (order.get(a.token) ?? 0) - (order.get(b.token) ?? 0))
        renderPins()
      }
    }
    st.draw = draw
    const schedule = () => { if (!st.frame) st.frame = requestAnimationFrame(draw) }
    const unsync = subscribe(() => { st.reconcile(); if (!st.mouse) schedule() })

    const zr = ch.getZr()
    zr.on('mousemove', (e: { offsetX: number; offsetY: number }) => { st.mouse = [e.offsetX, e.offsetY]; schedule() })
    zr.on('globalout', () => { st.mouse = null; schedule() })
    zr.on('mousedown', (e: { offsetX: number; offsetY: number }) => { st.down = [e.offsetX, e.offsetY] })
    zr.on('mouseup', (e: { offsetX: number; offsetY: number }) => {
      const d = st.down
      st.down = null
      const moved = !d || Math.hypot(e.offsetX - d[0], e.offsetY - d[1]) > 4
      const h = st.current, p = h?.point
      if (!moved && p && st.excludeMode && p.track.series.dataset && p.track.series.ids) {
        const id = p.track.series.ids[p.track.src[p.k]]
        if (id) st.onExclude(p.track.series.dataset, id)
      } else if (!moved && h && !boxRef.current) {
        // щелчок закрепляет подсказку там, где она сейчас: у точки, у выделенной кривой или у курсора
        if (p) addPin(p.x, p.y, p.track.axis)
        else if (h.focus) addPin(h.focus.x, h.focus.y, h.focus.track.axis)
        else if (h.values.length) addPin(h.x, view.fromPixel(e.offsetX, e.offsetY)[1], 0)
      }
      schedule()
    })
    zr.on('dblclick', () => ch.dispatchAction({ type: 'dataZoom', start: 0, end: 100 }))
    // Окно оси X → точки окна: при увеличении, а также в режимах «Замеры» и «Исключать точки» (там нужны все замеры)
    let timer = 0, seq = 0
    const edges = (): [number, number] | null => {
      const r = gridRect()
      if (!r) return null
      const a = ch.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [r.x, r.y + r.height]) as [number, number]
      const b = ch.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [r.x + r.width, r.y]) as [number, number]
      return Number.isFinite(a[0]) && Number.isFinite(b[0]) ? [Math.min(a[0], b[0]), Math.max(a[0], b[0])] : null
    }
    const axisExtent = (index: number): [number, number] | null => {
      try {
        const axis = (ch as unknown as { getModel(): { getComponent(n: string, i: number): { axis?: { scale: { getExtent(): number[] } } } | undefined } })
          .getModel().getComponent('yAxis', index)?.axis
        const e = axis?.scale.getExtent()
        return e && Number.isFinite(e[0]) && Number.isFinite(e[1]) ? [e[0], e[1]] : null
      } catch { return null }
    }
    const dataExtent = (c: Chart): [number, number] => {
      let lo = Infinity, hi = -Infinity
      for (const s of c.series) {
        if (s.kind !== 'line') continue
        for (const v of [s.x[0], s.x[s.x.length - 1]]) {
          const n = toNumber(v, c.x.scale)
          if (Number.isFinite(n)) { lo = Math.min(lo, n); hi = Math.max(hi, n) }
        }
      }
      return [lo, hi]
    }
    st.edges = edges
    st.ensure = () => {
      const base = st.base, load = st.fetchWindow
      if (!load || !base.series.some(s => s.total > s.x.length) || base.x.scale === 'category') return
      const view = edges()
      if (!view) return
      const [lo, hi] = dataExtent(base), span = hi - lo
      if (!(span > 0)) return
      const raw = st.mode === 'facts' || st.excludeMode
      const whole = view[0] <= lo + span * 0.01 && view[1] >= hi - span * 0.01
      const have = st.patch
      if (whole && !raw) {
        if (have) { st.patch = null; st.pin = null; ++seq; setPatch(null) }
        return
      }
      const width = view[1] - view[0]
      if (have && have.base === base && have.raw === raw && view[0] >= have.from && view[1] <= have.to
        && (whole || width >= (have.to - have.from) * 0.2)) return
      const from = whole ? lo : view[0] - width * 0.25, to = whole ? hi : view[1] + width * 0.25
      const id = ++seq
      load(from, to, raw).then(reply => {
        if (id !== seq || st.base !== base) return
        st.pin = { x: [lo, hi], y: axisExtent(0), y2: base.y2 ? axisExtent(1) : null }
        const next: Patch = { base, from, to, raw, series: reply.series }
        st.patch = next
        setPatch(next)
      }).catch(() => { /* остаётся прореженный график; пометка «показана часть точек» это говорит */ })
    }
    ch.on('datazoom', () => { schedule(); window.clearTimeout(timer); timer = window.setTimeout(st.ensure, 250) })
    // столбцы и ящики (ось категорий): щелчок по точке-выбросу тоже исключает её
    ch.on('click', (p: { seriesIndex?: number; data?: unknown }) => {
      if (st.tracks.length) return
      const series = p.seriesIndex === undefined ? undefined : st.chart.series[p.seriesIndex]
      const id = Array.isArray(p.data) ? (p.data[2] as string | undefined) : undefined
      if (st.excludeMode && series?.dataset && id) st.onExclude(series.dataset, id)
    })
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || !st.pins.length) return
      st.pins.forEach(p => { p.el.remove(); if (p.shared) unpinShared(p.token) }); st.pins = []; schedule()
    }
    window.addEventListener('keydown', onKey)
    const observer = new ResizeObserver(() => { ch.resize(); schedule() })
    observer.observe(el)
    return () => {
      window.clearTimeout(timer); ++seq
      observer.disconnect(); unsync(); publish(st.id, null, null)
      st.pins.forEach(p => { p.el.remove(); if (p.own && p.shared) unpinShared(p.token) })
      window.removeEventListener('keydown', onKey); host.removeEventListener('click', onUnpin); host.removeEventListener('click', onOpen)
      host.removeEventListener('pointerdown', onGrab); host.removeEventListener('pointermove', onDrag)
      host.removeEventListener('pointerup', onDrop); host.removeEventListener('pointercancel', onDrop)
      if (st.frame) cancelAnimationFrame(st.frame)
      ch.dispose(); instance.current = null
    }
  }, [])

  useEffect(() => {
    const st = state.current, el = box.current!
    setDarkPalette(theme === 'dark')
    st.chart = chart
    st.sync = syncKey(chart)
    st.tokens = chartTokens(el)
    st.tracks = buildTracks(chart.series, chart.x, !!chart.y2, s => hasMarkers(s, excludeMode, mode))
    st.events = (chart.events ?? []).map(e => ({ x: toNumber(e.x, chart.x.scale), label: e.label, kind: e.kind }))
      .filter(e => Number.isFinite(e.x)).sort((a, b) => a.x - b.x)
    const span = (t: Track[], f: (t: Track) => Float64Array) => {
      let lo = Infinity, hi = -Infinity
      for (const tr of t) for (const v of f(tr)) if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v }
      return hi - lo
    }
    st.spans = { x: span(st.tracks, t => t.xs), y: span(st.tracks.filter(t => !t.axis), t => t.ys), y2: span(st.tracks.filter(t => t.axis), t => t.ys) }
    st.blur = chart.series.reduce((n, s) => n + s.x.length, 0) <= BLUR_LIMIT
    st.focused = -1
    const view = st.patch && st.patch.base === given ? st.edges() : null      // масштаб сохраняется при подмене точек окна
    instance.current?.setOption(toOption(chart, excludeMode, st.tokens, st.tracks.length > 0, mode, st.patch ? st.pin : null, given), { notMerge: true })
    if (view) instance.current?.dispatchAction({ type: 'dataZoom', dataZoomIndex: 0, startValue: view[0], endValue: view[1] })
    st.selected = {}
    applyLegend()
    if (boxRef.current) instance.current?.dispatchAction({ type: 'takeGlobalCursor', key: 'dataZoomSelect', dataZoomSelectActive: true })
    st.reconcile()
    st.draw()
    const later = window.setTimeout(st.ensure, 0)
    return () => window.clearTimeout(later)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chart, excludeMode, mode, theme])

  // новый расчёт (другие параметры, исключение точки) — подгруженное окно относится к прежнему графику
  useEffect(() => { state.current.patch = null; state.current.pin = null; setPatch(null) }, [given])

  // новый расчёт — прежние закреплённые подсказки относятся к другим данным
  const lastGiven = useRef(given)
  useEffect(() => {
    if (lastGiven.current === given) return        // первое построение: закрепления с других графиков остаются
    lastGiven.current = given
    const st = state.current
    st.pins.forEach(p => { p.el.remove(); if (p.shared) unpinShared(p.token) }); st.pins = []
  }, [given])
  // разница с первой подсказкой — в единицах новой темы и вида не меняется, но номера и отметки перерисовать
  useEffect(() => { state.current.draw() }, [offEvents])

  // легенда: видимость серий = не скрыт пункт и не скрыто ни одно значение её признаков
  setDarkPalette(theme === 'dark')
  const legend = useMemo(() => legendModel(chart, excludeMode, mode), [chart, excludeMode, mode, theme])
  const applyLegend = () => {
    const ch = instance.current, st = state.current
    if (!ch) return
    for (const item of legend.items) {
      const on = !hidden.has(item.name) && !item.facets.every(f => [...f.entries()].some(([k, v]) => facetOff.has(k + '\u0001' + v)))
      if ((st.selected[item.name] !== false) === on) continue
      ch.dispatchAction({ type: on ? 'legendSelect' : 'legendUnSelect', name: item.name })
      st.selected[item.name] = on
    }
  }
  useEffect(() => { applyLegend(); state.current.draw() })    // после каждого изменения легенды или графика

  const highlight = (name: string | null) => {
    const ch = instance.current
    if (!ch || !state.current.blur) return
    ch.dispatchAction({ type: 'downplay' })
    if (name) ch.dispatchAction({ type: 'highlight', seriesName: name })
  }

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
      {thinned.length > 0 && <ThinNote chart={chart} thinned={thinned.map(([, i]) => i)} windowed={!!patch && patch.base === given} patch={patch} />}
      <div className="chart-stage" ref={stage}>
        <div ref={box} className="chart-canvas" role="img" aria-label={chart.title} />
        <canvas ref={overlay} className="chart-overlay" aria-hidden="true" />
        <div ref={tip} className="atlas-tip floating" hidden />
      </div>
      <ChartLegend model={legend} hidden={hidden} facetOff={facetOff} events={chart.events ?? []}
        offEvents={offEvents} onHighlight={highlight}
        onToggle={(name, only) => setHidden(h => {
          if (only) {
            const others = legend.items.map(i => i.name).filter(n => n !== name)
            const isolated = !h.has(name) && others.every(n => h.has(n))
            return isolated ? new Set() : new Set(others)
          }
          const n = new Set(h); if (n.has(name)) n.delete(name); else n.add(name); return n
        })}
        onFacet={(facet, value, only) => setFacetOff(off => {
          const values = legend.facets.find(f => f.name === facet)?.values.map(v => v.value) ?? []
          const id = (v: string) => facet + '\u0001' + v
          const n = new Set(off)
          if (only) {
            const isolated = !off.has(id(value)) && values.filter(v => v !== value).every(v => off.has(id(v)))
            for (const v of values) { if (isolated || v === value) n.delete(id(v)); else n.add(id(v)) }
            return n
          }
          if (n.has(id(value))) n.delete(id(value)); else n.add(id(value))
          return n
        })}
        onEvent={kind => hiddenEvents.set(offEvents.includes(kind) ? offEvents.filter(k => k !== kind) : [...offEvents, kind])} />
    </figure>
  )
}

// ---------- легенда ----------

interface LegendItem {
  name: string; color: string; dash: string | number[]; line: boolean; symbol: string | null; hollow: boolean
  facets: Map<string, string>[]      // признаки серий этого пункта (у пункта может быть несколько серий)
}
interface FacetValue { value: string; color: string | null; dash: string | number[] | null }
interface LegendModel { items: LegendItem[]; facets: { name: string; values: FacetValue[] }[]; plain: LegendItem[] }

/** Пункты легенды и ряды признаков. Ряд — признак, у которого больше одного значения; значение рисуется
 *  цветом, если он у всех его серий общий, иначе стилем линии, если общий он. */
function legendModel(chart: Chart, excludeMode: boolean, mode: HoverMode): LegendModel {
  const color = colorOf(chart)
  const items: LegendItem[] = []
  const byName = new Map<string, LegendItem>()
  for (const s of chart.series) {
    const name = key(s)
    let item = byName.get(name)
    if (!item) {
      if (!chart.series.some(o => key(o) === name && o.legend)) continue
      const first = chart.series.find(o => key(o) === name && o.legend)!
      item = {
        name, color: color(first), dash: dashOf(first), line: first.kind === 'line', hollow: first.hollow,
        symbol: first.kind === 'points' || (first.kind === 'line' && hasMarkers(first, excludeMode, mode)) ? first.symbol : null,
        facets: [],
      }
      byName.set(name, item); items.push(item)
    }
    item.facets.push(new Map(Object.entries(s.facets ?? {})))
  }
  const names: string[] = []
  for (const s of chart.series) for (const f of Object.keys(s.facets ?? {})) if (!names.includes(f)) names.push(f)
  const facets = names.map(name => {
    const values: FacetValue[] = []
    for (const s of chart.series) {
      const v = s.facets?.[name]
      if (v === undefined || values.some(o => o.value === v)) continue
      const all = chart.series.filter(o => o.facets?.[name] === v)
      const c = color(all[0]), d = dashOf(all[0])
      values.push({
        value: v, color: all.every(o => color(o) === c) ? c : null,
        dash: all.every(o => JSON.stringify(dashOf(o)) === JSON.stringify(d)) ? d : null,
      })
    }
    return { name, values }
  }).filter(f => f.values.length > 1)
  // серии без признаков (или с одним значением) остаются обычными пунктами
  const plain = facets.length ? items.filter(i => i.facets.every(f => f.size === 0)) : items
  return { items, facets, plain }
}

function Swatch({ color, dash, line, symbol, hollow }: { color: string; dash: string | number[] | null; line: boolean; symbol?: string | null; hollow?: boolean }) {
  const pattern = Array.isArray(dash) ? dash.join(' ') : undefined
  const mark = { fill: hollow ? 'var(--chart-surface)' : color, stroke: color }    // var() — только через style, не атрибут
  return (
    <svg className="legend-key" viewBox="0 0 22 12" aria-hidden="true">
      {line && <line x1="1" y1="6" x2="21" y2="6" style={{ stroke: color }} strokeWidth={2.2} strokeDasharray={pattern} strokeLinecap="round" />}
      {symbol && (symbol === 'square' ? <rect x="7.5" y="2.5" width="7" height="7" style={mark} strokeWidth={1.4} />
        : symbol === 'diamond' ? <path d="M11 1.8 15.2 6 11 10.2 6.8 6Z" style={mark} strokeWidth={1.4} />
        : symbol === 'triangle' ? <path d="M11 2 15 10H7Z" style={mark} strokeWidth={1.4} />
        : <circle cx="11" cy="6" r="3.6" style={mark} strokeWidth={1.4} />)}
      {!line && !symbol && <rect x="5" y="2" width="12" height="8" rx="2" style={{ fill: color }} />}
    </svg>
  )
}

interface LegendProps {
  model: LegendModel; hidden: Set<string>; facetOff: Set<string>; events: ChartEvent[]; offEvents: string[]
  onToggle: (name: string, only: boolean) => void; onFacet: (facet: string, value: string, only: boolean) => void
  onEvent: (kind: string) => void; onHighlight: (name: string | null) => void
}

function ChartLegend({ model, hidden, facetOff, events, offEvents, onToggle, onFacet, onEvent, onHighlight }: LegendProps) {
  const [open, setOpen] = useState(false)
  const [overflow, setOverflow] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = root.current
    if (el) setOverflow(el.scrollHeight > el.clientHeight + 2)
  })
  const kinds = EVENT_KINDS.filter(k => events.some(e => e.kind === k.kind))
  const tk = { muted: 'var(--chart-muted)', accent: 'var(--chart-accent)', faint: 'var(--chart-faint)' } as ChartTokens
  if (model.items.length < 2 && !kinds.length) return null
  const hint = 'Щелчок — скрыть или показать, двойной щелчок — только этот'
  return (
    <div className="chart-legend-wrap">
      <div ref={root} className={'chart-legend' + (open ? ' open' : '')}>
        {model.facets.map(f => (
          <div key={f.name} className="legend-row">
            <span className="legend-title">{f.name}</span>
            {f.values.map(v => (
              <button key={v.value} type="button" className="legend-item" aria-pressed={!facetOff.has(f.name + '\u0001' + v.value)} title={hint}
                onClick={e => onFacet(f.name, v.value, e.detail > 1)}>
                {(v.color || v.dash) && <Swatch color={v.color ?? 'var(--chart-ink)'} dash={v.dash} line />}
                <span>{v.value}</span>
              </button>
            ))}
          </div>
        ))}
        {model.plain.length > (model.facets.length ? 0 : 1) && (
          <div className="legend-row">
            {model.facets.length > 0 && <span className="legend-title">Кривые</span>}
            {model.plain.map(i => (
              <button key={i.name} type="button" className="legend-item" aria-pressed={!hidden.has(i.name)} title={hint}
                onClick={e => onToggle(i.name, e.detail > 1)}
                onMouseEnter={() => onHighlight(i.name)} onMouseLeave={() => onHighlight(null)}>
                <Swatch color={i.color} dash={i.dash} line={i.line} symbol={i.symbol} hollow={i.hollow} />
                <span>{i.name}</span>
              </button>
            ))}
          </div>
        )}
        {kinds.length > 0 && (
          <div className="legend-row">
            <span className="legend-title">События</span>
            {kinds.map(k => (
              <button key={k.kind} type="button" className="legend-item" aria-pressed={!offEvents.includes(k.kind)}
                title="Показать или скрыть отметки на всех графиках" onClick={() => onEvent(k.kind)}>
                <svg className="legend-key" viewBox="0 0 22 12" aria-hidden="true">
                  <path d="M7 1h8l-4 6Z" style={{ fill: eventColor(k.kind, tk) }} />
                  <line x1="11" y1="7" x2="11" y2="12" style={{ stroke: eventColor(k.kind, tk) }} strokeDasharray="2 1.5" />
                </svg>
                <span>{k.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {(overflow || open) && (
        <button type="button" className="legend-more" onClick={() => setOpen(o => !o)}>
          {open ? 'Свернуть легенду' : `Вся легенда (${model.items.length})`}
        </button>
      )}
    </div>
  )
}

const count = (n: number) => n.toLocaleString('ru-RU')

/** Пометка «показана часть точек»: линии прорежены методом М4 (пики и провалы сохранены), все точки — при увеличении. */
function ThinNote({ chart, thinned, windowed, patch }: { chart: Chart; thinned: number[]; windowed: boolean; patch: Patch | null }) {
  let shown = 0, total = 0
  for (const i of thinned) {
    const s = chart.series[i]
    shown += s.x.length
    total += windowed && patch?.series[i] ? patch.series[i].window : s.total
  }
  const part = shown < total
  const where = windowed ? ' в видимой области' : ''
  return (
    <span className={'chart-thin' + (part ? ' part' : '')}
      title={'Линии прорежены методом М4: на каждый участок оставлены первая, последняя, наибольшая и наименьшая точки и разрывы, пики и провалы не теряются. '
        + 'Увеличьте масштаб или включите «Замеры» — подгрузятся все точки видимой области. Таблицы и выгрузки графиков (PNG, SVG, PDF, CSV, XLSX) всегда содержат все данные.'}>
      {part ? `Показано ${count(shown)} из ${count(total)} точек${where} · увеличьте масштаб для всех` : `Все точки${where}: ${count(total)}`}
    </span>
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

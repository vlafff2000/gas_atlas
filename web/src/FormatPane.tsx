// Панель «Формат» (как «Формат диаграммы» в Excel): один компонент для всех графиков Атласа. Слева выбор элемента — график,
// оси, ряды; справа его настройки. Меняет график сразу. Оформление графика и осей пишется на выбранный уровень (раздел или
// весь проект), вид рядов — в тему проекта по ключу ряда (один и тот же год или группа выглядит одинаково везде).
import type { Axis, Chart, Series } from './api'
import { Dialog } from './BuilderDialogs'
import { SeriesLookFields } from './ChartSettings'
import type { AxisFormat, AxisName, ChartFormat } from './chartFormat'
import { seriesLookKey, type Look } from './chartStyle'
import { AxisStyleFields, ChartStyleFields, SeriesExtraFields, compact } from './FormatFields'
import type { FormatScope } from './projectLooks'

const KIND: Record<Series['kind'], string> = { line: 'линия', points: 'точки', bar: 'столбцы', box: 'ящики' }
const AXES: AxisName[] = ['x', 'y', 'y2', 'y3', 'y4', 'y5']
const AXIS_TITLE: Record<AxisName, string> = { x: 'Ось X', y: 'Ось Y', y2: 'Ось Y2', y3: 'Ось Y3', y4: 'Ось Y4', y5: 'Ось Y5' }

/** Элемент панели: 'chart', 'axis:y2' или 'series:3'. */
export type FormatElement = string

interface Props {
  chart: Chart
  element: FormatElement
  onElement: (e: FormatElement) => void
  scope: FormatScope
  onScope: (s: FormatScope) => void
  /** Оформление графика и осей выбранного уровня. */
  doc: ChartFormat
  onDoc: (doc: ChartFormat) => void
  colorOf: (s: Series) => string
  looks: Record<string, Look>
  onLooks: (next: Record<string, Look>) => void
  onClose: () => void
}

export function FormatPane({ chart, element, onElement, scope, onScope, doc, onDoc, colorOf, looks, onLooks, onClose }: Props) {
  const axes = AXES.filter(n => n === 'x' || n === 'y' || chart[n])
  const [kind, id] = element.split(':')
  const axisName = (kind === 'axis' && axes.includes(id as AxisName) ? id : 'x') as AxisName
  const s = kind === 'series' ? chart.series[Math.min(Number(id) || 0, chart.series.length - 1)] : undefined
  const setChart = (patch: object) => onDoc({ ...doc, chart: compact({ ...doc.chart, ...patch }) })
  const setAxis = (patch: Partial<AxisFormat>) => onDoc({ ...doc, axes: { ...doc.axes, [axisName]: compact({ ...doc.axes?.[axisName], ...patch }) } })
  const setLook = (patch: Partial<Look>) => { if (s) { const k = seriesLookKey(s); onLooks({ ...looks, [k]: compact({ ...looks[k], ...patch }) }) } }
  const axis: Axis | null | undefined = chart[axisName]
  const look: Look = (s && looks[seriesLookKey(s)]) || {}

  return (
    <Dialog title="Формат" subtitle={chart.title} onClose={onClose} dockRight>
      <div className="cs-scope">
        Оформление графика и осей действует на:
        <select value={scope} onChange={e => onScope(e.target.value as FormatScope)} aria-label="Уровень оформления">
          <option value="type">графики этого раздела</option>
          <option value="project">все графики проекта</option>
        </select>
      </div>
      <div className="cs-body">
        <ul className="cs-list">
          <li><button type="button" aria-pressed={kind === 'chart'} onClick={() => onElement('chart')}><i style={{ background: 'var(--line)' }} /><span>График</span></button></li>
          {axes.map(n => (
            <li key={n}><button type="button" aria-pressed={kind === 'axis' && axisName === n} onClick={() => onElement('axis:' + n)}>
              <i style={{ background: chart[n]?.color ?? 'var(--line)' }} /><span>{AXIS_TITLE[n]}</span></button></li>))}
          {chart.series.map((item, i) => (
            <li key={'s' + i}><button type="button" aria-pressed={kind === 'series' && s === item} onClick={() => onElement('series:' + i)} title={item.name}>
              <i style={{ background: colorOf(item) }} /><span>{item.name}</span></button></li>))}
        </ul>
        <div className="cs-editor">
          {kind === 'chart' && <>
            <h3>График</h3>
            <ChartStyleFields value={doc.chart ?? {}} set={setChart} />
            <div className="cs-actions">
              <button type="button" onClick={() => onDoc({ ...doc, chart: undefined })} disabled={!doc.chart || !Object.keys(doc.chart).length}>Сбросить график</button>
            </div>
          </>}
          {kind === 'axis' && <>
            <h3>{AXIS_TITLE[axisName]}{axis?.label ? <small> {axis.label}</small> : null}</h3>
            <AxisStyleFields value={doc.axes?.[axisName] ?? {}} set={setAxis} time={axis?.scale === 'time'} />
            <p className="cs-hint">Границы и шаг осей Y задаются на самом графике: двойной щелчок по оси.</p>
            <div className="cs-actions">
              <button type="button" onClick={() => onDoc({ ...doc, axes: { ...doc.axes, [axisName]: undefined } })} disabled={!doc.axes?.[axisName]}>Сбросить ось</button>
            </div>
          </>}
          {s && <>
            <h3>{s.name} <small>{KIND[s.kind]}</small></h3>
            <SeriesLookFields s={s} color={colorOf(s)} look={look} onChange={setLook} />
            <SeriesExtraFields value={look} set={setLook} marker={s.kind === 'points' || (s.kind === 'line' && !s.fill)} labels={s.kind !== 'box'} />
            <p className="cs-hint">Вид ряда общий для проекта: тот же год, сезон или группа выглядит так же на всех графиках.</p>
            <div className="cs-actions">
              <button type="button" disabled={!looks[seriesLookKey(s)]}
                onClick={() => { const next = { ...looks }; delete next[seriesLookKey(s)]; onLooks(next) }}>Сбросить ряд</button>
            </div>
          </>}
          <div className="cs-actions">
            <button type="button" onClick={() => { onDoc({}); onLooks({}) }}>Сбросить всё: график, оси и ряды</button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

// Панель «Формат» (как «Формат диаграммы» в Excel): один компонент для всех графиков Атласа. Слева выбор элемента — график,
// оси, ряды; справа его настройки. Меняет график сразу. Оформление графика и осей пишется на выбранный уровень (раздел или
// весь проект), вид рядов — в тему проекта по ключу ряда (один и тот же год или группа выглядит одинаково везде).
import { useState } from 'react'
import type { Axis, Chart, Series } from './api'
import { Dialog } from './BuilderDialogs'
import { SeriesLookFields } from './ChartSettings'
import { projectFormats, usePref } from './chartPrefs'
import type { AxisFormat, AxisName, ChartFormat } from './chartFormat'
import { seriesLookKey, type Look } from './chartStyle'
import { AxisStyleFields, ChartStyleFields, Commit, SeriesExtraFields, compact } from './FormatFields'
import type { FormatScope } from './projectLooks'

const KIND: Record<Series['kind'], string> = { line: 'линия', points: 'точки', bar: 'столбцы', box: 'ящики' }
const AXES: AxisName[] = ['x', 'y', 'y2', 'y3', 'y4', 'y5']
const AXIS_TITLE: Record<AxisName, string> = { x: 'Ось X', y: 'Ось Y', y2: 'Ось Y2', y3: 'Ось Y3', y4: 'Ось Y4', y5: 'Ось Y5' }

/** «Формат по образцу» (кисть Excel): скопированное оформление графика, оси или ряда; держится, пока открыта страница. */
let painter: { kind: 'chart' | 'axis' | 'series'; value: object } | null = null

const FIELD_LIMIT = 100
/** Шаблоны оформления проекта: сохранить, применить, перенести как JSON. */
function TemplateBar({ current, onReplace }: { current: ChartFormat; onReplace: (doc: ChartFormat) => void }) {
  const store = usePref(projectFormats)
  const templates = store.templates ?? {}
  const names = Object.keys(templates).sort((a, b) => a.localeCompare(b, 'ru'))
  const [picked, setPicked] = useState('')
  const [name, setName] = useState('')
  const [json, setJson] = useState<string | null>(null)
  const [error, setError] = useState('')
  const chosen = templates[picked] ? picked : ''
  const put = (next: Record<string, ChartFormat>) => projectFormats.set({ ...store, templates: Object.keys(next).length ? next : undefined })
  const save = () => {
    const key = name.trim().slice(0, 60)
    if (!key) { setError('Введите название шаблона'); return }
    if ((!(key in templates) && names.length >= FIELD_LIMIT)) { setError(`Шаблонов не больше ${FIELD_LIMIT}`); return }
    setError(''); put({ ...templates, [key]: current }); setPicked(key); setName('')
  }
  const drop = () => { const next = { ...templates }; delete next[chosen]; put(next); setPicked('') }
  const load = () => {
    try {
      const raw = JSON.parse(json ?? '') as { name?: string; format?: ChartFormat }
      if (!raw || typeof raw !== 'object' || !raw.format || typeof raw.format !== 'object') throw new Error('нет поля format')
      const key = String(raw.name ?? 'Импортированный').trim().slice(0, 60) || 'Импортированный'
      put({ ...templates, [key]: raw.format }); setPicked(key); setJson(null); setError('')
    } catch (e) { setError('Не получилось прочитать шаблон: ' + (e as Error).message) }
  }
  return (
    <details className="cs-templates">
      <summary>Шаблоны оформления{names.length ? ` (${names.length})` : ''}</summary>
      <div className="cs-tpl-row">
        <select value={chosen} onChange={e => setPicked(e.target.value)} aria-label="Шаблон оформления">
          <option value="">— выберите шаблон —</option>
          {names.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <button type="button" disabled={!chosen} onClick={() => onReplace(templates[chosen])} title="Заменяет оформление графика, осей и рядов на этом уровне">Применить</button>
        <button type="button" disabled={!chosen} onClick={drop}>Удалить</button>
        <button type="button" disabled={!chosen} onClick={() => setJson(JSON.stringify({ name: chosen, format: templates[chosen] }, null, 1))}>В текст</button>
      </div>
      <div className="cs-tpl-row">
        <input value={name} placeholder="Название нового шаблона" maxLength={60} onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') save() }} aria-label="Название шаблона" />
        <button type="button" onClick={save} title="Сохраняет оформление графика, осей и рядов, которое сейчас на этом уровне">Сохранить текущее</button>
        <button type="button" onClick={() => setJson(json === null ? '' : null)}>Из текста</button>
      </div>
      {json !== null && <>
        <textarea className="cs-tpl-json" value={json} rows={6} onChange={e => setJson(e.target.value)} aria-label="Шаблон как текст"
          placeholder="Вставьте сюда текст шаблона из другого проекта" />
        <div className="cs-actions"><button type="button" onClick={load} disabled={!json.trim()}>Добавить в шаблоны</button></div>
      </>}
      {error && <p className="cs-hint" role="alert">{error}</p>}
    </details>
  )
}

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
  /** Заменяет всё оформление уровня целиком (шаблон): график, оси и ряды. */
  onReplace: (doc: ChartFormat) => void
  /** Оформление одного графика (страница выгрузки): вместо выбора уровня показывается подпись. */
  scopeLabel?: string
}

/** «Копировать формат» / «Вставить формат» для графика, оси или ряда: вставляется только в элемент того же вида. */
function Brush({ kind, value, paste }: { kind: 'chart' | 'axis' | 'series'; value: object | undefined; paste: (v: object) => void }) {
  const [, tick] = useState(0)
  const same = painter?.kind === kind
  return <>
    <button type="button" disabled={!value || !Object.keys(value).length} title="Запомнить оформление этого элемента"
      onClick={() => { painter = { kind, value: JSON.parse(JSON.stringify(value)) as object }; tick(n => n + 1) }}>Копировать формат</button>
    <button type="button" disabled={!same} title={same ? 'Перенести запомненное оформление сюда' : 'Сначала скопируйте формат такого же элемента'}
      onClick={() => painter && paste(painter.value)}>Вставить формат</button>
  </>
}

export function FormatPane({ chart, element, onElement, scope, onScope, doc, onDoc, colorOf, looks, onLooks, onClose, onReplace, scopeLabel }: Props) {
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
        {scopeLabel ? <b>{scopeLabel}</b> : (
          <select value={scope} onChange={e => onScope(e.target.value as FormatScope)} aria-label="Уровень оформления">
            <option value="type">графики этого раздела</option>
            <option value="project">все графики проекта</option>
          </select>)}
      </div>
      <TemplateBar current={{ ...doc, series: Object.keys(looks).length ? looks : undefined }} onReplace={onReplace} />
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
              <Brush kind="chart" value={doc.chart} paste={v => setChart(v)} />
              <button type="button" onClick={() => onDoc({ ...doc, chart: undefined })} disabled={!doc.chart || !Object.keys(doc.chart).length}>Сбросить график</button>
            </div>
          </>}
          {kind === 'axis' && <>
            <h3>{AXIS_TITLE[axisName]}{axis?.label ? <small> {axis.label}</small> : null}</h3>
            <AxisStyleFields value={doc.axes?.[axisName] ?? {}} set={setAxis} time={axis?.scale === 'time'} />
            {(axis?.scale === 'value' || axis?.scale === 'time') && <fieldset>
              <legend>Разрыв оси</legend>
              <div className="cs-row">
                <Commit label="Вырезать от" value={doc.axes?.[axisName]?.break_from} placeholder={axis.scale === 'time' ? 'дд.мм.гггг' : 'число'} onChange={v => setAxis({ break_from: v || undefined })} />
                <Commit label="до" value={doc.axes?.[axisName]?.break_to} placeholder={axis.scale === 'time' ? 'дд.мм.гггг' : 'число'} onChange={v => setAxis({ break_to: v || undefined })} />
              </div>
              <p className="cs-hint">Диапазон между значениями не показывается, на оси ставится знак разрыва. Применяется, когда заполнены оба поля (Enter или выход из поля).</p>
            </fieldset>}
            <p className="cs-hint">Границы и шаг осей Y задаются на самом графике: двойной щелчок по оси.</p>
            <div className="cs-actions">
              <Brush kind="axis" value={doc.axes?.[axisName]} paste={v => setAxis(v as Partial<AxisFormat>)} />
              <button type="button" onClick={() => onDoc({ ...doc, axes: { ...doc.axes, [axisName]: undefined } })} disabled={!doc.axes?.[axisName]}>Сбросить ось</button>
            </div>
          </>}
          {s && <>
            <h3>{s.name} <small>{KIND[s.kind]}</small></h3>
            <SeriesLookFields s={s} color={colorOf(s)} look={look} onChange={setLook} />
            <SeriesExtraFields value={look} set={setLook} marker={s.kind === 'points' || (s.kind === 'line' && !s.fill)} labels={s.kind !== 'box'} trend={s.kind === 'points' || s.kind === 'line'} hatch={s.kind === 'bar'} />
            <p className="cs-hint">Вид ряда общий для проекта: тот же год, сезон или группа выглядит так же на всех графиках.</p>
            <div className="cs-actions">
              <Brush kind="series" value={looks[seriesLookKey(s)]} paste={v => setLook(v as Partial<Look>)} />
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

// Экспорт → «Любой график»: выбрать график любого раздела и выгрузить его с полной ручной настройкой (atlas/export_any.py).
// Пустое поле — «авто» (как задал модуль): всё, что поменял инженер, главнее.
// Выбор и настройки каждого графика хранятся в проекте (``settings.export_any``); график без своих настроек берёт вид с экрана.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { saveFileWithPicker } from './desktopDownload'
import { api, defaults, type Chart, type ModuleSpec, type Params, type Project } from './api'
import { ChartView } from './ChartView'
import type { ChartFormat } from './chartFormat'
import { ParamBar } from './ParamBar'
import { Check, Section, Select, SizePick, Text, type Opt } from './exportFields'
import { savedRanges, seriesLooks } from './chartPrefs'
import { anyApi, type AnyChartInfo, type AnyModule, type AnySettings, type AnyStore, type Form } from './api_projects'

const FORMATS: Opt[] = [['png', 'PNG'], ['svg', 'SVG'], ['pdf', 'PDF'], ['xlsx', 'Excel (данные)'], ['csv', 'CSV (данные)']]
const FONTS: Opt[] = [['default', 'Стандартный (DejaVu Sans)'], ['times', 'Times New Roman'], ['arial_narrow', 'Arial Narrow'], ['calibri', 'Calibri (как в Excel)']]
const AXIS_NAME: Record<string, string> = { x: 'Ось X', y: 'Ось Y', y2: 'Ось Y2 (справа)', y3: 'Ось Y3', y4: 'Ось Y4', y5: 'Ось Y5' }
const EXTRA_FORMATS: Opt[] = [['svg', 'SVG'], ['pdf', 'PDF'], ['xlsx', 'Excel'], ['csv', 'CSV']]
const FACET_SEP = '\u0001'      // как на экране: 'Признак\u0001значение'
const DPIS = [150, 200, 250, 300, 600, 1200]
const KIND_NOTE: Record<string, string> = {
  heat: 'Тепловая карта: действуют размер рисунка, шрифты, текст в ячейках, заголовок и фон.',
  strips: 'Матрица скважин × сезонов: действуют размер рисунка, шрифты, текст в ячейках, заголовок и фон.',
  stack: 'Столбцы с подписями в сегментах: действуют размер, шрифт, легенда (справа, сверху, снизу или скрыть), заголовок, подписи в столбцах и таблица под графиком.',
}

type Dict = Record<string, unknown>
const put = (obj: Dict, key: string, value: unknown): Dict => {
  const next = { ...obj }
  if (value === '' || value === undefined || value === null) delete next[key]
  else next[key] = value
  return next
}

function Box({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="param-section" aria-label={title}>
      <span className="param-title" aria-hidden="true">{title}</span>
      <div className="param-fields">{children}</div>
    </fieldset>
  )
}

/** Число или пустое поле («авто»); текст держится отдельно, пока вводят. */
function Field({ label, value, onChange, placeholder, wide, type = 'text' }:
  { label: string; value: unknown; onChange: (v: string) => void; placeholder?: string; wide?: boolean; type?: 'text' | 'number' }) {
  return (
    <label className={'field' + (wide ? ' wide' : '') + (type === 'number' ? ' number' : '')}>
      <span className="field-label">{label}</span>
      <input type={type} value={value === undefined ? '' : String(value)} placeholder={placeholder ?? 'авто'} maxLength={300} onChange={e => onChange(e.target.value)} />
    </label>
  )
}

/** Вид графика на экране: личный вид рядов («Настройка») и ручные границы осей Y (двойной щелчок по оси). */
/** Старые настройки формы (оформление графика и вид рядов) переносятся в оформление графика (doc): их правит панель «Формат».
 *  Заголовок и границы осей остаются в форме. Уже заданное в doc главнее перенесённого. */
function legacyToDoc(s: AnySettings): { settings: AnySettings; moved: boolean } {
  const chart = { ...((s.chart as Dict | undefined) ?? {}) }
  const title = chart.title
  delete chart.title
  const view = { ...((s.view as Dict | undefined) ?? {}) }
  const looks = view.looks as Record<string, unknown> | undefined
  if (!Object.keys(chart).length && !looks) return { settings: s, moved: false }
  const old = ((s as { doc?: ChartFormat }).doc ?? {}) as ChartFormat
  const doc: ChartFormat = { ...old, chart: { ...chart, ...old.chart }, ...(looks ? { series: { ...(looks as Record<string, never>), ...old.series } } : {}) }
  if (!Object.keys(doc.chart ?? {}).length) delete doc.chart
  const next: Dict = { ...s, doc }
  if (title) next.chart = { title }; else delete next.chart
  if (looks) { delete view.looks; if (Object.keys(view).length) next.view = view; else delete next.view }
  return { settings: next, moved: true }
}

function screenView(chart: AnyChartInfo): Dict {
  const all = seriesLooks.get()
  const looks = Object.fromEntries(chart.items.filter(it => all[it.key]).map(it => [it.key, all[it.key]]))
  const saved = chart.range_key !== undefined ? savedRanges.get()[chart.range_key] ?? {} : {}
  const ranges = Object.fromEntries(Object.entries(saved).filter(([, r]) => Array.isArray(r)))
  return { ...(Object.keys(looks).length ? { looks } : {}), ...(Object.keys(ranges).length ? { ranges } : {}) }
}

const SAVE_DELAY = 800      // мс: настройки пишутся в проект с паузой, а не на каждое нажатие
const MAX_CHARTS = 300      // графиков со своими настройками в проекте (то же число в atlas/projects.py)

function Tick({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return <label className="toggle"><input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} /><span>{label}</span></label>
}


export function ExportAnyChart({ project, onProject }: { project: Project; onProject: (p: Project) => void }) {
  const [specs, setSpecs] = useState<ModuleSpec[]>([])
  const [ready, setReady] = useState<Record<string, AnyModule>>({})
  const [moduleId, setModuleId] = useState('')
  const [params, setParams] = useState<Params>({})
  const [charts, setCharts] = useState<AnyChartInfo[]>([])
  const [note, setNote] = useState('')
  const [chartId, setChartId] = useState('')
  const [settings, setSettings] = useState<AnySettings>({})
  const [image, setImage] = useState<string | null>(null)
  const [live, setLive] = useState<Chart | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [extraFormats, setExtraFormats] = useState<string[]>([])
  const seq = useRef(0)                   // запросы перечня графиков: ответ на устаревший отбрасывается
  const previewSeq = useRef(0)            // запросы предпросмотра — свой счётчик, чтобы не гасить перечень
  // Ревизия данных: своё же сохранение настроек тоже меняет ревизию проекта, но перечень и предпросмотр от него не пересчитываются.
  const ownRevision = useRef<number | null>(null)
  const [dataRevision, setDataRevision] = useState(project.revision)
  useEffect(() => { if (project.revision !== ownRevision.current) setDataRevision(project.revision) }, [project.revision])
  const store = (project.settings.export_any ?? {}) as AnyStore
  const storeRef = useRef(store)
  storeRef.current = store
  const restored = useRef(false)          // последний выбор из проекта уже восстановлен
  const loadedKey = useRef('')            // для какого графика сейчас в форме настройки
  const edited = useRef(false)            // настройки этого графика менял инженер: их надо сохранить

  useEffect(() => {
    api.modules().then(setSpecs).catch(e => setError((e as Error).message))
    anyApi.modules(project.id).then(r => setReady(Object.fromEntries(r.modules.map(m => [m.id, m])))).catch(() => undefined)
  }, [project.id, dataRevision])

  // Последний выбор (раздел, параметры, график) — из проекта, один раз после загрузки списка разделов.
  useEffect(() => {
    if (restored.current || !specs.length) return
    restored.current = true
    const last = storeRef.current.last
    const s = last && specs.find(x => x.id === last.module)
    if (!last || !s) return
    setModuleId(s.id); setParams({ ...defaults(s), ...last.params }); setChartId(last.chart)
  }, [specs])

  const spec = specs.find(s => s.id === moduleId)
  const groups = useMemo(() => {
    const by = new Map<string, ModuleSpec[]>()
    for (const s of [...specs].sort((a, b) => a.order - b.order)) by.set(s.group, [...(by.get(s.group) ?? []), s])
    const known = new Set(specs.map(s => s.id))
    for (const m of Object.values(ready)) if (!known.has(m.id)) by.set(m.group, [...(by.get(m.group) ?? []), { id: m.id, title: m.title, group: m.group, order: m.order } as ModuleSpec])
    return [...by.entries()]
  }, [specs, ready])
  const chart = charts.find(c => c.id === chartId)
  const chartGroups = useMemo(() => {
    const by = new Map<string, AnyChartInfo[]>()
    for (const c of charts) by.set(c.group || 'Графики', [...(by.get(c.group || 'Графики') ?? []), c])
    return [...by.entries()]
  }, [charts])
  const pickModule = (id: string) => {
    restored.current = true
    const s = specs.find(x => x.id === id)
    setExtraFormats([])
    setModuleId(id); setChartId(''); setCharts([]); setNote(''); setImage(null)
    setParams(s ? defaults(s) : {})
  }

  // Перечень графиков раздела при выбранных параметрах.
  const paramsKey = JSON.stringify(params)
  useEffect(() => {
    if (!moduleId) return
    const mine = ++seq.current
    setBusy('charts'); setError(null)
    const timer = setTimeout(() => {
      anyApi.charts(project.id, moduleId, params).then(r => {
        if (mine !== seq.current) return
        setCharts(r.charts); setNote(r.note)
        setChartId(id => r.charts.some(c => c.id === id) ? id : (r.charts[0]?.id ?? ''))
      }).catch(e => { if (mine === seq.current) { setCharts([]); setError((e as Error).message) } })
        .finally(() => { if (mine === seq.current) setBusy(null) })
    }, 400)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, paramsKey, project.id, dataRevision])

  // Настройки выбранного графика: сохранённые в проекте, иначе — вид с экрана (не сохраняется, пока его не поменяют).
  const chartKey = moduleId && chartId ? `${moduleId}::${chartId}` : ''
  useEffect(() => {
    if (!chart || !chartKey || loadedKey.current === chartKey) return
    loadedKey.current = chartKey
    edited.current = false
    const own = storeRef.current.charts?.[chartKey]
    if (own) {
      const m = legacyToDoc(own)
      if (m.moved) edited.current = true
      setSettings(m.settings); return
    }
    const view = screenView(chart)
    setSettings(Object.keys(view).length ? { view } : {})
  }, [chart, chartKey])

  // Сохранение в проект: последний выбор и изменённые инженером настройки графиков; одинаковое повторно не пишется.
  // Изменённое запоминается сразу (pending), а пишется с паузой: переход к другому графику или уход со вкладки его не теряет.
  const settingsKey = JSON.stringify(settings)
  const pending = useRef<Record<string, AnySettings>>({})
  const selection = useRef<AnyStore['last']>(undefined)
  const saving = useRef(false)
  const again = useRef(false)
  const flush = useRef(() => undefined as void)
  flush.current = () => {
    if (saving.current) { again.current = true; return }
    const old = storeRef.current
    const charts = { ...(old.charts ?? {}) }
    for (const [k, v] of Object.entries(pending.current)) {
      delete charts[k]
      if (Object.keys(v).length) charts[k] = v          // последний изменённый — в конце: при переполнении вытесняются самые старые
    }
    pending.current = {}
    const keys = Object.keys(charts)
    for (const k of keys.slice(0, Math.max(0, keys.length - MAX_CHARTS))) delete charts[k]
    const last = selection.current ?? old.last
    const next: AnyStore = { ...(last ? { last } : {}), ...(Object.keys(charts).length ? { charts } : {}) }
    if (JSON.stringify(next) === JSON.stringify(old)) return
    saving.current = true
    api.saveSettings(project.id, { export_any: next })
      .then(p => { storeRef.current = (p.settings.export_any ?? {}) as AnyStore; ownRevision.current = p.revision; onProject(p) })
      .catch(e => setError((e as Error).message))
      .finally(() => { saving.current = false; if (again.current) { again.current = false; flush.current() } })
  }
  useEffect(() => {
    if (!restored.current || !moduleId || !chartId || loadedKey.current !== chartKey) return
    selection.current = { module: moduleId, chart: chartId, params }
    if (edited.current) pending.current[chartKey] = settings
    const timer = window.setTimeout(() => flush.current(), SAVE_DELAY)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsKey, moduleId, chartId, paramsKey, chartKey])
  useEffect(() => () => flush.current(), [])     // уход со вкладки: несохранённое пишется сразу

  // Живой вид: график с оформлением проекта и настройками формы; оформление самого графика (doc) накладывает экран сразу.
  const { doc: _doc, ...formSettings } = settings as AnySettings & { doc?: unknown }
  const formKey = JSON.stringify(formSettings)
  useEffect(() => {
    if (!moduleId || !chart?.id || chart.special) { setLive(null); return }
    let alive = true
    const timer = setTimeout(() => {
      anyApi.chart(project.id, moduleId, params, chart.id, formSettings).then(c => alive && setLive(c)).catch(e => alive && setError((e as Error).message))
    }, 400)
    return () => { alive = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, chart?.id, formKey, paramsKey, project.id, dataRevision])
  const doc = ((settings as { doc?: ChartFormat }).doc ?? {}) as ChartFormat
  const onDoc = (next: ChartFormat) => change(s => put(s, 'doc', Object.keys(JSON.parse(JSON.stringify(next))).length ? next : ''))

  // Предпросмотр: тот же файл, что уйдёт на выгрузку, PNG 150 DPI.
  const shownId = chart?.id ?? ''         // предпросмотр — только у графика, который есть в перечне
  useEffect(() => {
    if (!moduleId || !shownId) return
    const mine = ++previewSeq.current
    const timer = setTimeout(() => {
      setBusy('preview')
      anyApi.file(project.id, moduleId, params, shownId, { ...settings, format: 'png', dpi: 150 }).then(r => {
        if (mine !== previewSeq.current) return
        setImage(old => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(r.blob) })
        setNotes(r.notes); setError(null)
      }).catch(e => { if (mine === previewSeq.current) { setError((e as Error).message); setImage(null) } })
        .finally(() => { if (mine === previewSeq.current) setBusy(null) })
    }, 500)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, shownId, settingsKey, paramsKey, project.id, dataRevision])

  // Любое изменение инженером — через change: настройки графика после этого сохраняются в проекте.
  const change = (fn: (s: AnySettings) => AnySettings) => { edited.current = true; setSettings(fn) }
  const set = (key: string, value: unknown) => change(s => put(s, key, value))
  const sub = (group: 'chart' | 'axes' | 'labels' | 'table', key: string, value: unknown) => change(s => {
    const next = put((s[group] as Dict | undefined) ?? {}, key, value)
    return put(s, group, Object.keys(next).length ? next : '')
  })
  const axis = (name: string, key: string, value: unknown) => change(s => {
    const all = (s.axes as Dict | undefined) ?? {}
    const one = put((all[name] as Dict | undefined) ?? {}, key, value)
    const next = put(all, name, Object.keys(one).length ? one : '')
    return put(s, 'axes', Object.keys(next).length ? next : '')
  })
  const setView = (fn: (v: Dict) => Dict) => change(s => {
    const next = fn((s.view as Dict | undefined) ?? {})
    return put(s, 'view', Object.keys(next).length ? next : '')
  })
  const setHidden = (group: string, hide: boolean) => setView(v => {
    const list = ((v.hidden as string[] | undefined) ?? []).filter(g => g !== group)
    return put(v, 'hidden', hide ? [...list, group] : list.length ? list : '')
  })
  const fromScreen = chart ? screenView(chart) : {}
  // рядам с экрана — их вид поверх уже заданного здесь; границы осей — как на экране
  const takeScreen = () => setView(v => ({ ...v, ...fromScreen,
    ...(fromScreen.looks ? { looks: { ...(v.looks as Dict | undefined), ...(fromScreen.looks as Dict) } } : {}) }))
  const chartStyle = (settings.chart as Dict | undefined) ?? {}
  const axes = (settings.axes as Dict | undefined) ?? {}
  const labels = (settings.labels as Dict | undefined) ?? {}
  const special = chart?.special ?? false
  const format = (settings.format as string | undefined) ?? 'png'
  // Общие поля — те же компоненты и подписи, что у «Производительность скважин»; значения берутся из настроек выгрузки.
  const form: Form = { format, dpi: settings.dpi, look: settings.look, width: settings.width, height: settings.height, font: settings.font,
    font_size: settings.font_size, angle: settings.angle, legend: chartStyle.legend, title: chartStyle.title, title_align: chartStyle.title_align, grid: chartStyle.grid,
    grid_width: chartStyle.grid_width, minor_grid: chartStyle.minor_grid, minor_grid_width: chartStyle.minor_grid_width,
    table_show: (settings.table as Dict | undefined)?.show !== false }
  const setField = (field: string, value: unknown) => {
    if (field === 'format') set('format', value === 'png' ? '' : value)
    else if (field === 'dpi') set('dpi', Number(value) === 300 ? '' : value)
    else if (field === 'look' || field === 'font') set(field, value === 'default' ? '' : value)
    else if (field === 'legend') sub('chart', 'legend', value === 'auto' ? '' : value)
    else if (['title', 'title_align', 'grid', 'grid_width', 'minor_grid', 'minor_grid_width'].includes(field)) sub('chart', field, value === 'auto' ? '' : value)
    else if (field === 'angle') set('angle', value === 'auto' ? '' : value)
    else if (field === 'table_show') sub('table', 'show', value ? '' : false)
    else set(field, value)
  }
  const F = { form, set: setField }

  const download = async () => {
    if (!chart) return
    setBusy('download'); setError(null)
    try {
      // основной формат и отмеченные дополнительные: каждый файл — через наш проводник «Сохранить как»
      for (const f of [format, ...extraFormats.filter(x => x !== format)]) {
        const r = await anyApi.file(project.id, moduleId, params, chartId, { ...settings, format: f })
        await saveFileWithPicker(r.blob, r.name)
        setNotes(r.notes)
      }
    } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }

  return (
    <>
      <p className="lede">Любой график любого раздела: выберите раздел, сезон и график из общего списка — и настройте выгрузку именно этого графика. Пустое поле — как задал раздел.</p>
      <div className="param-bar flat">
        <Box title="Раздел">
          <label className="field wide">
            <span className="field-label">Раздел программы</span>
            <select value={moduleId} onChange={e => pickModule(e.target.value)}>
              <option value="">— выберите —</option>
              {groups.map(([group, items]) => (
                <optgroup key={group} label={group}>
                  {items.map(s => <option key={s.id} value={s.id} disabled={ready[s.id] ? !ready[s.id].ready : false}>
                    {s.title}{ready[s.id] && !ready[s.id].ready ? ` (нет данных: ${ready[s.id].missing.join(', ')})` : ''}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
        </Box>
      </div>
      {spec && <ParamBar key={spec.id} spec={spec} project={project.id} panel={0} values={params} onChange={setParams} />}
      {charts.length > 0 && (
        <div className="param-bar flat">
          <Box title="График">
            <label className="field wide">
              <span className="field-label">Все графики раздела ({charts.length})</span>
              <select value={chartId} onChange={e => setChartId(e.target.value)}>
                {chartGroups.map(([group, items]) => (
                  <optgroup key={group} label={group}>
                    {items.map(c => <option key={c.id} value={c.id}>{c.title || c.id}{c.table ? ' · с таблицей' : ''}</option>)}
                  </optgroup>
                ))}
              </select>
            </label>
          </Box>
        </div>
      )}
      {error && <div className="note warning" role="alert">{error}</div>}
      {moduleId && !busy && charts.length === 0 && !error && <div className="note info">{note || 'Графиков нет.'}</div>}

      {chart && (
        <>
          {special && <div className="note info">{KIND_NOTE[chart.kind] ?? 'Размер, шрифт и оформление этого графика пока задаются самим графиком.'}</div>}
          <div className="param-bar">
            <Section title="Общие параметры файлов">
              <Select {...F} field="format" label="Формат" def="png" options={FORMATS} />
              <Select {...F} field="dpi" label="Разрешение, DPI" def={300} options={DPIS.map(d => [d, String(d)] as Opt)} />
              <SizePick {...F} />
              <Select {...F} field="font" label="Шрифт" def="default" options={FONTS} />
              <Select {...F} field="look" label="Вид графиков" def="default" options={[['default', 'Обычный'], ['excel', 'Как диаграммы Excel']]} />
              <Select {...F} field="font_size" label="Размер шрифта, пт" def={null}
                options={[[null, 'Авто (9)'], ...[7, 8, 9, 10, 11, 12, 14].map(n => [n, String(n)] as Opt)]} />
              <Text {...F} field="title" label="Заголовок графика" def="" wide />
              <Select {...F} field="angle" label="Подписи оси X" def="auto"
                options={[['auto', 'Как есть'], ['0', 'Горизонтально'], ['30', '30°'], ['45', '45°'], ['60', '60°'], ['90', 'Вертикально']]} />
              <Field label="Имя файла (без расширения)" wide value={settings.filename} placeholder="по заголовку графика" onChange={v => set('filename', v)} />
              {(chart.kind === 'heat' || chart.kind === 'strips') && (
                <Field label="Текст в ячейках, пт (4–30)" type="number" value={settings.cell_size} onChange={v => set('cell_size', v === '' ? '' : Number(v))} />
              )}
              {EXTRA_FORMATS.filter(f => f[0] !== format).map(f => (
                <Tick key={String(f[0])} label={'Сохранить также: ' + f[1]} value={extraFormats.includes(f[0] as string)}
                  onChange={on => setExtraFormats(l => on ? [...l, f[0] as string] : l.filter(x => x !== f[0]))} />
              ))}
            </Section>
            <Section title="Названия осей">
              {['x', ...chart.axes].map(name => (
                <Field key={name} label={AXIS_NAME[name] ?? name} wide value={labels[name]} placeholder={chart.labels?.[name] || 'как в программе'}
                  onChange={v => sub('labels', name, v)} />
              ))}
              {['x', 'y'].map(name => {
                const a = (axes[name] as Dict | undefined) ?? {}
                return (
                  <div key={name} className="field wide">
                    <Field label={`${AXIS_NAME[name]}: размер названия, пт`} type="number" value={a.title_size} onChange={v => axis(name, 'title_size', v === '' ? '' : Number(v))} />
                    <Tick label={`${AXIS_NAME[name]}: название жирным`} value={!!a.title_bold} onChange={v => axis(name, 'title_bold', v ? true : '')} />
                    <Tick label={`${AXIS_NAME[name]}: название курсивом`} value={!!a.title_italic} onChange={v => axis(name, 'title_italic', v ? true : '')} />
                    <Field label={`${AXIS_NAME[name]}: размер делений, пт`} type="number" value={a.tick_size} onChange={v => axis(name, 'tick_size', v === '' ? '' : Number(v))} />
                    <Tick label={`${AXIS_NAME[name]}: деления жирным`} value={!!a.tick_bold} onChange={v => axis(name, 'tick_bold', v ? true : '')} />
                    <Tick label={`${AXIS_NAME[name]}: деления курсивом`} value={!!a.tick_italic} onChange={v => axis(name, 'tick_italic', v ? true : '')} />
                  </div>
                )
              })}
            </Section>
          </div>
          {(chart.table || chart.kind === 'stack') && (
            <div className="param-bar">
              {chart.table && (
                <Section title="Таблица под графиком">
                  <Check {...F} field="table_show" label="Показывать таблицу" def={true} />
                  <Field label="Размер шрифта, пт (5–24)" type="number" value={(settings.table as Dict | undefined)?.font_size} onChange={v => sub('table', 'font_size', v === '' ? '' : Number(v))} />
                  <Field label="Высота строк (0,5–3)" type="number" value={(settings.table as Dict | undefined)?.row} placeholder="1" onChange={v => sub('table', 'row', v === '' ? '' : Number(v))} />
                </Section>
              )}
              {chart.kind === 'stack' && (
                <Section title="Подписи в столбцах">
                  <Field label="Размер, пт (5–30)" type="number" value={settings.segment_size} onChange={v => set('segment_size', v === '' ? '' : Number(v))} />
                </Section>
              )}
            </div>
          )}
          {!special && (
            <details className="table-block">
              <summary className="block-head"><h3>Границы и деления осей</h3></summary>
              <div className="param-bar flat">
                {['x', ...chart.axes].map(name => {
                  const a = (axes[name] as Dict | undefined) ?? {}
                  return (
                    <Box key={name} title={AXIS_NAME[name] ?? name}>
                      <Field label="Минимум" value={a.min} onChange={v => axis(name, 'min', v)} />
                      <Field label="Максимум" value={a.max} onChange={v => axis(name, 'max', v)} />
                      <Field label="Шаг делений" value={a.step} onChange={v => axis(name, 'step', v)} />
                      <Field label="Знаков после запятой" type="number" value={a.decimals} onChange={v => axis(name, 'decimals', v === '' ? '' : Number(v))} />
                      <Tick label="Обратное направление" value={!!a.inverse} onChange={v => axis(name, 'inverse', v ? true : '')} />
                      <Tick label="Логарифмическая шкала" value={!!a.log} onChange={v => axis(name, 'log', v ? true : '')} />
                      <Tick label="От нуля" value={!!a.from_zero} onChange={v => axis(name, 'from_zero', v ? true : '')} />
                    </Box>
                  )
                })}
              </div>
              <p className="muted pad">Границы чисел — через запятую или точку; для оси времени — дата дд.мм.гггг.</p>
            </details>
          )}
          {chart.facets.length > 0 && (
            <details className="table-block">
              <summary className="block-head"><h3>Признаки рядов</h3></summary>
              <p className="muted pad">Как значки в легенде на экране: снятая галочка убирает ряды с этим значением из файла.</p>
              {chart.facets.map(f => (
                <Box key={f.name} title={f.name}>
                  {f.values.map(v => {
                    const key = f.name + FACET_SEP + v
                    const off = (((settings.view as Dict | undefined)?.facets as string[] | undefined) ?? []).includes(key)
                    return <Tick key={v} label={v} value={!off} onChange={on => setView(view => {
                      const list = ((view.facets as string[] | undefined) ?? []).filter(x => x !== key)
                      return put(view, 'facets', on ? (list.length ? list : '') : [...list, key])
                    })} />
                  })}
                </Box>
              ))}
            </details>
          )}
          {!special && (
            <section className="table-block">
              <div className="pad">
                <p className="muted small-text">Живой график: двойной щелчок по заголовку, оси или ряду, правая кнопка или кнопка «Формат» открывают панель оформления этого графика
                  (заголовок, легенда, сетка, оси, ряды). То, что вы здесь настроили, попадает в файл.</p>
                {live
                  ? <ChartView key={live.id + moduleId} chart={live} excludeMode={false} onExclude={() => {}}
                      format={{ doc, onDoc, label: 'этот график' }}
                      onDownload={async () => { throw new Error('Файл создаётся кнопкой «Скачать» ниже.') }} />
                  : <p className="pulse">Построение графика…</p>}
              </div>
            </section>
          )}
          {!special && chart.items.length > 1 && (
            <details className="table-block">
              <summary className="block-head"><h3>Какие ряды выгружать ({chart.items.length})</h3></summary>
              <p className="muted pad">Снятая галочка убирает ряд из файла. Цвет, линия и маркеры рядов — в панели «Формат» живого графика.</p>
              <div className="pad">
                {chart.items.slice(0, 200).map(it => {
                  const hidden = (((settings.view as Dict | undefined)?.hidden as string[] | undefined) ?? []).includes(it.group)
                  return <Tick key={it.key} label={it.name || it.group} value={!hidden} onChange={v => setHidden(it.group, !v)} />
                })}
              </div>
            </details>
          )}
          <div className="toolbar">
            <button type="button" className="quiet" disabled={!Object.keys(settings).length} onClick={() => change(() => ({}))}>Сбросить настройки</button>
            <button type="button" className="quiet" title="Вид рядов из окна «Настройка» и границы осей Y, заданные на экране, — поверх настроек этого графика"
              disabled={!Object.keys(fromScreen).length} onClick={takeScreen}>Взять вид с экрана</button>
            <span className="spacer" />
            {busy === 'preview' && <span className="pulse">Обновление предпросмотра…</span>}
            {busy === 'download' && <span className="pulse">Подготовка файла…</span>}
            <button type="button" className="primary" disabled={busy === 'download'} onClick={download}>Скачать {FORMATS.find(f => f[0] === format)?.[1]}</button>
          </div>
          {notes.map((n, i) => <div key={i} className="note info">{n}</div>)}
          {image && <section className="table-block"><div className="pad"><img src={image} alt={chart.title} style={{ maxWidth: '100%' }} /></div></section>}
        </>
      )}
    </>
  )
}

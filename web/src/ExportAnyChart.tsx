// Экспорт → «Любой график»: выбрать график любого раздела и выгрузить его с полной ручной настройкой (atlas/export_any.py).
// Пустое поле — «авто» (как задал модуль): всё, что поменял инженер, главнее.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, defaults, type ModuleSpec, type Params, type Project } from './api'
import { ParamBar } from './ParamBar'
import { SeriesLookFields } from './ChartSettings'
import { Check, Num, Section, Select, SizePick, Text, type Opt } from './exportFields'
import type { Look } from './chartStyle'
import { anyApi, type AnyChartInfo, type AnyModule, type AnySettings, type Form } from './api_projects'

const FORMATS: Opt[] = [['png', 'PNG'], ['svg', 'SVG'], ['pdf', 'PDF'], ['xlsx', 'Excel (данные)'], ['csv', 'CSV (данные)']]
const FONTS: Opt[] = [['default', 'Стандартный (DejaVu Sans)'], ['times', 'Times New Roman'], ['arial_narrow', 'Arial Narrow'], ['calibri', 'Calibri (как в Excel)']]
const LEGENDS: Opt[] = [['auto', 'Авто'], ['bottom', 'Снизу'], ['top', 'Сверху'], ['right', 'Справа'], ['hide', 'Скрыть']]
const GRIDS: Opt[] = [['', 'Авто'], ['both', 'Обе'], ['h', 'Горизонтальная'], ['v', 'Вертикальная'], ['none', 'Нет']]
const MINOR_GRIDS: Opt[] = [['auto', 'Как в графике'], ['show', 'Показывать'], ['hide', 'Скрыть']]
const ALIGNS: Opt[] = [['', 'Авто'], ['left', 'Слева'], ['center', 'По центру'], ['right', 'Справа']]
const AXIS_NAME: Record<string, string> = { x: 'Ось X', y: 'Ось Y', y2: 'Ось Y2 (справа)', y3: 'Ось Y3', y4: 'Ось Y4', y5: 'Ось Y5' }
const SERIES_LIMIT = 40
const DPIS = [150, 200, 250, 300, 600, 1200]
const HEX = /^#[0-9a-f]{6}$/i
const KIND_NOTE: Record<string, string> = {
  heat: 'Тепловая карта: действуют размер рисунка, шрифт и заголовок; размер текста внутри задаёт сам график.',
  strips: 'Матрица скважин × сезонов: действуют размер рисунка, шрифт и заголовок; размер текста внутри задаёт сам график.',
  stack: 'Столбцы с подписями в сегментах: действуют размер, шрифт, легенда (справа, сверху или скрыть), заголовок, подписи в столбцах и таблица под графиком.',
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

function Tick({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return <label className="toggle"><input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} /><span>{label}</span></label>
}

function Color({ label, value, onChange }: { label: string; value: unknown; onChange: (v: string) => void }) {
  const text = typeof value === 'string' ? value : ''
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <span className="cs-range">
        <input type="color" value={HEX.test(text) ? text : '#ffffff'} onChange={e => onChange(e.target.value)} />
        <button type="button" className="cs-auto" disabled={!text} onClick={() => onChange('')} title="Вернуть цвет по умолчанию">авто</button>
      </span>
    </label>
  )
}

export function ExportAnyChart({ project }: { project: Project }) {
  const [specs, setSpecs] = useState<ModuleSpec[]>([])
  const [ready, setReady] = useState<Record<string, AnyModule>>({})
  const [moduleId, setModuleId] = useState('')
  const [params, setParams] = useState<Params>({})
  const [charts, setCharts] = useState<AnyChartInfo[]>([])
  const [note, setNote] = useState('')
  const [chartId, setChartId] = useState('')
  const [settings, setSettings] = useState<AnySettings>({})
  const [image, setImage] = useState<string | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const seq = useRef(0)

  useEffect(() => {
    api.modules().then(setSpecs).catch(e => setError((e as Error).message))
    anyApi.modules(project.id).then(r => setReady(Object.fromEntries(r.modules.map(m => [m.id, m])))).catch(() => undefined)
  }, [project.id, project.revision])

  const spec = specs.find(s => s.id === moduleId)
  const groups = useMemo(() => {
    const by = new Map<string, ModuleSpec[]>()
    for (const s of [...specs].sort((a, b) => a.order - b.order)) by.set(s.group, [...(by.get(s.group) ?? []), s])
    return [...by.entries()]
  }, [specs])
  const chart = charts.find(c => c.id === chartId)

  const pickModule = (id: string) => {
    const s = specs.find(x => x.id === id)
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
  }, [moduleId, paramsKey, project.id, project.revision])

  // Предпросмотр: тот же файл, что уйдёт на выгрузку, PNG 150 DPI.
  const settingsKey = JSON.stringify(settings)
  useEffect(() => {
    if (!moduleId || !chartId) return
    const mine = ++seq.current
    const timer = setTimeout(() => {
      setBusy('preview')
      anyApi.file(project.id, moduleId, params, chartId, { ...settings, format: 'png', dpi: 150 }).then(r => {
        if (mine !== seq.current) return
        setImage(old => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(r.blob) })
        setNotes(r.notes); setError(null)
      }).catch(e => { if (mine === seq.current) { setError((e as Error).message); setImage(null) } })
        .finally(() => { if (mine === seq.current) setBusy(null) })
    }, 500)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, chartId, settingsKey, paramsKey, project.id])

  const set = (key: string, value: unknown) => setSettings(s => put(s, key, value))
  const sub = (group: 'chart' | 'axes' | 'labels' | 'table', key: string, value: unknown) => setSettings(s => {
    const next = put((s[group] as Dict | undefined) ?? {}, key, value)
    return put(s, group, Object.keys(next).length ? next : '')
  })
  const axis = (name: string, key: string, value: unknown) => setSettings(s => {
    const all = (s.axes as Dict | undefined) ?? {}
    const one = put((all[name] as Dict | undefined) ?? {}, key, value)
    const next = put(all, name, Object.keys(one).length ? one : '')
    return put(s, 'axes', Object.keys(next).length ? next : '')
  })
  const setView = (fn: (v: Dict) => Dict) => setSettings(s => {
    const next = fn((s.view as Dict | undefined) ?? {})
    return put(s, 'view', Object.keys(next).length ? next : '')
  })
  const setLook = (key: string, patch: Partial<Look>) => setView(v => {
    const looks = { ...((v.looks as Record<string, Look> | undefined) ?? {}) }
    const one = { ...looks[key], ...patch } as Dict
    for (const k of Object.keys(one)) if (one[k] === undefined) delete one[k]
    if (Object.keys(one).length) looks[key] = one as Look; else delete looks[key]
    return put(v, 'looks', Object.keys(looks).length ? looks : '')
  })
  const setHidden = (group: string, hide: boolean) => setView(v => {
    const list = ((v.hidden as string[] | undefined) ?? []).filter(g => g !== group)
    return put(v, 'hidden', hide ? [...list, group] : list.length ? list : '')
  })
  const chartStyle = (settings.chart as Dict | undefined) ?? {}
  const axes = (settings.axes as Dict | undefined) ?? {}
  const labels = (settings.labels as Dict | undefined) ?? {}
  const special = chart?.special ?? false
  const format = (settings.format as string | undefined) ?? 'png'
  // Общие поля — те же компоненты и подписи, что у «Производительность скважин»; значения берутся из настроек выгрузки.
  const form: Form = { format, dpi: settings.dpi, look: settings.look, width: settings.width, height: settings.height, font: settings.font,
    font_size: settings.font_size, legend: chartStyle.legend, title: chartStyle.title, title_align: chartStyle.title_align, grid: chartStyle.grid,
    grid_width: chartStyle.grid_width, minor_grid: chartStyle.minor_grid, minor_grid_width: chartStyle.minor_grid_width,
    table_show: (settings.table as Dict | undefined)?.show !== false }
  const setField = (field: string, value: unknown) => {
    if (field === 'format') set('format', value === 'png' ? '' : value)
    else if (field === 'dpi') set('dpi', Number(value) === 300 ? '' : value)
    else if (field === 'look' || field === 'font') set(field, value === 'default' ? '' : value)
    else if (field === 'legend') sub('chart', 'legend', value === 'auto' ? '' : value)
    else if (['title', 'title_align', 'grid', 'grid_width', 'minor_grid', 'minor_grid_width'].includes(field)) sub('chart', field, value === 'auto' ? '' : value)
    else if (field === 'table_show') sub('table', 'show', value ? '' : false)
    else set(field, value)
  }
  const F = { form, set: setField }

  const download = async () => {
    if (!chart) return
    setBusy('download'); setError(null)
    try {
      const r = await anyApi.file(project.id, moduleId, params, chartId, settings)
      const url = URL.createObjectURL(r.blob)
      const a = document.createElement('a')
      a.href = url; a.download = r.name; document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotes(r.notes)
    } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }

  return (
    <>
      <p className="lede">Любой график любого раздела: выберите раздел и его параметры, затем график — и настройте выгрузку именно этого графика. Пустое поле — как задал раздел.</p>
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
          {charts.length > 0 && (
            <label className="field wide">
              <span className="field-label">График ({charts.length})</span>
              <select value={chartId} onChange={e => setChartId(e.target.value)}>
                {charts.map(c => <option key={c.id} value={c.id}>{c.title || c.id}{c.table ? ' · с таблицей' : ''}</option>)}
              </select>
            </label>
          )}
        </Box>
      </div>
      {spec && <ParamBar key={spec.id} spec={spec} project={project.id} panel={0} values={params} onChange={setParams} />}
      {error && <div className="note warning" role="alert">{error}</div>}
      {spec && !busy && charts.length === 0 && !error && <div className="note info">{note || 'Графиков нет.'}</div>}

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
              <Select {...F} field="legend" label="Легенда" def="auto" options={LEGENDS} />
              <Text {...F} field="title" label="Заголовок графика" def="" wide />
            </Section>
            <Section title="Оформление графика">
              <Field label="Размер заголовка, пт" type="number" value={chartStyle.title_size} onChange={v => sub('chart', 'title_size', v === '' ? '' : Number(v))} />
              <Select {...F} field="title_align" label="Выравнивание заголовка" def="" options={ALIGNS} />
              <Color label="Цвет заголовка" value={chartStyle.title_color} onChange={v => sub('chart', 'title_color', v)} />
              <Select {...F} field="grid" label="Сетка" def="" options={GRIDS} />
              <Color label="Цвет сетки" value={chartStyle.grid_color} onChange={v => sub('chart', 'grid_color', v)} />
              <Num {...F} field="grid_width" label="Толщина основной сетки, пт" def={0.7} min={0.2} max={4} step={0.1} />
              <Select {...F} field="minor_grid" label="Доп. линии сетки" def="auto" options={MINOR_GRIDS} />
              <Color label="Цвет доп. линий" value={chartStyle.minor_grid_color} onChange={v => sub('chart', 'minor_grid_color', v)} />
              <Num {...F} field="minor_grid_width" label="Толщина доп. линий, пт" def={0.5} min={0.2} max={4} step={0.1} />
              <Color label="Фон рисунка" value={chartStyle.background} onChange={v => sub('chart', 'background', v)} />
              <Color label="Фон области построения" value={chartStyle.plot_background} onChange={v => sub('chart', 'plot_background', v)} />
              <Color label="Цвет текста" value={chartStyle.text_color} onChange={v => sub('chart', 'text_color', v)} />
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
              <summary className="block-head"><h3>Оси</h3></summary>
              <div className="param-bar flat">
                {['x', ...chart.axes].map(name => {
                  const a = (axes[name] as Dict | undefined) ?? {}
                  return (
                    <Box key={name} title={AXIS_NAME[name] ?? name}>
                      <Field label="Подпись" wide value={labels[name]} placeholder="как в программе" onChange={v => sub('labels', name, v)} />
                      <Field label="Минимум" value={a.min} onChange={v => axis(name, 'min', v)} />
                      <Field label="Максимум" value={a.max} onChange={v => axis(name, 'max', v)} />
                      <Field label="Шаг делений" value={a.step} onChange={v => axis(name, 'step', v)} />
                      <Field label="Знаков после запятой" type="number" value={a.decimals} onChange={v => axis(name, 'decimals', v === '' ? '' : Number(v))} />
                      <Field label="Размер подписей, пт" type="number" value={a.tick_size} onChange={v => axis(name, 'tick_size', v === '' ? '' : Number(v))} />
                      <Tick label="Название оси жирным" value={!!a.title_bold} onChange={v => axis(name, 'title_bold', v ? true : '')} />
                      <Tick label="Название оси курсивом" value={!!a.title_italic} onChange={v => axis(name, 'title_italic', v ? true : '')} />
                      <Tick label="Деления жирным" value={!!a.tick_bold} onChange={v => axis(name, 'tick_bold', v ? true : '')} />
                      <Tick label="Деления курсивом" value={!!a.tick_italic} onChange={v => axis(name, 'tick_italic', v ? true : '')} />
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
          {!special && chart.items.length > 0 && (
            <details className="table-block">
              <summary className="block-head"><h3>Ряды ({chart.items.length})</h3></summary>
              <p className="muted pad">Цвет, линия, маркеры и прозрачность каждого ряда; снятая галочка скрывает ряд в файле. Цвет «авто» — из сквозной палитры групп.</p>
              {chart.items.slice(0, SERIES_LIMIT).map(it => {
                const look = (((settings.view as Dict | undefined)?.looks as Dict | undefined)?.[it.key] as Look | undefined) ?? {}
                const hidden = (((settings.view as Dict | undefined)?.hidden as string[] | undefined) ?? []).includes(it.group)
                return (
                  <details key={it.key} className="table-block">
                    <summary className="block-head">
                      <span style={{ display: 'inline-block', width: 12, height: 12, background: look.color ?? it.color, marginRight: 8, borderRadius: 2 }} />
                      {it.name || it.group}{hidden ? ' (скрыт)' : ''}
                    </summary>
                    <div className="pad">
                      <Tick label="Показывать ряд" value={!hidden} onChange={v => setHidden(it.group, !v)} />
                      <SeriesLookFields s={{ kind: it.kind, dash: 'solid', dashed: false, width: 0, markers: false, symbol: 'circle', opacity: 1 }}
                        color={it.color} look={look} onChange={patch => setLook(it.key, patch)} />
                    </div>
                  </details>
                )
              })}
              {chart.items.length > SERIES_LIMIT && <p className="muted pad">Показаны первые {SERIES_LIMIT} рядов из {chart.items.length}.</p>}
            </details>
          )}
          <div className="toolbar">
            <button type="button" className="quiet" disabled={!Object.keys(settings).length} onClick={() => setSettings({})}>Сбросить настройки</button>
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

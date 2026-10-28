// Экспорт → «Любой график»: выбрать график любого раздела и выгрузить его с полной ручной настройкой (atlas/export_any.py).
// Пустое поле — «авто» (как задал модуль): всё, что поменял инженер, главнее.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, defaults, type ModuleSpec, type Params, type Project } from './api'
import { ParamBar } from './ParamBar'
import { anyApi, type AnyChartInfo, type AnyModule, type AnySettings } from './api_projects'

const FORMATS: [string, string][] = [['png', 'PNG'], ['svg', 'SVG'], ['pdf', 'PDF'], ['xlsx', 'Excel (данные)'], ['csv', 'CSV (данные)']]
const SIZES: [string, string][] = [
  ['', 'Авто (по ширине и легенде)'], ['a4-width', 'A4: ширина поля 170'], ['a4-half', 'A4: пол-листа 170 × 100'], ['a4-page', 'A4: 190 × 120'],
  ['a4-land', 'A4 альбомный 270 × 180'], ['16x9', 'Слайд 16:9, 254 × 143'], ['4x3', 'Слайд 4:3, 240 × 180'], ['column', 'Колонка 85 × 65'], ['square', 'Квадрат 150 × 150'],
]
const FONTS: [string, string][] = [['default', 'Стандартный (DejaVu Sans)'], ['times', 'Times New Roman'], ['arial_narrow', 'Arial Narrow'], ['calibri', 'Calibri (как в Excel)']]
const LEGENDS: [string, string][] = [['', 'Авто'], ['bottom', 'Снизу'], ['top', 'Сверху'], ['right', 'Справа'], ['hide', 'Скрыть']]
const GRIDS: [string, string][] = [['', 'Авто'], ['both', 'Обе'], ['h', 'Горизонтальная'], ['v', 'Вертикальная'], ['none', 'Нет']]
const ALIGNS: [string, string][] = [['', 'Авто'], ['left', 'Слева'], ['center', 'По центру'], ['right', 'Справа']]
const AXIS_NAME: Record<string, string> = { x: 'Ось X', y: 'Ось Y', y2: 'Ось Y2 (справа)', y3: 'Ось Y3', y4: 'Ось Y4', y5: 'Ось Y5' }
const DPIS = [150, 200, 250, 300, 600, 1200]
const HEX = /^#[0-9a-f]{6}$/i
const KIND_NOTE: Record<string, string> = {
  heat: 'Тепловая карта: размер, шрифт и оформление задаются самим графиком.',
  strips: 'Матрица скважин × сезонов: размер, шрифт и оформление задаются самим графиком.',
  stack: 'Столбцы с подписями в сегментах: размер, шрифт и оформление задаются самим графиком.',
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

function Pick({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select value={value} onChange={e => onChange(e.target.value)}>{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
    </label>
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
  const sub = (group: 'chart' | 'axes' | 'labels', key: string, value: unknown) => setSettings(s => {
    const next = put((s[group] as Dict | undefined) ?? {}, key, value)
    return put(s, group, Object.keys(next).length ? next : '')
  })
  const axis = (name: string, key: string, value: unknown) => setSettings(s => {
    const all = (s.axes as Dict | undefined) ?? {}
    const one = put((all[name] as Dict | undefined) ?? {}, key, value)
    const next = put(all, name, Object.keys(one).length ? one : '')
    return put(s, 'axes', Object.keys(next).length ? next : '')
  })
  const chartStyle = (settings.chart as Dict | undefined) ?? {}
  const axes = (settings.axes as Dict | undefined) ?? {}
  const labels = (settings.labels as Dict | undefined) ?? {}
  const special = chart?.special ?? false
  const format = (settings.format as string | undefined) ?? 'png'

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
          <div className="param-bar flat">
            <Box title="Файл">
              <Pick label="Формат" value={format} options={FORMATS} onChange={v => set('format', v === 'png' ? '' : v)} />
              <Pick label="Разрешение, DPI" value={String(settings.dpi ?? 300)} options={DPIS.map(d => [String(d), String(d)] as [string, string])} onChange={v => set('dpi', Number(v) === 300 ? '' : Number(v))} />
              <Pick label="Вид" value={(settings.look as string | undefined) ?? 'default'} options={[['default', 'Обычный'], ['excel', 'Как диаграмма Excel']]} onChange={v => set('look', v === 'default' ? '' : v)} />
            </Box>
            <Box title="Размер, мм">
              <Pick label="Шаблон" value={(settings.size as string | undefined) ?? ''} options={SIZES} onChange={v => set('size', v)} />
              <Field label="Ширина (80–300)" type="number" value={settings.width} onChange={v => set('width', v === '' ? '' : Number(v))} />
              <Field label="Высота (40–400)" type="number" value={settings.height} onChange={v => set('height', v === '' ? '' : Number(v))} />
            </Box>
            <Box title="Шрифт">
              <Pick label="Шрифт" value={(settings.font as string | undefined) ?? 'default'} options={FONTS} onChange={v => set('font', v === 'default' ? '' : v)} />
              <Field label="Размер, пт (5–30)" type="number" value={settings.font_size} onChange={v => set('font_size', v === '' ? '' : Number(v))} />
            </Box>
            <Box title="Оформление графика">
              <Field label="Заголовок" wide value={chartStyle.title} placeholder="как в программе" onChange={v => sub('chart', 'title', v)} />
              <Field label="Размер заголовка, пт" type="number" value={chartStyle.title_size} onChange={v => sub('chart', 'title_size', v === '' ? '' : Number(v))} />
              <Pick label="Выравнивание заголовка" value={(chartStyle.title_align as string | undefined) ?? ''} options={ALIGNS} onChange={v => sub('chart', 'title_align', v)} />
              <Color label="Цвет заголовка" value={chartStyle.title_color} onChange={v => sub('chart', 'title_color', v)} />
              <Pick label="Легенда" value={(chartStyle.legend as string | undefined) ?? ''} options={LEGENDS} onChange={v => sub('chart', 'legend', v)} />
              <Pick label="Сетка" value={(chartStyle.grid as string | undefined) ?? ''} options={GRIDS} onChange={v => sub('chart', 'grid', v)} />
              <Color label="Цвет сетки" value={chartStyle.grid_color} onChange={v => sub('chart', 'grid_color', v)} />
              <Color label="Фон рисунка" value={chartStyle.background} onChange={v => sub('chart', 'background', v)} />
              <Color label="Фон области построения" value={chartStyle.plot_background} onChange={v => sub('chart', 'plot_background', v)} />
              <Color label="Цвет текста" value={chartStyle.text_color} onChange={v => sub('chart', 'text_color', v)} />
            </Box>
          </div>
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

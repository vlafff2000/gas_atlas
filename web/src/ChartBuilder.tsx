import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { MultiSelect } from './MultiSelect'
import type { ChartStyle } from './api'
import type { Look } from './chartStyle'
import { AxisDialog, ChartDialog, SeriesDialog, VIEWS, type AxisFmt, type AxisItem, type AxisKey, type BuilderView } from './BuilderDialogs'
import { FUNCTIONS, checkFormula, findCycle, letter, renumber } from './builderFormula'
import { BuilderLibrary } from './BuilderLibrary'
import { SeriesDialog as SeriesExport, WellPicker } from './BuilderWells'
import './builder.css'

// Конструктор графиков: дерево полей, ряды-карточки, ручные подписи. Макет — параметр раздела ``layout``
// (atlas/modules/builder.py), хранится и сохраняется как параметры других разделов.

export interface BuilderField {
  id: string; dataset: string; dataset_label: string; field: string; label: string; unit: string
  kind: 'number' | 'date'; category: string
}
export interface BuilderDataset {
  id: string; label: string; entity: '' | 'well' | 'group'; entities: string[]
  kinds: { value: string; label: string }[]; fields: BuilderField[]; date_min: string | null; date_max: string | null
}
export interface BuilderCatalog {
  categories: { id: string; label: string; fields: BuilderField[] }[]
  datasets: BuilderDataset[]
  wells?: string[]        // скважины проекта (для «Скважины макета»)
  keys: { value: string; label: string }[]
}
export type AxisName = 'y' | 'y2' | 'y3' | 'y4' | 'y5'
export interface BuilderRow {
  id: string; dataset: string; y: string; x_dataset: string; x: string; wells: string[]
  wells_mode?: 'fixed' | 'current'   // «текущая скважина»: ряд берёт layout.current_well; старые макеты — фиксированные
  date_from: string; date_to: string; kind: string; axis: AxisName; view: BuilderView
  stack?: string         // общее имя: столбцы и области с одним именем складываются стопкой
  key: string; days: number; name: string; hidden?: boolean
  look?: Look            // ручной вид ряда (окно «Ряд»); пусто — авто
  source?: 'field' | 'formula'   // этап 4: поле данных (по умолчанию) или формула по другим рядам (A, B, C… по порядку)
  formula?: string
  transform?: RowTransform       // преобразование Y; нет — без преобразования (старые макеты)
  unit?: string                  // ручная единица; пусто — по полю и преобразованию
}
export interface RowTransform { op: TransformOp; n?: number; by?: 'points' | 'days'; agg?: Agg; norm?: 'first' | 'max' | 'value'; value?: string }
type TransformOp = 'none' | 'cumsum' | 'rolling' | 'day' | 'month' | 'group' | 'norm' | 'mul' | 'div' | 'add' | 'diff'
type Agg = 'mean' | 'sum' | 'max' | 'min'
const TRANSFORMS: [TransformOp, string][] = [
  ['none', 'без преобразования'], ['cumsum', 'накопленное (с начала периода)'], ['rolling', 'скользящее среднее'],
  ['day', 'по суткам'], ['month', 'по месяцам'], ['group', 'по скважинам выборки (одна кривая)'], ['norm', 'нормировка'],
  ['mul', 'умножить на число'], ['div', 'разделить на число'], ['add', 'прибавить число'], ['diff', 'разность соседних значений'],
]
const AGGS: [Agg, string][] = [['mean', 'среднее'], ['sum', 'сумма'], ['max', 'максимум'], ['min', 'минимум']]
const EXAMPLES = ['A/B', '(A-B)/A*100', 'A-B', 'sqrt(A^2 - B^2)', 'max(A; B)']
const isFormula = (r: BuilderRow) => r.source === 'formula'
export interface BuilderLayout {
  series: BuilderRow[]; title: string; x_label: string; axes: Partial<Record<AxisName, string>>
  current_well?: string                               // скважина макета для рядов «Текущая скважина»; нет в старых макетах
  axis_style?: Partial<Record<AxisKey, AxisFmt>>      // окно «Ось»: границы, шаг, шрифт…; старые макеты без него открываются как раньше
  chart_style?: ChartStyle                            // окно «График»: заголовок, легенда, сетка, фон
}

const AXES: AxisName[] = ['y', 'y2', 'y3', 'y4', 'y5']
const axisTitle = (a: AxisName) => (a === 'y' ? 'Y1' : 'Y' + a.slice(1))
const axisHint = (a: AxisName) => (a === 'y' ? 'левая' : 'правая')
const newId = () => Math.random().toString(36).slice(2, 10)

export function layoutOf(value: unknown): BuilderLayout {
  const v = (value && typeof value === 'object' ? value : {}) as Partial<BuilderLayout>
  return {
    series: Array.isArray(v.series) ? v.series.filter(r => r && typeof r === 'object').map(r => ({
      ...r, id: r.id || newId(), dataset: r.dataset ?? '', y: r.y ?? '', x_dataset: r.x_dataset ?? r.dataset ?? '', x: r.x ?? 'date',
      wells: Array.isArray(r.wells) ? r.wells : [], date_from: r.date_from ?? '', date_to: r.date_to ?? '', kind: r.kind ?? '',
      axis: r.axis ?? 'y', view: r.view ?? 'line', key: r.key ?? 'well_date', days: r.days ?? 3, name: r.name ?? '',   // файл мог быть написан вручную
    })) : [],
    title: v.title ?? '', x_label: v.x_label ?? '', axes: v.axes ?? {},
    ...(v.current_well ? { current_well: v.current_well } : {}),
    ...(v.axis_style ? { axis_style: v.axis_style } : {}), ...(v.chart_style ? { chart_style: v.chart_style } : {}),
  }
}

function withUnit(f: BuilderField | undefined) {
  return f ? f.label + (f.unit ? ', ' + f.unit : '') : ''
}

/** Новый ряд с полем Y: X — дата того же набора (если есть), первая скважина, отбор. */
function rowFor(field: BuilderField, ds: BuilderDataset | undefined, axis: AxisName = 'y', base?: BuilderRow): BuilderRow {
  const hasDate = !!ds?.fields.some(f => f.field === 'date')
  const keepX = base && base.x_dataset !== base.dataset
  const wells = base && ds ? base.wells.filter(w => ds.entities.includes(w)) : []
  return {
    id: base?.id ?? newId(), dataset: field.dataset, y: field.field,
    x_dataset: keepX ? base!.x_dataset : field.dataset,
    x: keepX ? base!.x : hasDate ? 'date' : (ds?.fields.find(f => f.field !== field.field)?.field ?? field.field),
    wells: wells.length ? wells : ds?.entities.length ? [ds.entities[0]] : [],
    date_from: base?.date_from ?? '', date_to: base?.date_to ?? '',
    kind: !ds?.kinds.length ? '' : base && (base.kind === '' || ds.kinds.some(k => k.value === base.kind)) ? base.kind
      : ds.kinds.some(k => k.value === 'withdrawal') ? 'withdrawal' : '',
    axis: base?.axis ?? axis, view: base?.view ?? 'line', stack: base?.stack, key: base?.key ?? 'well_date', days: base?.days ?? 3,
    name: '', hidden: base?.hidden, look: base?.look, ...(base?.wells_mode && ds?.entity === 'well' ? { wells_mode: base.wells_mode } : {}), ...(base?.transform ? { transform: base.transform } : {}),
  }
}

export function ChartBuilder({ project, revision, value, onChange }:
  { project: string; revision: number; value: unknown; onChange: (layout: BuilderLayout) => void }) {
  const layout = useMemo(() => layoutOf(value), [value])
  const [catalog, setCatalog] = useState<BuilderCatalog | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [active, setActive] = useState<string | null>(layout.series[layout.series.length - 1]?.id ?? null)
  const [dialog, setDialog] = useState<'row' | 'axis' | 'chart' | null>(null)
  const [axisKey, setAxisKey] = useState<AxisKey>('x')
  const [seriesOpen, setSeriesOpen] = useState(false)

  useEffect(() => {
    let alive = true
    api.catalog<BuilderCatalog>('builder', project)
      .then(c => { if (alive) { setCatalog(c); setError('') } })
      .catch(e => { if (alive) setError((e as Error).message) })
    return () => { alive = false }
  }, [project, revision])

  const datasets = useMemo(() => new Map((catalog?.datasets ?? []).map(d => [d.id, d])), [catalog])
  const fieldOf = (dataset: string, field: string) => datasets.get(dataset)?.fields.find(f => f.field === field)
  const set = (next: Partial<BuilderLayout>) => onChange({ ...layout, ...next })
  const setRow = (id: string, patch: Partial<BuilderRow>) =>
    set({ series: layout.series.map(r => (r.id === id ? { ...r, ...patch } : r)) })

  const freeAxis = (): AxisName => AXES.find(a => !layout.series.some(r => r.axis === a)) ?? 'y'
  const addRow = (field?: BuilderField) => {
    const all = catalog?.categories.flatMap(c => c.fields) ?? []
    // по умолчанию — суточный расход скважины: с него обычно начинают; иначе первое поле дерева
    const f = field ?? all.find(a => a.id === 'production.q') ?? all[0]
    if (!f) return
    const row = rowFor(f, datasets.get(f.dataset), layout.series.length ? freeAxis() : 'y')
    set({ series: [...layout.series, row] }); setActive(row.id)
  }
  const pickY = (f: BuilderField) => {
    const row = layout.series.find(r => r.id === active)
    if (!row) { addRow(f); return }
    if (isFormula(row)) {       // у формулы щелчок по полю — новый скрытый ряд с этим полем, его буква дописывается в формулу
      const extra = { ...rowFor(f, datasets.get(f.dataset), row.axis), hidden: true }
      const ref = letter(layout.series.length + 1)
      const text = (row.formula ?? '').trim()
      set({ series: [...layout.series.map(r => (r.id === row.id ? { ...r, formula: text ? text + ' ' + ref : ref } : r)), extra] })
      return
    }
    const next = rowFor(f, datasets.get(f.dataset), row.axis, row)
    set({ series: layout.series.map(r => (r.id === row.id ? next : r)) })
  }
  const pickX = (f: BuilderField) => {
    const row = layout.series.find(r => r.id === active)
    if (row) setRow(row.id, { x_dataset: f.dataset, x: f.field })
  }
  // формулы ссылаются на ряды по порядку: при вставке и удалении буквы перенумеровываются
  const shift = (rows: BuilderRow[], map: (n: number) => number | null) =>
    rows.map(r => (isFormula(r) && r.formula ? { ...r, formula: renumber(r.formula, map) } : r))
  const duplicate = (row: BuilderRow) => {
    const copy = { ...row, id: newId(), axis: freeAxis() }
    const at = layout.series.findIndex(r => r.id === row.id)
    const next = [...layout.series.slice(0, at + 1), copy, ...layout.series.slice(at + 1)]
    set({ series: shift(next, n => (n > at + 1 ? n + 1 : n)) }); setActive(copy.id)
  }
  const remove = (row: BuilderRow) => {
    const at = layout.series.findIndex(r => r.id === row.id) + 1
    const rest = shift(layout.series.filter(r => r.id !== row.id), n => (n > at ? n - 1 : n === at ? null : n))
    set({ series: rest }); if (active === row.id) setActive(rest[rest.length - 1]?.id ?? null)
  }
  const checks = useMemo(() => {
    const out = new Map<string, string>()
    const refs = new Map<number, number[]>()
    layout.series.forEach((r, i) => {
      if (!isFormula(r)) return
      const c = checkFormula(r.formula ?? '', i + 1, layout.series.length)
      if (c.error) out.set(r.id, c.error); else refs.set(i + 1, c.refs)
    })
    const cycle = findCycle(refs)
    if (cycle) out.set(layout.series[cycle[0] - 1].id, 'циклическая ссылка: ' + cycle.map(n => letter(n)).join(' → '))
    return out
  }, [layout.series])
  const rowLabel = (r: BuilderRow) => (isFormula(r) ? r.formula || 'формула' : fieldOf(r.dataset, r.y)?.label ?? r.y)
    + (r.transform && r.transform.op !== 'none' ? ', ' + (TRANSFORMS.find(o => o[0] === r.transform!.op)?.[1] ?? '') : '')

  const q = query.trim().toLowerCase()
  const tree = (catalog?.categories ?? []).map(c => ({
    ...c, fields: q ? c.fields.filter(f => (f.label + ' ' + f.dataset_label + ' ' + c.label).toLowerCase().includes(q)) : c.fields,
  })).filter(c => c.fields.length)
  const used = AXES.filter(a => layout.series.some(r => r.axis === a && !r.hidden))
  const autoAxis = (a: AxisName) => [...new Set(layout.series.filter(r => r.axis === a && !r.hidden).map(rowLabel))].join(', ')
  const autoX = [...new Set(layout.series.filter(r => !isFormula(r)).map(r => withUnit(fieldOf(r.x_dataset, r.x)) || r.x))].join(', ')
  const activeRow = layout.series.find(r => r.id === active)
  const axes: AxisItem[] = [
    { key: 'x', title: 'X', label: layout.x_label, auto: autoX, time: layout.series.some(r => fieldOf(r.x_dataset, r.x)?.kind === 'date') },
    ...used.map(a => ({ key: a as AxisKey, title: axisTitle(a), label: layout.axes[a] ?? '', auto: autoAxis(a),
      time: layout.series.some(r => r.axis === a && fieldOf(r.dataset, r.y)?.kind === 'date') })),
  ]

  return (
    <div className="builder-side">
      <section className="builder-tree" aria-label="Поля данных">
        <h2>Поля</h2>
        <input type="search" placeholder="Найти поле…" value={query} onChange={e => setQuery(e.target.value)} aria-label="Поиск по полям" />
        {error && <div className="note warning">{error}</div>}
        {!catalog && !error && <p className="muted">Загрузка полей…</p>}
        {catalog && !catalog.categories.length && <div className="note info">В проекте нет числовых полей. Загрузите данные в разделе импорта.</div>}
        {catalog && q && !tree.length && <p className="muted">Ничего не найдено.</p>}
        {tree.map(c => (
          <details key={c.id} open={!!q || c.id === catalog?.categories[0]?.id}>
            <summary>{c.label} <span className="muted">{c.fields.length}</span></summary>
            <ul>
              {c.fields.map(f => (
                <li key={f.id}>
                  <button type="button" className="tree-field" onClick={() => pickY(f)}
                    title={activeRow ? `Поле Y ряда ${layout.series.indexOf(activeRow) + 1}` : 'Новый ряд с этим полем'}>
                    <span>{f.label}</span><small>{f.unit ? f.unit + ' · ' : ''}{f.dataset_label}</small>
                  </button>
                  {activeRow && <button type="button" className="tree-x" onClick={() => pickX(f)} title="Поле X выбранного ряда">X</button>}
                </li>
              ))}
            </ul>
          </details>
        ))}
        {catalog && catalog.categories.length > 0 && <p className="muted tree-hint">Щелчок — поле Y выбранного ряда, «X» — его поле X.</p>}
      </section>

      <section className="builder-rows" aria-label="Ряды графика">
        <BuilderLibrary project={project} layout={layout} onOpen={v => { const next = layoutOf(v); onChange(next); setActive(next.series[0]?.id ?? null); return next }} />
        {catalog?.wells?.length ? (
          <WellPicker wells={catalog.wells} value={layout.current_well ?? ''} onChange={w => set({ current_well: w })} onSeries={() => setSeriesOpen(true)} />
        ) : null}
        <h2>Ряды</h2>
        {layout.series.length > 0 && (
          <div className="builder-tools" role="toolbar" aria-label="Настройка графика">
            <span className="tools-label">Настройка:</span>
            {([['row', 'Ряд', 'Линия, маркеры, цвет, прозрачность выбранного ряда'], ['axis', 'Ось', 'Подпись, границы, шаг, логарифм, формат чисел и шрифт оси'],
              ['chart', 'График', 'Заголовок, шрифты, легенда, сетка, фон']] as const).map(([id, label, hint]) => (
              <button key={id} type="button" className="quiet" aria-pressed={dialog === id} title={hint}
                onClick={() => setDialog(d => (d === id ? null : id))}>{label}</button>
            ))}
          </div>
        )}
        {layout.series.map((r, i) => (
          <RowCard key={r.id} index={i} row={r} catalog={catalog} datasets={datasets} open={r.id === active}
            others={layout.series.map((o, k) => ({ ref: letter(k + 1), title: o.name || rowLabel(o), hidden: !!o.hidden, self: k === i }))}
            check={checks.get(r.id) ?? ''}
            onOpen={() => setActive(r.id === active ? null : r.id)} onChange={patch => setRow(r.id, patch)}
            onPickY={f => set({ series: layout.series.map(x => (x.id === r.id ? rowFor(f, datasets.get(f.dataset), r.axis, r) : x)) })}
            onDuplicate={() => duplicate(r)} onRemove={() => remove(r)} />
        ))}
        <button type="button" className="primary add-row" onClick={() => addRow()} disabled={!catalog?.categories.length}>+ Добавить ряд</button>

        {layout.series.length > 0 && (
          <fieldset className="builder-labels">
            <legend>Подписи</legend>
            <p className="muted">Пусто — по названиям полей и единицам. <code>{'{скважина}'}</code> заменится номером скважины макета.</p>
            <LabelInput label="Заголовок" value={layout.title} auto={[...new Set(layout.series.filter(r => !r.hidden).map(r => r.name || rowLabel(r)))].join(', ')}
              onChange={v => set({ title: v })} />
            <LabelInput label="Ось X" value={layout.x_label} auto={autoX} onChange={v => set({ x_label: v })} />
            {used.map(a => (
              <LabelInput key={a} label={`Ось ${axisTitle(a)}`} value={layout.axes[a] ?? ''} auto={autoAxis(a)}
                onChange={v => set({ axes: { ...layout.axes, [a]: v } })} />
            ))}
          </fieldset>
        )}
      </section>
      {seriesOpen && <SeriesExport project={project} layout={layout} onClose={() => setSeriesOpen(false)} />}
      {dialog === 'row' && layout.series.length > 0 && (
        <SeriesDialog activeId={active} onActive={setActive} onClose={() => setDialog(null)}
          rows={layout.series.map((r, i) => ({ id: r.id, view: r.view, look: r.look ?? {},
            title: r.name || rowLabel(r) || `ряд ${i + 1}` }))}
          onChange={(id, look) => setRow(id, { look: Object.keys(look).length ? look : undefined })} />
      )}
      {dialog === 'axis' && layout.series.length > 0 && (
        <AxisDialog activeKey={axes.some(a => a.key === axisKey) ? axisKey : 'x'} onActive={setAxisKey} axes={axes} fmt={layout.axis_style ?? {}}
          onLabel={(k, v) => (k === 'x' ? set({ x_label: v }) : set({ axes: { ...layout.axes, [k]: v } }))}
          onChange={(k, f) => { const next = { ...layout.axis_style }; if (Object.keys(f).length) next[k] = f; else delete next[k]; set({ axis_style: next }) }}
          onClose={() => setDialog(null)} />
      )}
      {dialog === 'chart' && layout.series.length > 0 && (
        <ChartDialog title={layout.title} autoTitle={[...new Set(layout.series.filter(r => !r.hidden).map(r => r.name || rowLabel(r)))].join(', ')}
          style={layout.chart_style ?? {}} onTitle={t => set({ title: t })} onChange={s => set({ chart_style: s })} onClose={() => setDialog(null)} />
      )}
    </div>
  )
}

function LabelInput({ label, value, auto, onChange }: { label: string; value: string; auto: string; onChange: (v: string) => void }) {
  return (
    <label className="field label-input">
      <span className="field-label">{label}</span>
      <input type="text" value={value} placeholder={auto} onChange={e => onChange(e.target.value)} />
    </label>
  )
}

function RowCard({ index, row, catalog, datasets, open, others, check, onOpen, onChange, onPickY, onDuplicate, onRemove }: {
  index: number; row: BuilderRow; catalog: BuilderCatalog | null; datasets: Map<string, BuilderDataset>; open: boolean
  others: { ref: string; title: string; hidden: boolean; self: boolean }[]; check: string
  onOpen: () => void; onChange: (patch: Partial<BuilderRow>) => void; onPickY: (f: BuilderField) => void
  onDuplicate: () => void; onRemove: () => void
}) {
  const ds = datasets.get(row.dataset)
  const y = ds?.fields.find(f => f.field === row.y)
  const xs = datasets.get(row.x_dataset)
  const x = xs?.fields.find(f => f.field === row.x)
  const joined = row.x_dataset !== row.dataset
  const entity = ds?.entity === 'group' ? 'Группы' : 'Скважины'
  const wells = row.wells.length ? (ds?.entity === 'well' ? 'скв. ' : '') + row.wells.slice(0, 3).join(', ') + (row.wells.length > 3 ? ` +${row.wells.length - 3}` : '')
    : ds?.entity ? (ds.entity === 'well' ? 'все скважины' : 'все группы') : 'объект'
  const keyLabel = catalog?.keys.find(k => k.value === row.key)?.label ?? row.key
  const allFields = catalog?.categories.flatMap(c => c.fields) ?? []
  const formula = isFormula(row)
  const t: RowTransform = row.transform ?? { op: 'none' }
  const setT = (patch: Partial<RowTransform>) => {
    const next = { ...t, ...patch }
    onChange({ transform: next.op === 'none' ? undefined : next })
  }
  const opLabel = TRANSFORMS.find(o => o[0] === t.op)?.[1]

  return (
    <article className={'row-card' + (open ? ' open' : '') + (row.hidden ? ' hidden-row' : '')}>
      <header>
        <button type="button" className="row-head" onClick={onOpen} aria-expanded={open} title={open ? 'Свернуть' : 'Изменить ряд'}>
          <strong>Ряд {index + 1}</strong> <span className="ref-chip" title="Буква ряда в формулах">{letter(index + 1)}</span>
          {' · '}{formula ? (row.name || (row.formula ? '= ' + row.formula : 'формула не задана')) : <>{row.name || y?.label || 'поле не выбрано'}, {row.wells_mode === 'current' ? 'текущая скважина' : wells}</>}
          <span className="row-sub">
            {formula ? <>формула · связь рядов: {keyLabel}{row.key === 'nearest' ? ` ±${row.days} дн.` : ''}</> : <>
            {ds?.label ?? row.dataset} → {y?.label ?? row.y} · X: {x?.label ?? row.x}{joined ? ` (${xs?.label ?? row.x_dataset}, ${keyLabel})` : ''}
            {row.kind ? ' · ' + (ds?.kinds.find(k => k.value === row.kind)?.label.toLowerCase() ?? row.kind) : ''}</>}
            {t.op !== 'none' ? ` · ${opLabel}` : ''}
            {' · '}<span className="axis-chip">{axisTitle(row.axis)} {axisHint(row.axis)}</span> · {VIEWS.find(v => v[0] === row.view)?.[1]}{row.stack && (row.view === 'bar' || row.view === 'area') ? ` · стопка «${row.stack}»` : ''}
          </span>
        </button>
        <div className="row-actions">
          <button type="button" className="quiet small" onClick={() => onChange({ hidden: !row.hidden })}
            title={row.hidden ? 'Показать ряд на графике' : 'Скрыть ряд, не удаляя'}>{row.hidden ? 'Показать' : 'Скрыть'}</button>
          <button type="button" className="quiet small" onClick={onDuplicate} title="Копия ряда на свободной оси">Дублировать</button>
          <button type="button" className="quiet small" onClick={onRemove} title="Удалить ряд">Удалить</button>
        </div>
      </header>
      {check && !open && <div className="formula-error" role="alert">Формула: {check}</div>}
      {open && (
        <div className="row-form">
          <div className="kind-group" role="radiogroup" aria-label="Источник">
            <span className="kind-label">Источник</span>
            {([['field', 'Поле данных'], ['formula', 'Формула']] as const).map(([v, label]) => (
              <button key={v} type="button" role="radio" aria-checked={(row.source ?? 'field') === v}
                className={'kind' + ((row.source ?? 'field') === v ? ' on' : '')}
                title={v === 'formula' ? 'Ряд из других рядов макета: A — ряд 1, B — ряд 2…' : 'Поле из данных проекта'}
                onClick={() => onChange(v === 'field' ? { source: undefined } : { source: 'formula', formula: row.formula ?? '' })}>{label}</button>
            ))}
          </div>
          {formula && <FormulaFields row={row} others={others} check={check} keys={catalog?.keys ?? []} onChange={onChange} />}
          {!formula && <>
          <label className="field wide">
            <span className="field-label">Поле Y</span>
            <select value={y ? y.id : ''} onChange={e => { const f = allFields.find(a => a.id === e.target.value); if (f) onPickY(f) }}>
              {!y && <option value="">{row.y || 'выберите поле'}</option>}
              {catalog?.categories.map(c => (
                <optgroup key={c.id} label={c.label}>
                  {c.fields.map(f => <option key={f.id} value={f.id}>{f.label} · {f.dataset_label}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="field wide">
            <span className="field-label">Поле X</span>
            <select value={`${row.x_dataset}.${row.x}`} onChange={e => {
              const [d, ...f] = e.target.value.split('.'); onChange({ x_dataset: d, x: f.join('.') })
            }}>
              {!x && <option value={`${row.x_dataset}.${row.x}`}>{row.x}</option>}
              {catalog?.datasets.map(d => (
                <optgroup key={d.id} label={d.label}>
                  {d.fields.map(f => <option key={f.id} value={f.id}>{f.label}{f.unit ? ', ' + f.unit : ''}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          {joined && (
            <label className="field">
              <span className="field-label">Связь X и Y</span>
              <select value={row.key} onChange={e => onChange({ key: e.target.value })}>
                {catalog?.keys.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
              </select>
            </label>
          )}
          {joined && row.key === 'nearest' && (
            <label className="field number">
              <span className="field-label">± дней</span>
              <input type="number" min={0} max={366} value={row.days}
                onChange={e => { const n = Math.round(Number(e.target.value)); if (Number.isFinite(n) && n >= 0 && n <= 366) onChange({ days: n }) }} />
            </label>
          )}
          {ds?.entity === 'well' && (
            <label className="field">
              <span className="field-label">Скважины ряда</span>
              <select value={row.wells_mode === 'current' ? 'current' : 'fixed'} onChange={e => onChange({ wells_mode: e.target.value as 'fixed' | 'current' })}>
                <option value="fixed">фиксированные скважины</option>
                <option value="current">текущая скважина (макета)</option>
              </select>
            </label>
          )}
          {ds?.entity && !(ds.entity === 'well' && row.wells_mode === 'current') && (
            <MultiSelect label={entity} options={ds.entities} value={row.wells} onChange={w => onChange({ wells: w })}
              prefix={ds.entity === 'well' ? '№ ' : ''} />
          )}
          {!!ds?.kinds.length && (
            <label className="field">
              <span className="field-label">Режим</span>
              <select value={row.kind} onChange={e => onChange({ kind: e.target.value })}>
                <option value="">все</option>
                {ds.kinds.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
              </select>
            </label>
          )}
          {ds?.date_min && (
            <>
              <label className="field date">
                <span className="field-label">Период с</span>
                <input type="date" value={row.date_from} min={ds.date_min ?? undefined} max={ds.date_max ?? undefined}
                  onChange={e => onChange({ date_from: e.target.value })} />
              </label>
              <label className="field date">
                <span className="field-label">по</span>
                <input type="date" value={row.date_to} min={ds.date_min ?? undefined} max={ds.date_max ?? undefined}
                  onChange={e => onChange({ date_to: e.target.value })} />
              </label>
            </>
          )}
          </>}
          <TransformFields t={t} setT={setT} dateX={formula || (x?.kind ?? 'date') === 'date'} />
          <label className="field">
            <span className="field-label">Единица</span>
            <input type="text" value={row.unit ?? ''} maxLength={40} placeholder={formula ? 'нет' : 'авто'}
              title="Пусто — по полю и преобразованию (накопленное тыс. м³/сут → млн м³ и т.п.)"
              onChange={e => onChange({ unit: e.target.value || undefined })} />
          </label>
          <div className="kind-group" role="radiogroup" aria-label="Ось">
            <span className="kind-label">Ось</span>
            {AXES.map(a => (
              <button key={a} type="button" role="radio" aria-checked={row.axis === a} className={'kind' + (row.axis === a ? ' on' : '')}
                title={a === 'y' ? 'Левая шкала' : 'Правая шкала'} onClick={() => onChange({ axis: a })}>{axisTitle(a)}</button>
            ))}
          </div>
          <div className="kind-group" role="radiogroup" aria-label="Вид">
            <span className="kind-label">Вид</span>
            {VIEWS.map(([v, label]) => (
              <button key={v} type="button" role="radio" aria-checked={row.view === v} className={'kind' + (row.view === v ? ' on' : '')}
                onClick={() => onChange({ view: v })}>{label}</button>
            ))}
          </div>
          {(row.view === 'bar' || row.view === 'area') && (
            <label className="field">
              <span className="field-label">Стопка</span>
              <input type="text" value={row.stack ?? ''} placeholder="нет" maxLength={60}
                title="Столбцы или области с одинаковым именем стопки складываются друг на друга; пусто — рядом (столбцы) или поверх (области)"
                onChange={e => onChange({ stack: e.target.value })} />
            </label>
          )}
          <label className="field wide">
            <span className="field-label">Название в легенде</span>
            <input type="text" value={row.name} placeholder={formula ? row.formula ?? '' : y?.label ?? ''} onChange={e => onChange({ name: e.target.value })} />
          </label>
        </div>
      )}
    </article>
  )
}

function FormulaFields({ row, others, check, keys, onChange }: {
  row: BuilderRow; others: { ref: string; title: string; hidden: boolean; self: boolean }[]; check: string
  keys: { value: string; label: string }[]; onChange: (patch: Partial<BuilderRow>) => void
}) {
  const [help, setHelp] = useState(false)
  return (
    <>
      <label className="field wide">
        <span className="field-label">Формула</span>
        <input type="text" className={'formula-input' + (check ? ' bad' : '')} value={row.formula ?? ''} maxLength={500} spellCheck={false}
          placeholder="например A/B или (A-B)/A*100" aria-invalid={!!check}
          onChange={e => onChange({ formula: e.target.value })} />
      </label>
      {check ? <div className="formula-error" role="alert">{check}</div>
        : row.formula?.trim() ? <div className="formula-ok">Формула разобрана.</div> : null}
      <div className="formula-refs">
        {others.filter(o => !o.self).map(o => (
          <button key={o.ref} type="button" className="quiet small" title={`Вставить ${o.ref} в формулу`}
            onClick={() => onChange({ formula: ((row.formula ?? '').trimEnd() + ' ' + o.ref).trim() })}>
            <b>{o.ref}</b> {o.title}{o.hidden ? ' (скрыт)' : ''}
          </button>
        ))}
        <button type="button" className="quiet small" aria-expanded={help} onClick={() => setHelp(h => !h)}>Подсказка</button>
      </div>
      {help && (
        <div className="formula-help">
          <p>Ряды — буквы по порядку (A — ряд 1, B — ряд 2…, дальше R27). Скрытый ряд тоже можно взять в формулу — для промежуточных величин.
            Щелчок по полю в дереве слева добавляет скрытый ряд с этим полем и дописывает его букву.</p>
          <p>Операции: <code>+ − × ÷ ^</code> (можно <code>* /</code>), скобки, числа (<code>2.5</code> или <code>2,5</code>), постоянные <code>pi</code>, <code>e</code>.
            Аргументы функций — через «;».</p>
          <p>Функции: {FUNCTIONS.map(([n, , , d]) => <span key={n}><code>{n}</code> — {d}; </span>)}</p>
          <p>Примеры: {EXAMPLES.map(e => (
            <button key={e} type="button" className="quiet small" onClick={() => onChange({ formula: e })}><code>{e}</code></button>
          ))}</p>
          <p>Точки формулы — точки первого ряда в ней (его X и скважины), остальные ряды подставляются по связи. Деление на ноль, логарифм
            и корень от недопустимого числа — пропуск точки (счётчик — в заметках); «нет данных» в любом ряду — пропуск.</p>
        </div>
      )}
      <label className="field">
        <span className="field-label">Связь рядов</span>
        <select value={row.key} onChange={e => onChange({ key: e.target.value })} title="Как найти значение ряда B для точки ряда A">
          {keys.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
      </label>
      {row.key === 'nearest' && (
        <label className="field number">
          <span className="field-label">± дней</span>
          <input type="number" min={0} max={366} value={row.days}
            onChange={e => { const n = Math.round(Number(e.target.value)); if (Number.isFinite(n) && n >= 0 && n <= 366) onChange({ days: n }) }} />
        </label>
      )}
    </>
  )
}

function TransformFields({ t, setT, dateX }: { t: RowTransform; setT: (p: Partial<RowTransform>) => void; dateX: boolean }) {
  return (
    <>
      <label className="field">
        <span className="field-label">Преобразование</span>
        <select value={t.op} onChange={e => setT({ op: e.target.value as TransformOp })}>
          {TRANSFORMS.map(([v, label]) => <option key={v} value={v} disabled={!dateX && (v === 'day' || v === 'month')}>{label}</option>)}
        </select>
      </label>
      {t.op === 'rolling' && (
        <>
          <label className="field number">
            <span className="field-label">Окно</span>
            <input type="number" min={1} max={10000} value={t.n ?? 7}
              onChange={e => { const n = Math.round(Number(e.target.value)); if (Number.isFinite(n) && n >= 1 && n <= 10000) setT({ n }) }} />
          </label>
          <label className="field">
            <span className="field-label">в</span>
            <select value={t.by ?? 'points'} onChange={e => setT({ by: e.target.value as 'points' | 'days' })}>
              <option value="points">точках</option>
              <option value="days" disabled={!dateX}>сутках</option>
            </select>
          </label>
        </>
      )}
      {(t.op === 'day' || t.op === 'month' || t.op === 'group') && (
        <label className="field">
          <span className="field-label">Сводка</span>
          <select value={t.agg ?? 'mean'} onChange={e => setT({ agg: e.target.value as Agg })}>
            {AGGS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
      )}
      {t.op === 'norm' && (
        <label className="field">
          <span className="field-label">Делить</span>
          <select value={t.norm ?? 'first'} onChange={e => setT({ norm: e.target.value as RowTransform['norm'] })}>
            <option value="first">на первую точку</option>
            <option value="max">на максимум</option>
            <option value="value">на число</option>
          </select>
        </label>
      )}
      {(t.op === 'mul' || t.op === 'div' || t.op === 'add' || (t.op === 'norm' && t.norm === 'value')) && (
        <label className="field number">
          <span className="field-label">Число</span>
          <input type="text" inputMode="decimal" value={t.value ?? ''} placeholder={t.op === 'add' ? '0' : '1000'}
            title="Например 1000 (тыс. → единицы) или 0,0980665 (кгс/см² → МПа)" onChange={e => setT({ value: e.target.value })} />
        </label>
      )}
    </>
  )
}

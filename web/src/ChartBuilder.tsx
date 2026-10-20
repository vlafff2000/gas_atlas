import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { MultiSelect } from './MultiSelect'
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
  keys: { value: string; label: string }[]
}
export type AxisName = 'y' | 'y2' | 'y3' | 'y4' | 'y5'
export interface BuilderRow {
  id: string; dataset: string; y: string; x_dataset: string; x: string; wells: string[]
  date_from: string; date_to: string; kind: string; axis: AxisName; view: 'line' | 'points'
  key: string; days: number; name: string; hidden?: boolean
}
export interface BuilderLayout { series: BuilderRow[]; title: string; x_label: string; axes: Partial<Record<AxisName, string>> }

const AXES: AxisName[] = ['y', 'y2', 'y3', 'y4', 'y5']
const axisTitle = (a: AxisName) => (a === 'y' ? 'Y1' : 'Y' + a.slice(1))
const axisHint = (a: AxisName) => (a === 'y' ? 'левая' : 'правая')
const VIEWS: [BuilderRow['view'], string][] = [['line', 'линия'], ['points', 'точки']]
const newId = () => Math.random().toString(36).slice(2, 10)

export function layoutOf(value: unknown): BuilderLayout {
  const v = (value && typeof value === 'object' ? value : {}) as Partial<BuilderLayout>
  return {
    series: Array.isArray(v.series) ? v.series.map(r => ({ ...r, id: r.id || newId() })) : [],
    title: v.title ?? '', x_label: v.x_label ?? '', axes: v.axes ?? {},
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
    axis: base?.axis ?? axis, view: base?.view ?? 'line', key: base?.key ?? 'well_date', days: base?.days ?? 3,
    name: '', hidden: base?.hidden,
  }
}

export function ChartBuilder({ project, revision, value, onChange }:
  { project: string; revision: number; value: unknown; onChange: (layout: BuilderLayout) => void }) {
  const layout = useMemo(() => layoutOf(value), [value])
  const [catalog, setCatalog] = useState<BuilderCatalog | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [active, setActive] = useState<string | null>(layout.series[layout.series.length - 1]?.id ?? null)

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
    const next = rowFor(f, datasets.get(f.dataset), row.axis, row)
    set({ series: layout.series.map(r => (r.id === row.id ? next : r)) })
  }
  const pickX = (f: BuilderField) => {
    const row = layout.series.find(r => r.id === active)
    if (row) setRow(row.id, { x_dataset: f.dataset, x: f.field })
  }
  const duplicate = (row: BuilderRow) => {
    const copy = { ...row, id: newId(), axis: freeAxis() }
    const at = layout.series.findIndex(r => r.id === row.id)
    set({ series: [...layout.series.slice(0, at + 1), copy, ...layout.series.slice(at + 1)] }); setActive(copy.id)
  }
  const remove = (row: BuilderRow) => {
    const rest = layout.series.filter(r => r.id !== row.id)
    set({ series: rest }); if (active === row.id) setActive(rest[rest.length - 1]?.id ?? null)
  }

  const q = query.trim().toLowerCase()
  const tree = (catalog?.categories ?? []).map(c => ({
    ...c, fields: q ? c.fields.filter(f => (f.label + ' ' + f.dataset_label + ' ' + c.label).toLowerCase().includes(q)) : c.fields,
  })).filter(c => c.fields.length)
  const used = AXES.filter(a => layout.series.some(r => r.axis === a && !r.hidden))
  const autoAxis = (a: AxisName) => [...new Set(layout.series.filter(r => r.axis === a)
    .map(r => fieldOf(r.dataset, r.y)?.label ?? r.y))].join(', ')
  const autoX = [...new Set(layout.series.map(r => withUnit(fieldOf(r.x_dataset, r.x)) || r.x))].join(', ')
  const activeRow = layout.series.find(r => r.id === active)

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
        <h2>Ряды</h2>
        {layout.series.map((r, i) => (
          <RowCard key={r.id} index={i} row={r} catalog={catalog} datasets={datasets} open={r.id === active}
            onOpen={() => setActive(r.id === active ? null : r.id)} onChange={patch => setRow(r.id, patch)}
            onPickY={f => set({ series: layout.series.map(x => (x.id === r.id ? rowFor(f, datasets.get(f.dataset), r.axis, r) : x)) })}
            onDuplicate={() => duplicate(r)} onRemove={() => remove(r)} />
        ))}
        <button type="button" className="primary add-row" onClick={() => addRow()} disabled={!catalog?.categories.length}>+ Добавить ряд</button>

        {layout.series.length > 0 && (
          <fieldset className="builder-labels">
            <legend>Подписи</legend>
            <p className="muted">Пусто — по названиям полей и единицам.</p>
            <LabelInput label="Заголовок" value={layout.title} auto={[...new Set(layout.series.map(r => fieldOf(r.dataset, r.y)?.label ?? r.y))].join(', ')}
              onChange={v => set({ title: v })} />
            <LabelInput label="Ось X" value={layout.x_label} auto={autoX} onChange={v => set({ x_label: v })} />
            {used.map(a => (
              <LabelInput key={a} label={`Ось ${axisTitle(a)}`} value={layout.axes[a] ?? ''} auto={autoAxis(a)}
                onChange={v => set({ axes: { ...layout.axes, [a]: v } })} />
            ))}
          </fieldset>
        )}
      </section>
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

function RowCard({ index, row, catalog, datasets, open, onOpen, onChange, onPickY, onDuplicate, onRemove }: {
  index: number; row: BuilderRow; catalog: BuilderCatalog | null; datasets: Map<string, BuilderDataset>; open: boolean
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

  return (
    <article className={'row-card' + (open ? ' open' : '') + (row.hidden ? ' hidden-row' : '')}>
      <header>
        <button type="button" className="row-head" onClick={onOpen} aria-expanded={open} title={open ? 'Свернуть' : 'Изменить ряд'}>
          <strong>Ряд {index + 1}</strong> · {row.name || y?.label || 'поле не выбрано'}, {wells}
          <span className="row-sub">
            {ds?.label ?? row.dataset} → {y?.label ?? row.y} · X: {x?.label ?? row.x}{joined ? ` (${xs?.label ?? row.x_dataset}, ${keyLabel})` : ''}
            {row.kind ? ' · ' + (ds?.kinds.find(k => k.value === row.kind)?.label.toLowerCase() ?? row.kind) : ''}
            {' · '}<span className="axis-chip">{axisTitle(row.axis)} {axisHint(row.axis)}</span> · {VIEWS.find(v => v[0] === row.view)?.[1]}
          </span>
        </button>
        <div className="row-actions">
          <button type="button" className="quiet small" onClick={() => onChange({ hidden: !row.hidden })}
            title={row.hidden ? 'Показать ряд на графике' : 'Скрыть ряд, не удаляя'}>{row.hidden ? 'Показать' : 'Скрыть'}</button>
          <button type="button" className="quiet small" onClick={onDuplicate} title="Копия ряда на свободной оси">Дублировать</button>
          <button type="button" className="quiet small" onClick={onRemove} title="Удалить ряд">Удалить</button>
        </div>
      </header>
      {open && (
        <div className="row-form">
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
          {ds?.entity && (
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
          <label className="field wide">
            <span className="field-label">Название в легенде</span>
            <input type="text" value={row.name} placeholder={y?.label ?? ''} onChange={e => onChange({ name: e.target.value })} />
          </label>
        </div>
      )}
    </article>
  )
}

import { useEffect, useRef, useState } from 'react'
import { api, type ModuleSpec, type Param, type Params } from './api'
import { MultiSelect } from './MultiSelect'
import { paramsCollapsed, usePref } from './chartPrefs'
import { formatDate } from './format'

interface Props {
  spec: ModuleSpec
  project: string
  panel: number
  values: Params
  onChange: (values: Params) => void
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((v, i) => v === b[i])

/** Выбор по умолчанию из вариантов: 'all' | 'first:N' | 'last:N'. */
function autoPick(rule: string, options: string[]): string[] {
  const [kind, n] = rule.split(':')
  if (kind === 'first') return options.slice(0, Number(n))
  if (kind === 'last') return options.slice(-Number(n))
  return [...options]
}

const visible = (p: Param, values: Params) =>
  !p.show_if || Object.entries(p.show_if).every(([k, v]) => values[k] === v)

/** Одна строка-сводка свёрнутой панели: «№ 31, 45, 540 · Отбор · 2023-2024 – 2025-2026 · Q / дата». */
export function paramSummary(params: Param[], values: Params, options: Record<string, string[] | undefined>): string[] {
  const out: string[] = []
  for (const p of params) {
    if (!visible(p, values)) continue
    const v = values[p.name]
    if (p.kind === 'multi') {
      const list = (v as string[] | undefined) ?? []
      const all = options[p.name] ?? p.options.map(o => String(o.value))
      const name = p.label.toLowerCase()
      if (!list.length) out.push(`${p.label}: ${p.empty}`)
      else if (all.length > 1 && list.length === all.length) out.push(`${p.label}: все (${all.length})`)
      else if (list.length <= 3) out.push(list.map(x => p.prefix + x).join(', '))
      else out.push(`${name[0].toUpperCase() + name.slice(1)}: ${list.length}${all.length ? ' из ' + all.length : ''}`)
    } else if (p.kind === 'choice') {
      const o = p.options.find(o => o.value === v)
      if (o) out.push(o.label)
    } else if (p.kind === 'boolean') {
      if (v) out.push(p.label)
    } else if (p.kind === 'date') {
      if (v) out.push(`${p.label} ${formatDate(String(v))}`)
    } else if (p.kind === 'text') {
      if (v) out.push(p.label)
    } else if (p.kind === 'map') {
      const n = Object.keys((v as Record<string, number> | undefined) ?? {}).length
      if (n) out.push(`${p.label}: ${n}`)
    } else if (v !== null && v !== undefined && v !== '') {
      out.push(`${p.label} ${String(v).replace('.', ',')}${p.unit ? ' ' + p.unit : ''}`)
    }
  }
  return out
}

export function ParamBar({ spec, project, panel, values, onChange }: Props) {
  const [options, setOptions] = useState<Record<string, string[]>>({})
  const [dynamic, setDynamic] = useState<Record<string, string[] | undefined>>({})
  const collapsed = usePref(paramsCollapsed)
  const latest = useRef(values)
  latest.current = values

  useEffect(() => {
    let alive = true
    setOptions({})
    for (const p of spec.params) {
      if (!p.source || p.dynamic) continue
      api.options(project, p.source.dataset, p.source.column)
        .then(list => { if (alive) setOptions(o => ({ ...o, [p.name]: list })) })
        .catch(() => { if (alive) setOptions(o => ({ ...o, [p.name]: [] })) })
    }
    return () => { alive = false }
  }, [spec, project])

  // Несколько вызовов в одном такте (автовыбор нескольких списков) складываются, а не затирают друг друга.
  const set = (name: string, value: unknown) => {
    latest.current = { ...latest.current, [name]: value }
    onChange(latest.current)
  }

  const sections: [string, Param[]][] = []
  for (const p of spec.params) {
    if (!visible(p, values)) continue
    const last = sections[sections.length - 1]
    if (last && last[0] === p.section) last[1].push(p); else sections.push([p.section, [p]])
  }

  const summary = paramSummary(spec.params, values, { ...options, ...dynamic })
  return (
    <div className={'param-bar' + (collapsed ? ' collapsed' : '')}>
      <button type="button" className="param-summary" aria-expanded={!collapsed} onClick={() => paramsCollapsed.set(!collapsed)}
        title={collapsed ? 'Показать параметры' : 'Свернуть параметры в одну строку'}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d={collapsed ? 'M6 3.5 10.5 8 6 12.5' : 'M3.5 6 8 10.5 12.5 6'} /></svg>
        <span className="param-summary-label">Параметры</span>
        {collapsed && <span className="param-summary-text">{summary.join(' · ')}</span>}
        <span className="param-summary-action">{collapsed ? 'Изменить' : 'Свернуть'}</span>
      </button>
      {/* свёрнутые поля остаются на странице: списки сами подбирают варианты по умолчанию */}
      <div className="param-sections" hidden={collapsed}>
      {sections.map(([title, params]) => (
        <fieldset key={title || '-'} className="param-section" aria-label={title || undefined}>
          <span className="param-title" aria-hidden="true">{title}</span>
          <div className="param-fields">
            {params.map(p => p.kind === 'map'
              ? <DynamicMap key={p.name} spec={spec} project={project} param={p} values={values} onChange={v => set(p.name, v)} />
              : p.dynamic
              ? <DynamicMulti key={p.name} spec={spec} project={project} panel={panel} param={p}
                              values={values} onChange={v => set(p.name, v)}
                              onOptions={list => setDynamic(d => (d[p.name] === list ? d : { ...d, [p.name]: list }))} />
              : <Field key={p.name} param={p} value={values[p.name]} options={options[p.name]} onChange={v => set(p.name, v)} />)}
          </div>
        </fieldset>
      ))}
      </div>
    </div>
  )
}

/** Список, варианты которого считает модуль и зависят от других параметров (группы → скважины, режим → периоды). */
function DynamicMulti({ spec, project, param: p, values, onChange, onOptions }:
  { spec: ModuleSpec; project: string; panel: number; param: Param; values: Params; onChange: (v: string[]) => void
    onOptions: (list: string[] | undefined) => void }) {
  const [options, setOptions] = useState<string[] | undefined>()
  const touched = useRef(false)
  const value = (values[p.name] as string[] | undefined) ?? []
  const deps = JSON.stringify(p.depends.map(d => values[d]))

  useEffect(() => {
    const ctrl = new AbortController()
    const current = Object.fromEntries(p.depends.map(d => [d, values[d]]))
    api.paramOptions(spec.id, project, p.name, current, ctrl.signal)
      .then(setOptions)
      .catch(e => { if ((e as Error).name !== 'AbortError') setOptions([]) })
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec.id, project, p.name, deps])

  // Пришли новые варианты: отбросить недопустимое; если ничего не осталось — выбор по умолчанию.
  useEffect(() => {
    onOptions(options)
    if (!options) return
    const kept = value.filter(v => options.includes(v))
    let next = kept
    if (p.auto && options.length > 0 && ((value.length === 0 && !touched.current) || (kept.length === 0 && value.length > 0))) {
      next = autoPick(p.auto, options)
    }
    if (!same(next, value)) onChange(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options])

  return <MultiSelect label={p.label} options={options ?? []} value={value} loading={options === undefined}
    emptyMeaning={p.empty} prefix={p.prefix} onChange={v => { touched.current = true; onChange(v) }} />
}

/** Число на каждый вариант, который считает модуль (порог у каждой группы); пусто — общее значение. */
function DynamicMap({ spec, project, param: p, values, onChange }:
  { spec: ModuleSpec; project: string; param: Param; values: Params; onChange: (v: Record<string, number>) => void }) {
  const [keys, setKeys] = useState<string[]>([])
  const value = (values[p.name] as Record<string, number> | undefined) ?? {}
  const deps = JSON.stringify(p.depends.map(d => values[d]))
  useEffect(() => {
    const ctrl = new AbortController()
    const current = Object.fromEntries(p.depends.map(d => [d, values[d]]))
    api.paramOptions(spec.id, project, p.name, current, ctrl.signal)
      .then(setKeys)
      .catch(e => { if ((e as Error).name !== 'AbortError') setKeys([]) })
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec.id, project, p.name, deps])
  if (keys.length === 0) return null
  const change = (key: string, text: string) => {
    const next = { ...value }
    const n = Number(text.replace(',', '.'))
    if (text.trim() === '' || !Number.isFinite(n) || n < (p.minimum ?? 0)) delete next[key]; else next[key] = n
    onChange(next)
  }
  return (
    <div className="field map" title={p.help}>
      <span className="field-label">{p.label}</span>
      <div className="map-rows">
        {keys.map(k => <MapRow key={k} label={k} value={value[k]} placeholder="общий" onCommit={t => change(k, t)} />)}
      </div>
    </div>
  )
}

function MapRow({ label, value, placeholder, onCommit }:
  { label: string; value: number | undefined; placeholder: string; onCommit: (text: string) => void }) {
  const shown = value === undefined ? '' : String(value).replace('.', ',')
  const [text, setText] = useState(shown)
  useEffect(() => { setText(shown) }, [shown])
  return (
    <label className="map-row">
      <span>{label}</span>
      <input value={text} placeholder={placeholder} inputMode="decimal" aria-label={label}
        onChange={e => setText(e.target.value)} onBlur={() => { if (text !== shown) onCommit(text) }}
        onKeyDown={e => { if (e.key === 'Enter' && text !== shown) onCommit(text) }} />
    </label>
  )
}

/** «?» у параметра, который считается по формуле: пояснение, формула и числовой пример по щелчку. */
function HelpMark({ param: p }: { param: Param }) {
  const [open, setOpen] = useState(false)
  if (!p.formula && !p.example) return null
  return (
    <span className="help-mark">
      <button type="button" className="help-button" aria-expanded={open} aria-label={`Как считается: ${p.label}`}
        title="Как это считается" onClick={e => { e.preventDefault(); setOpen(o => !o) }}>?</button>
      {open && (
        <span className="help-pop" role="note">
          {p.help && <span>{p.help}</span>}
          {p.formula && <code>{p.formula}</code>}
          {p.example && <span className="help-example">Пример. {p.example}</span>}
        </span>
      )}
    </span>
  )
}

function Field({ param: p, value, options, onChange }:
  { param: Param; value: unknown; options?: string[]; onChange: (v: unknown) => void }) {
  if (p.kind === 'multi') {
    const list = options ?? p.options.map(o => String(o.value))
    return <MultiSelect label={p.label} options={list} value={(value as string[]) ?? []} onChange={onChange}
      loading={p.source !== null && options === undefined} emptyMeaning={p.empty} prefix={p.prefix} />
  }
  if (p.kind === 'boolean') {
    return (
      <label className="toggle" title={p.help}>
        <input type="checkbox" checked={Boolean(value)} onChange={e => onChange(e.target.checked)} />
        <span>{p.label}</span><HelpMark param={p} />
      </label>
    )
  }
  if (p.kind === 'date') {
    return (
      <label className="field date" title={p.help}>
        <span className="field-label">{p.label}</span>
        <input type="date" value={(value as string | null) ?? ''} onChange={e => onChange(e.target.value || null)} />
      </label>
    )
  }
  if (p.kind === 'choice') {
    const index = p.options.findIndex(o => o.value === value)
    return (
      <label className="field" title={p.help}>
        <span className="field-label">{p.label}<HelpMark param={p} /></span>
        <select value={index} onChange={e => onChange(p.options[Number(e.target.value)].value)}>
          {p.options.map((o, i) => <option key={i} value={i}>{o.label}</option>)}
        </select>
      </label>
    )
  }
  if (p.kind === 'text') return <TextField param={p} value={(value as string) ?? ''} onChange={onChange} />
  return <NumberField param={p} value={value as number} onChange={onChange} />
}

function TextField({ param: p, value, onChange }: { param: Param; value: string; onChange: (v: unknown) => void }) {
  // Пересчёт — по выходу из поля, а не на каждую букву.
  const [text, setText] = useState(value)
  useEffect(() => { setText(value) }, [value])
  return (
    <label className="field text" title={p.help}>
      <span className="field-label">{p.label}</span>
      <textarea rows={2} value={text} placeholder={p.help} onChange={e => setText(e.target.value)}
        onBlur={() => { if (text !== value) onChange(text) }} />
    </label>
  )
}

function NumberField({ param: p, value, onChange }: { param: Param; value: number; onChange: (v: unknown) => void }) {
  // Локальный текст, чтобы промежуточный ввод («0,») не сбрасывался; запятая допустима.
  const [text, setText] = useState(String(value ?? '').replace('.', ','))
  useEffect(() => { setText(String(value ?? '').replace('.', ',')) }, [value])
  const number = Number(text.replace(',', '.'))
  const invalid = text.trim() === '' || !Number.isFinite(number)
    || (p.minimum !== null && number < p.minimum) || (p.maximum !== null && number > p.maximum)
  const range = [p.minimum !== null ? `от ${p.minimum}` : '', p.maximum !== null ? `до ${p.maximum}` : ''].filter(Boolean).join(' ')
  return (
    <label className={'field number' + (invalid ? ' invalid' : '')} title={p.help || range}>
      <span className="field-label">{p.label}{p.unit ? `, ${p.unit}` : ''}<HelpMark param={p} /></span>
      <input inputMode="decimal" value={text} aria-invalid={invalid}
        onChange={e => setText(e.target.value)}
        onBlur={() => { if (!invalid && number !== value) onChange(number) }}
        onKeyDown={e => { if (e.key === 'Enter' && !invalid) onChange(number) }} />
      {invalid && <span className="field-error">Число {range}</span>}
    </label>
  )
}

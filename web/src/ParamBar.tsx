import { useEffect, useRef, useState } from 'react'
import { api, type ModuleSpec, type Param, type Params } from './api'
import { MultiSelect } from './MultiSelect'

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

export function ParamBar({ spec, project, panel, values, onChange }: Props) {
  const [options, setOptions] = useState<Record<string, string[]>>({})
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

  return (
    <div className="param-bar">
      {sections.map(([title, params]) => (
        <fieldset key={title || '-'} className="param-section" aria-label={title || undefined}>
          <span className="param-title" aria-hidden="true">{title}</span>
          <div className="param-fields">
            {params.map(p => p.dynamic
              ? <DynamicMulti key={p.name} spec={spec} project={project} panel={panel} param={p}
                              values={values} onChange={v => set(p.name, v)} />
              : <Field key={p.name} param={p} value={values[p.name]} options={options[p.name]} onChange={v => set(p.name, v)} />)}
          </div>
        </fieldset>
      ))}
    </div>
  )
}

/** Список, варианты которого считает модуль и зависят от других параметров (группы → скважины, режим → периоды). */
function DynamicMulti({ spec, project, param: p, values, onChange }:
  { spec: ModuleSpec; project: string; panel: number; param: Param; values: Params; onChange: (v: string[]) => void }) {
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
        <span>{p.label}</span>
      </label>
    )
  }
  if (p.kind === 'choice') {
    const index = p.options.findIndex(o => o.value === value)
    return (
      <label className="field" title={p.help}>
        <span className="field-label">{p.label}</span>
        <select value={index} onChange={e => onChange(p.options[Number(e.target.value)].value)}>
          {p.options.map((o, i) => <option key={i} value={i}>{o.label}</option>)}
        </select>
      </label>
    )
  }
  if (p.kind === 'date') {
    return (
      <label className="field" title={p.help}>
        <span className="field-label">{p.label}</span>
        <input type="date" value={(value as string | null) ?? ''} onChange={e => onChange(e.target.value || null)} />
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
      <span className="field-label">{p.label}{p.unit ? `, ${p.unit}` : ''}</span>
      <input inputMode="decimal" value={text} aria-invalid={invalid}
        onChange={e => setText(e.target.value)}
        onBlur={() => { if (!invalid && number !== value) onChange(number) }}
        onKeyDown={e => { if (e.key === 'Enter' && !invalid) onChange(number) }} />
      {invalid && <span className="field-error">Число {range}</span>}
    </label>
  )
}

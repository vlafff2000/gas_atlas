import { useEffect, useState } from 'react'
import { builderApi, type CriterionCfg, type CriterionView } from './api'

const LOGICS: { id: string; title: string }[] = [
  { id: 'sg', title: 'Sg > порога' },
  { id: 'sg_sgcr', title: 'Sg > SGCR + запас' },
  { id: 'sw_swcr', title: 'Sw < SWCR − запас' },
]
const CUSTOM = 'custom'

/** Критерий газа для ГВК и объёма по кубам: пресет или свои числа, и варианты «посчитать по всем опциям». */
export function BuilderCriterion({ project, selected, onChange }: { project: string; selected: string[]; onChange: () => void }) {
  const [view, setView] = useState<CriterionView | null>(null)
  const [variants, setVariants] = useState<CriterionCfg[]>([])
  const [multi, setMulti] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = () => builderApi.criterion(project).then(v => {
    setView(v)
    setVariants(v.variants)
    setMulti(v.variants.length > 0)
  }).catch(e => setError((e as Error).message))

  useEffect(() => { load() }, [project])

  const save = (criterion: CriterionCfg | undefined, list: CriterionCfg[] | undefined) => {
    setBusy(true)
    builderApi.chooseModels(project, selected, { criterion, criterion_variants: list })
      .then(() => { setError(''); load(); onChange() })
      .catch(e => setError((e as Error).message))
      .finally(() => setBusy(false))
  }

  if (!view) return error ? <div className="note warning">{error}</div> : null
  const cur = view.criterion
  const presetId = view.presets.find(p => p.logic === cur.logic && p.value === cur.value && p.fallback === cur.fallback)?.id ?? CUSTOM
  const preset = (id: string) => view.presets.find(p => p.id === id)

  return (
    <div className="builder-criterion">
      <label className="field"><span className="field-label">Критерий газа</span>
        <select value={presetId} disabled={busy} onChange={e => {
          const p = preset(e.target.value)
          if (p) save({ logic: p.logic, value: p.value, fallback: p.fallback }, undefined)
        }}>
          {view.presets.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}
          {presetId === CUSTOM && <option value={CUSTOM}>Свой критерий</option>}
        </select></label>
      <p className="muted" title="Какой критерий сейчас считает ГВК и объём по кубам">{view.formula}</p>
      <div className="builder-row" key={`${cur.logic}|${cur.value}|${cur.fallback}`}>
        <label className="field"><span className="field-label">Логика</span>
          <select defaultValue={cur.logic} disabled={busy} onChange={e => save({ ...cur, logic: e.target.value }, undefined)}>
            {LOGICS.map(l => <option key={l.id} value={l.id}>{l.title}</option>)}
          </select></label>
        <label className="field"><span className="field-label">Порог / запас</span>
          <input type="number" min={0} max={0.99} step={0.01} defaultValue={cur.value} disabled={busy}
            onBlur={e => save({ ...cur, value: Number(e.target.value) }, undefined)} /></label>
        <label className="field" title="Критическая насыщенность, если в INIT её нет по ячейке">
          <span className="field-label">SGCR, если нет в INIT</span>
          <input type="number" min={0} max={0.99} step={0.01} defaultValue={cur.fallback} disabled={busy}
            onBlur={e => save({ ...cur, fallback: Number(e.target.value) }, undefined)} /></label>
      </div>

      <label className="check" title="Каждый вариант даёт свою строку на графиках и в таблицах, подпись — модель · критерий">
        <input type="checkbox" checked={multi} disabled={busy} onChange={e => {
          setMulti(e.target.checked)
          if (!e.target.checked) save(undefined, [])
        }} /> Посчитать по всем опциям (варианты)
      </label>
      {multi && (
        <div className="builder-variants">
          {variants.map((v, i) => (
            <div key={i} className="builder-row">
              <select value={v.logic} disabled={busy} onChange={e => setVariants(vs => vs.map((x, j) => j === i ? { ...x, logic: e.target.value } : x))}>
                {LOGICS.map(l => <option key={l.id} value={l.id}>{l.title}</option>)}
              </select>
              <input type="number" min={0} max={0.99} step={0.01} value={v.value} disabled={busy}
                onChange={e => setVariants(vs => vs.map((x, j) => j === i ? { ...x, value: Number(e.target.value) } : x))} />
              <button type="button" className="kind" disabled={busy} onClick={() => setVariants(vs => vs.filter((_, j) => j !== i))}>Убрать</button>
            </div>
          ))}
          <button type="button" className="kind" disabled={busy || variants.length >= view.max_variants}
            onClick={() => setVariants(vs => [...vs, { logic: 'sg', value: 0.01, fallback: cur.fallback }])}>Добавить вариант</button>
          {' '}
          <button type="button" className="kind" disabled={busy || variants.length === 0}
            onClick={() => save(undefined, variants)}>Применить варианты</button>
          <p className="muted">До {view.max_variants} вариантов; каждый — полный проход по рестартам, поэтому долго. Одинаковые схлопываются.</p>
        </div>
      )}
      {error && <div className="note warning">{error}</div>}
    </div>
  )
}

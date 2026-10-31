import { useEffect, useMemo, useState } from 'react'
import { api, type Project } from './api'
import { fundApi, type FundTable } from './api_fund'
import './import.css'

/** «Фонды скважин»: эксплуатационная, наблюдательная, геофизическая, контрольная. Подсказка программы — с причиной, решение за инженером. */
export function FundPage({ project, onProject }: { project: Project; onProject: (p: Project) => void }) {
  const [info, setInfo] = useState<FundTable | null>(null)
  const [message, setMessage] = useState<{ text: string; level: 'info' | 'warning' } | null>(null)
  const [text, setText] = useState('')
  const [fund, setFund] = useState('')
  const [onlyManual, setOnlyManual] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [target, setTarget] = useState('observation')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fundApi.get(project.id).then(setInfo).catch(e => setMessage({ text: (e as Error).message, level: 'warning' }))
  }, [project.id])

  const label = useMemo(() => Object.fromEntries((info?.funds ?? []).map(f => [f.id, f.label])), [info])
  const rows = useMemo(() => (info?.wells ?? []).filter(r =>
    (!text || (r.well + ' ' + r.group).toLowerCase().includes(text.toLowerCase())) &&
    (!fund || r.fund === fund) && (!onlyManual || r.manual)), [info, text, fund, onlyManual])
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const r of info?.wells ?? []) c[r.fund || ''] = (c[r.fund || ''] ?? 0) + 1
    return c
  }, [info])

  const apply = async (wells: string[], value: string) => {
    if (!wells.length) return
    setBusy(true); setMessage(null)
    try {
      const next = await fundApi.assign(project.id, Object.fromEntries(wells.map(w => [w, value])), info?.revision)
      setInfo(next); setPicked(new Set())
      onProject(await api.project(project.id))
      setMessage({ text: value === 'auto' ? `Скважин с подсказкой программы: ${wells.length}.` : `Скважин переведено в «${label[value]}»: ${wells.length}.`, level: 'info' })
    } catch (e) { setMessage({ text: (e as Error).message, level: 'warning' }) } finally { setBusy(false) }
  }
  const toggle = (w: string) => setPicked(old => { const n = new Set(old); if (n.has(w)) n.delete(w); else n.add(w); return n })
  const allShown = rows.length > 0 && rows.every(r => picked.has(r.well))

  return (
    <>
      <header className="module-title">
        <div>
          <h1>Фонды скважин</h1>
          <p className="lede">Эксплуатационные, наблюдательные, геофизические (ГИС без перфораций) и контрольные скважины. Программа лишь подсказывает фонд и показывает причину; решение за инженером. Настройка общая для Карт и других программ.</p>
        </div>
      </header>
      {!info ? <p className="muted loading-line">Загрузка…</p> : info.wells.length === 0 ? (
        <div className="note info">В проекте нет скважин: сначала загрузите расходы, ГИС или давления.</div>
      ) : (
        <section className="panel">
          <p className="muted">{info.funds.map(f => `${f.label}: ${counts[f.id] ?? 0}`).join(' · ')}{counts[''] ? ` · без фонда: ${counts['']}` : ''}</p>
          <div className="toolbar">
            <label className="field"><span className="field-label">Поиск</span>
              <input value={text} onChange={e => setText(e.target.value)} placeholder="номер или группа" /></label>
            <label className="field"><span className="field-label">Фонд</span>
              <select value={fund} onChange={e => setFund(e.target.value)}>
                <option value="">все</option>{info.funds.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
              </select></label>
            <label className="toggle"><input type="checkbox" checked={onlyManual} onChange={e => setOnlyManual(e.target.checked)} /><span>только выбранные вручную</span></label>
          </div>
          <div className="toolbar">
            <span>Отмечено: {picked.size}</span>
            <button type="button" className="quiet" onClick={() => setPicked(allShown ? new Set() : new Set(rows.map(r => r.well)))}>
              {allShown ? 'Снять отметки' : `Отметить показанные (${rows.length})`}</button>
            <select value={target} onChange={e => setTarget(e.target.value)} aria-label="Перевести в фонд">
              {info.funds.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
            <button type="button" className="primary" disabled={busy || !picked.size} onClick={() => apply([...picked], target)}>Перевести отмеченные</button>
            <button type="button" className="quiet" disabled={busy || !picked.size} onClick={() => apply([...picked], 'auto')}>Вернуть подсказку</button>
          </div>
          {message && <div className={'note ' + message.level} role="status">{message.text}</div>}
          <div style={{ maxHeight: '60vh', overflow: 'auto' }}>
            <table className="data-grid">
              <thead><tr><th></th><th>Скважина</th><th>Группа</th><th>Фонд</th><th>Подсказка программы</th><th>Откуда известна</th></tr></thead>
              <tbody>{rows.map(r => (
                <tr key={r.well}>
                  <td><input type="checkbox" checked={picked.has(r.well)} onChange={() => toggle(r.well)} aria-label={'Отметить ' + r.well} /></td>
                  <td>№ {r.well}</td><td>{r.group || '—'}</td>
                  <td><select value={r.fund} disabled={busy} onChange={e => apply([r.well], e.target.value)}>
                    {!r.fund && <option value="">не определён</option>}
                    {info.funds.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
                  </select>{r.manual && <span className="muted"> · вручную</span>}</td>
                  <td className="muted">{r.hint ? `${label[r.hint]}: ` : ''}{r.reason}</td>
                  <td className="muted">{r.sources.join(', ') || '—'}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}

import { useEffect, useRef, useState } from 'react'
import type { Project } from './api'
import { passportApi, type PassportInfo } from './api_passport'
import { MultiSelect } from './MultiSelect'

/** «Паспорт скважины» 5.8: скважина, разделы, периоды, комментарий инженера и PDF. */
export function PassportPage({ project, onProject }: { project: Project; onProject: (p: Project) => void }) {
  const [info, setInfo] = useState<PassportInfo | null>(null)
  const [well, setWell] = useState<string | undefined>()
  const [sections, setSections] = useState<string[]>([])
  const [periods, setPeriods] = useState<Record<string, string[]>>({})
  const [comment, setComment] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState<'' | 'comment' | 'pdf'>('')
  const [message, setMessage] = useState<{ text: string; level: 'info' | 'warning' } | null>(null)
  const started = useRef(false)

  useEffect(() => {
    const ctrl = new AbortController()
    passportApi.info(project.id, well, ctrl.signal).then(next => {
      // Разделы и периоды остаются при смене скважины; комментарий — свой у каждой скважины.
      if (!started.current) {
        started.current = true
        setSections(next.sections.map(s => s.value))
        setPeriods(Object.fromEntries(Object.entries(next.periods).map(([k, v]) => [k, v.default])))
      }
      setInfo(next)
      setComment(next.comment); setSaved(next.comment)
      if (!well && next.well) setWell(next.well)
    }).catch(e => {
      if ((e as Error).name !== 'AbortError') setMessage({ text: (e as Error).message, level: 'warning' })
    })
    return () => ctrl.abort()
  }, [project.id, project.revision, well])

  const saveComment = async () => {
    if (!well) return
    setBusy('comment'); setMessage(null)
    try {
      const next = await passportApi.saveComment(project.id, well, comment)
      setSaved(next.comment); onProject(next)
      setMessage({ text: 'Комментарий сохранен в проекте (виден и в версии 5.8).', level: 'info' })
    } catch (e) { setMessage({ text: (e as Error).message, level: 'warning' }) } finally { setBusy('') }
  }
  const createPdf = async () => {
    if (!well) return
    setBusy('pdf'); setMessage(null)
    try {
      const name = await passportApi.pdf(project.id, well, sections, periods, comment)
      setMessage({ text: `Паспорт создан и сохранен в выгрузках проекта: ${name}`, level: 'info' })
    } catch (e) { setMessage({ text: 'Не удалось создать паспорт: ' + (e as Error).message, level: 'warning' }) } finally { setBusy('') }
  }

  return (
    <>
      <header className="module-title">
        <div>
          <h1>Паспорт скважины</h1>
          <p className="lede">Динамика, ГДИ, реагирование, расчетные параметры и комментарий инженера в PDF.</p>
        </div>
      </header>
      {!info ? <p className="muted loading-line">Загрузка…</p> : info.wells.length === 0 ? (
        <div className="note info">{info.note ?? 'Сначала загрузите данные скважин.'}</div>
      ) : (
        <section className="panel">
          <div className="param-bar">
            <fieldset className="param-section">
              <span className="param-title">Выбор</span>
              <div className="param-fields">
                <label className="field">
                  <span className="field-label">Скважина для паспорта</span>
                  <select value={well ?? ''} onChange={e => setWell(e.target.value)}>
                    {info.wells.map(w => <option key={w} value={w}>№ {w}</option>)}
                  </select>
                </label>
                {Object.entries(info.periods).filter(() => sections.includes('production')).map(([kind, p]) => (
                  <MultiSelect key={kind} label={`${p.label}: периоды паспорта`} options={p.options}
                    value={periods[kind] ?? []} emptyMeaning="ничего"
                    onChange={v => setPeriods(old => ({ ...old, [kind]: v }))} />
                ))}
              </div>
            </fieldset>
            <fieldset className="param-section">
              <span className="param-title">Разделы паспорта</span>
              <div className="param-fields">
                {info.sections.map(s => (
                  <label key={s.value} className="toggle">
                    <input type="checkbox" checked={sections.includes(s.value)}
                      onChange={e => setSections(old => e.target.checked
                        ? info.sections.map(x => x.value).filter(v => v === s.value || old.includes(v))
                        : old.filter(v => v !== s.value))} />
                    <span>{s.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
          <label className="passport-comment">
            <span className="field-label">Комментарий инженера</span>
            <textarea rows={7} value={comment} onChange={e => setComment(e.target.value)}
              style={{ width: '100%', maxWidth: '110ch', font: 'inherit', padding: 8, boxSizing: 'border-box' }} />
          </label>
          <div className="toolbar">
            <button type="button" className="quiet" disabled={busy !== '' || comment === saved} onClick={saveComment}>
              {busy === 'comment' ? 'Сохраняю…' : 'Сохранить комментарий'}
            </button>
            <button type="button" className="primary" disabled={busy !== '' || sections.length === 0} onClick={createPdf}>
              {busy === 'pdf' ? 'Формирование паспорта…' : 'Создать паспорт PDF'}
            </button>
            {sections.length === 0 && <span className="muted">Выберите хотя бы один раздел.</span>}
          </div>
          {message && <div className={'note ' + message.level} role="status">{message.text}</div>}
        </section>
      )}
    </>
  )
}

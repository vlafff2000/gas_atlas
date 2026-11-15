import { useEffect, useState } from 'react'
import { importApi, type ChecklistItem } from './api_import'
import type { Project } from './api'
import { projectsApi, type DatasetOption } from './api_projects'

/** Удаление наборов данных проекта: выбрать, посмотреть, что будет удалено, подтвердить. Перед удалением — резервная копия, после — «Вернуть». */
function DeleteDatasets({ project, onProject }: { project: Project; onProject?: (p: Project) => void }) {
  const [options, setOptions] = useState<DatasetOption[]>([])
  const [chosen, setChosen] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ text: string; ok: boolean; undo?: string } | null>(null)

  useEffect(() => {
    projectsApi.datasets(project.id).then(r => { setOptions(r.items); setChosen(c => c.filter(k => r.items.some(i => i.key === k))) })
      .catch(() => setOptions([]))
  }, [project.id, project.revision])

  if (!options.length && !message) return null
  const toggle = (key: string) => setChosen(c => c.includes(key) ? c.filter(k => k !== key) : [...c, key])
  const remove = async () => {
    setBusy(true)
    try {
      const plan = await projectsApi.datasetsPlan(project.id, chosen)
      const list = plan.items.map(i => `• ${i.label}: ${i.rows} строк`).join('\n')
      if (window.confirm(`Будет удалено из проекта «${project.name}»:\n${list}\nВсего ${plan.total} строк.\n\nПеред удалением сохранится резервная копия проекта, потом данные можно вернуть. Удалить?`)) {
        const done = await projectsApi.datasetsDelete(project.id, chosen, project.revision)
        onProject?.(done.project)
        setChosen([])
        setMessage({ text: `Удалено строк: ${done.total}. Резервная копия: ${done.backup}.`, ok: true, undo: done.undo ?? undefined })
      }
    } catch (e) { setMessage({ text: (e as Error).message, ok: false }) }
    setBusy(false)
  }
  const undo = async () => {
    if (!message?.undo) return
    setBusy(true)
    try {
      onProject?.(await projectsApi.rollback(project.id, message.undo, project.revision))
      setMessage({ text: 'Удаление отменено: данные возвращены.', ok: true })
    } catch (e) { setMessage({ text: (e as Error).message, ok: false }) }
    setBusy(false)
  }
  return (
    <details className="delete-datasets">
      <summary><strong>Удалить данные из проекта</strong></summary>
      <p className="muted small">Например, перед загрузкой обновлённой БД ГИС: отметьте наборы и удалите их, затем загрузите новые. Ничего не удаляется без подтверждения, перед удалением сохраняется копия проекта.</p>
      <ul className="checklist-items">
        {options.map(o => (
          <li key={o.key}>
            <label><input type="checkbox" checked={chosen.includes(o.key)} onChange={() => toggle(o.key)} /> {o.label}</label>
            <span className="muted small"> {o.rows} строк</span>
          </li>
        ))}
      </ul>
      <div className="row">
        <button type="button" disabled={busy || !chosen.length} onClick={remove}>Удалить выбранное…</button>
      </div>
      {message && (
        <div className={'note ' + (message.ok ? 'info' : 'warning')} role="status">
          {message.text}
          {message.undo && <> <button type="button" className="quiet small" disabled={busy} onClick={undo}>Вернуть удалённое</button></>}
        </div>
      )}
    </details>
  )
}

/** Чек-лист всего, что можно загрузить в проект: что уже есть (и сколько), чего нет. Щелчок по строке показывает, в каком виде нужен файл. */
export function ImportChecklist({ project, onProject }: { project: Project; onProject?: (p: Project) => void }) {
  const [items, setItems] = useState<ChecklistItem[] | null>(null)
  const [open, setOpen] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    importApi.checklist(project.id).then(r => setItems(r.items)).catch(e => setError((e as Error).message))
  }, [project.id, project.revision])

  if (error) return <div className="note warning">Чек-лист данных: {error}</div>
  if (!items) return null
  const have = items.filter(i => i.count > 0).length
  const shown = items.find(i => i.key === open)

  return (
    <section className="import-checklist" aria-label="Чек-лист данных проекта">
      <details open>
        <summary><strong>Чек-лист данных</strong> · загружено {have} из {items.length}</summary>
        <p className="muted small">Что можно загрузить в проект и что уже загружено. Щёлкните по строке: что именно загружено (скважины, сезоны, периоды) и в каком виде нужен файл.</p>
        <ul className="checklist-items">
          {items.map(i => (
            <li key={i.key}>
              <button type="button" className={'link' + (i.count > 0 ? ' have' : ' missing')} aria-expanded={open === i.key}
                      onClick={() => setOpen(open === i.key ? '' : i.key)}>
                <span aria-hidden="true">{i.count > 0 ? '✓' : '○'}</span> {i.label}
              </button>
              <span className="muted small"> {i.count > 0 ? (i.summary || `${i.count} ${i.unit}`) : 'нет данных'}</span>
            </li>
          ))}
        </ul>
        {shown && (
          <div className="checklist-detail">
            <h3>{shown.label}</h3>
            <p className="small">{shown.count > 0 ? 'Уже в проекте.' : 'В проекте пока нет.'} Нужно для: {shown.used}.</p>
            {shown.details.length > 0 && (
              <table className="data-grid checklist-facts" aria-label="Что загружено">
                <tbody>{shown.details.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}</tbody>
              </table>
            )}
            {shown.columns.length > 0 && (
              <p className="small muted">В каком виде нужен файл:</p>
            )}
            {shown.columns.length > 0 && (
              <div className="table-scroll">
                <table className="data-grid">
                  <thead><tr>{shown.columns.map((c, k) => <th key={k}>{c}</th>)}</tr></thead>
                  {shown.example.length > 0 && <tbody><tr>{shown.example.map((c, k) => <td key={k}>{c}</td>)}</tr></tbody>}
                </table>
              </div>
            )}
            {shown.note && <p className="small">{shown.note}</p>}
            <div className="row">
              {shown.template && <button type="button" onClick={() => void importApi.template(shown.template!)}>Скачать шаблон</button>}
              {shown.example_file && <button type="button" onClick={() => void importApi.template(shown.example_file!)}>Скачать пример</button>}
              <span className="muted small">Загрузить можно в окне ниже: тип файла определяется сам.</span>
            </div>
          </div>
        )}
        <DeleteDatasets project={project} onProject={onProject} />
      </details>
    </section>
  )
}

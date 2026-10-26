import { useEffect, useState } from 'react'
import { importApi, type ChecklistItem } from './api_import'
import type { Project } from './api'

/** Чек-лист всего, что можно загрузить в проект: что уже есть (и сколько), чего нет. Щелчок по строке показывает, в каком виде нужен файл. */
export function ImportChecklist({ project }: { project: Project }) {
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
              <table className="raw checklist-facts" aria-label="Что загружено">
                <tbody>{shown.details.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}</tbody>
              </table>
            )}
            {shown.columns.length > 0 && (
              <p className="small muted">В каком виде нужен файл:</p>
            )}
            {shown.columns.length > 0 && (
              <div className="table-scroll">
                <table className="raw">
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
      </details>
    </section>
  )
}

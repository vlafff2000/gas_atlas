// Мастер первого запуска: создать проект → загрузить файлы → проверить данные → открыть Обзор.
import { useState } from 'react'
import type { Project } from './api'
import { LARGE_DEMO_HINT } from './api'
import { projectsApi } from './api_projects'
import { RestoreBox } from './ProjectPage'

export const hasData = (p: Project) => Object.values(p.tables).some(n => n > 0)

interface Step { title: string; text: string; done: boolean; action?: { label: string; href: string } }

function Steps({ steps }: { steps: Step[] }) {
  const current = steps.findIndex(s => !s.done)
  return (
    <ol className="first-steps">
      {steps.map((s, i) => (
        <li key={s.title} className={s.done ? 'done' : i === current ? 'current' : ''}>
          <span className="mark" aria-hidden="true">{s.done ? '✓' : i + 1}</span>
          <div>
            <strong>{s.title}</strong>
            <p>{s.text}</p>
            {s.action && !s.done && (
              <a className={'link-button' + (i === current ? ' primary' : '')} href={s.action.href}>{s.action.label}</a>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

/** Проектов ещё нет: шаг 1 — назвать объект и создать проект (или открыть демонстрацию / резервную копию). */
export function NewProjectSteps({ onDemo, onOpen }:
  { onDemo: (large?: boolean) => Promise<void>; onOpen: (id: string) => void }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const create = async () => {
    setBusy(true); setError(null)
    try { onOpen((await projectsApi.create(name)).id); location.hash = '#/@import' }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const large = () => { setBusy(true); onDemo(true).finally(() => setBusy(false)) }
  return (
    <div className="empty first-run">
      <h1>Начало работы</h1>
      <p>Четыре шага до первого графика. Проекты общие с версией 5.8.</p>
      <Steps steps={[
        { title: 'Создайте проект', text: 'Один проект — один объект (ПХГ): в нём данные, настройки и выгрузки.', done: false },
        { title: 'Загрузите файлы', text: 'Книги Excel и таблицы CSV: программа сама определит тип и шапку.', done: false },
        { title: 'Проверьте данные', text: 'Программа найдёт сомнительные значения: Рзаб выше Рпл, скачки дебита, нули, повторы.', done: false },
        { title: 'Откройте Обзор и разделы', text: 'Производительность, ГДИ, реагирование, кроссплот, поскважинный анализ.', done: false },
      ]} />
      <div className="form-row">
        <label className="field wide">
          <span className="field-label">Название объекта</span>
          <input value={name} maxLength={120} placeholder="Например, Касимовское ПХГ" onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && name.trim()) create() }} />
        </label>
        <button type="button" className="primary" disabled={busy || !name.trim()} onClick={create}>Создать проект</button>
      </div>
      {error && <div className="note warning" role="alert">{error}</div>}
      <p className="muted">Или посмотрите, как всё работает, на синтетических данных:</p>
      <div className="toolbar">
        <button type="button" className="quiet" disabled={busy} onClick={() => onDemo()}>Открыть демонстрационный объект</button>
        <button type="button" className="quiet" disabled={busy} onClick={large} title={LARGE_DEMO_HINT}>
          {busy ? 'Создание…' : 'Большой демо-объект (2 млн строк)'}
        </button>
      </div>
      <RestoreBox onOpen={onOpen} />
    </div>
  )
}

/** Проект создан, данных нет: шаги 2–4 вместо пустого Обзора. */
export function EmptyProjectSteps({ project }: { project: Project }) {
  return (
    <div className="empty first-run">
      <h1>Проект «{project.name}» создан</h1>
      <p>Осталось загрузить данные.</p>
      <Steps steps={[
        { title: 'Проект создан', text: project.name, done: true },
        { title: 'Загрузите файлы', text: 'Перетащите книги Excel или таблицы CSV сразу все: тип листов, шапка и колонки определятся сами. '
          + 'Примеры файлов и шаблоны — на странице импорта.', done: false, action: { label: 'Загрузить файлы', href: '#/@import' } },
        { title: 'Проверьте данные', text: 'После загрузки откроется отчёт: что выглядит сомнительно. Позже его можно открыть в разделе «Проверка данных».',
          done: false, action: { label: 'Открыть проверку данных', href: '#/quality' } },
        { title: 'Откройте Обзор и разделы', text: 'Обзор покажет состав проекта; графики — в разделах слева.', done: false },
      ]} />
    </div>
  )
}

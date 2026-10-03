// Раздел «Проекты» (5.8: app/ui/extras.py) и общий вход для страниц «Экспорт», «Проекты», «Настройки».
import { useCallback, useEffect, useState } from 'react'
import { api, LARGE_DEMO_HINT, type Project } from './api'
import { bytes, projectsApi, saveLink, type ProjectDetails, type RestorePreview } from './api_projects'
import { ExportPage } from './ExportPage'
import { SettingsPage } from './SettingsPage'
import { formatDate } from './format'
import './project_pages.css'

export interface PageProps {
  project: Project
  projects: Project[]
  onProject: (p: Project) => void        // текущий проект изменился (ревизия, настройки)
  onOpen: (id: string) => void           // открыть другой (новый, копию, восстановленный) проект
}

export function ProjectPages({ page, ...props }: PageProps & { page: string }) {
  if (page === '@export') return <ExportPage key={props.project.id} {...props} />
  if (page === '@settings') return <SettingsPage key={props.project.id} {...props} />
  if (page === '@projects') return <ProjectsPage key={props.project.id} {...props} />
  return <div className="note warning">Нет такого раздела. Выберите раздел в меню слева.</div>
}

export function useDetails(pid: string, revision: number) {
  const [details, setDetails] = useState<ProjectDetails | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => projectsApi.details(pid).then(d => { setDetails(d); setError(null) })
    .catch(e => setError((e as Error).message)), [pid])
  useEffect(() => { reload() }, [reload, revision])
  return { details, error, reload }
}

export function Toast({ text, onClose }: { text: string | null; onClose: () => void }) {
  useEffect(() => {
    if (!text) return
    const timer = setTimeout(onClose, 9000)
    return () => clearTimeout(timer)
  }, [text, onClose])
  if (!text) return null
  return (
    <div className="toast" role="status">
      <span>{text}</span>
      <button type="button" aria-label="Закрыть" onClick={onClose}>×</button>
    </div>
  )
}

function ProjectsPage({ project, projects, onProject, onOpen }: PageProps) {
  const { details, error, reload } = useDetails(project.id, project.revision)
  const [name, setName] = useState(project.name)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const closeToast = useCallback(() => setToast(null), [])
  useEffect(() => setName(project.name), [project.name])

  const act = async (label: string, work: () => Promise<void>) => {
    setBusy(label)
    try { await work() } catch (e) { setToast((e as Error).message) } finally { setBusy(null) }
  }
  const rename = () => act('rename', async () => {
    onProject(await projectsApi.rename(project.id, name, project.revision))
    setToast('Проект переименован.')
  })
  const copy = () => act('copy', async () => {
    const created = await projectsApi.copy(project.id)
    onOpen(created.id)
  })
  const largeDemo = () => act('demo', async () => {
    onOpen((await api.createDemo(true)).id)
  })
  const create = () => act('create', async () => {
    const created = await projectsApi.create(newName)
    setNewName('')
    onOpen(created.id)
  })

  return (
    <>
      <header className="module-title">
        <div>
          <h1>Проекты</h1>
          <p className="lede">Название, копии, сохраненные параметры и готовые выгрузки проекта.</p>
        </div>
      </header>
      {error && <div className="note warning" role="alert">{error}</div>}

      <section className="table-block">
        <div className="block-head"><h3>Все проекты</h3><span className="muted">{projects.length}</span></div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Проект</th><th>Версия</th><th>Обновлен</th><th className="number">Строк данных</th><th /></tr></thead>
            <tbody>
              {projects.map(p => (
                <tr key={p.id} className={p.id === project.id ? 'is-current' : undefined}>
                  <td>{p.name}{p.demo ? ' (демо)' : ''}</td>
                  <td>{(p as Project & { version?: string }).version ?? ''}</td>
                  <td>{formatDate(p.updated)}</td>
                  <td className="number">{Object.values(p.tables).reduce((a, b) => a + b, 0).toLocaleString('ru-RU')}</td>
                  <td>{p.id === project.id ? <span className="muted">открыт</span>
                    : <button type="button" className="quiet small" onClick={() => onOpen(p.id)}>Открыть</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="form-block">
        <h2>Текущий проект</h2>
        <div className="form-row">
          <label className="field wide">
            <span className="field-label">Название текущего проекта</span>
            <input value={name} maxLength={120} onChange={e => setName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') rename() }} />
          </label>
          <button type="button" className="quiet" disabled={busy !== null || !name.trim() || name.trim() === project.name}
            onClick={rename}>Переименовать проект</button>
        </div>
        <div className="form-row">
          <button type="button" className="quiet" disabled={busy !== null} onClick={copy}>
            {busy === 'copy' ? 'Копирование проекта…' : 'Создать копию проекта с данными и настройками'}
          </button>
        </div>
      </section>

      <section className="form-block">
        <h2>Новый проект</h2>
        <div className="form-row">
          <label className="field wide">
            <span className="field-label">Название объекта</span>
            <input value={newName} maxLength={120} onChange={e => setNewName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && newName.trim()) create() }} />
          </label>
          <button type="button" className="primary" disabled={busy !== null || !newName.trim()} onClick={create}>Создать</button>
        </div>
        <div className="form-row">
          <button type="button" className="quiet" disabled={busy !== null} onClick={largeDemo}
            title={LARGE_DEMO_HINT}>
            {busy === 'demo' ? 'Создание большого демо-объекта…' : 'Создать большой демо-объект (2 млн строк)'}
          </button>
        </div>
      </section>

      <section className="table-block">
        <div className="block-head">
          <h3>Сохраненные выгрузки</h3>
          <button type="button" className="quiet small" onClick={reload}>Обновить список</button>
        </div>
        {!details ? <p className="muted pad">Загрузка…</p>
          : details.exports.length === 0 ? <p className="muted pad">Архивы, Word-отчеты и PDF-паспорта появятся здесь после формирования.</p>
          : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Файл</th><th>Создан</th><th className="number">Размер</th><th /></tr></thead>
                <tbody>
                  {details.exports.map(f => (
                    <tr key={f.name}>
                      <td>{f.name}</td>
                      <td>{formatDate(f.modified)}</td>
                      <td className="number">{bytes(f.bytes)}</td>
                      <td><a className="link-button" href={projectsApi.exportUrl(project.id, f.name)} download>Скачать</a></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </section>

      <details className="table-block">
        <summary className="block-head"><h3>Сохраненные параметры просмотра</h3></summary>
        <pre className="json">{JSON.stringify(details?.panels ?? {}, null, 2)}</pre>
      </details>

      <div className="toolbar">
        <button type="button" className="quiet" disabled={!details?.log} title={details?.log ? '' : 'Журнал ошибок пока пуст'}
          onClick={() => saveLink(projectsApi.logUrl)}>Скачать журнал ошибок</button>
      </div>
      <Toast text={toast} onClose={closeToast} />
    </>
  )
}

/** Восстановление резервной копии (.zip) или перенос проекта версии 1 (.gas.json) — как в 5.8, с предпросмотром. */
export function RestoreBox({ onOpen, label = 'Открыть резервную копию или старый проект .gas.json' }:
  { onOpen: (id: string) => void; label?: string }) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<RestorePreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const choose = async (f: File | null) => {
    setFile(f); setPreview(null); setError(null)
    if (!f) return
    try { setPreview(await projectsApi.restorePreview(f)) } catch (e) { setError('Предпросмотр проекта: ' + (e as Error).message) }
  }
  const restore = async () => {
    if (!file) return
    setBusy(true)
    try { onOpen((await projectsApi.restore(file)).id) } catch (e) { setError('Не удалось восстановить: ' + (e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <div className="restore">
      <label className="field wide">
        <span className="field-label">{label}</span>
        <input type="file" accept=".zip,.json" onChange={e => choose(e.target.files?.[0] ?? null)} />
      </label>
      {preview && (
        <div className="restore-preview">
          <strong>Предпросмотр проекта · {file?.name}</strong>
          <pre className="json">{JSON.stringify(preview.info, null, 2)}</pre>
          {preview.kind === 'legacy' ? <p className="muted">Записей: {preview.count}</p>
            : <p className="muted">Файлов в архиве: {preview.count}{preview.files && preview.count > preview.files.length ? ` (показаны первые ${preview.files.length})` : ''}</p>}
          {preview.files && (
            <ul className="file-list">{preview.files.map(f => <li key={f.name}>{f.name} <span className="muted">· {bytes(f.bytes)}</span></li>)}</ul>
          )}
          {preview.rows && preview.rows.length > 0 && (
            <div className="table-scroll">
              <table>
                <thead><tr>{preview.columns?.map(c => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{preview.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
          <p className="muted">Резервная копия имеет фиксированную структуру проекта. Восстановление создает отдельный проект и ничего не перезаписывает.</p>
        </div>
      )}
      {error && <div className="note warning" role="alert">{error}</div>}
      {file && <button type="button" className="primary" disabled={busy} onClick={restore}>{busy ? 'Восстановление…' : 'Восстановить'}</button>}
    </div>
  )
}

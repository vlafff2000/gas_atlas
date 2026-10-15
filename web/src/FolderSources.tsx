import { useState } from 'react'
import { folderApi, FolderEdit, FolderFile, FolderLoad, FolderLoadResult, FolderScan } from './api_folder'
import { openFilePicker } from './FilePicker'
import type { Project } from './api'

const KINDS = ['production', 'pressure', 'gdi', 'water'] as const
const KIND_LABEL: Record<string, string> = { production: 'Расходы', pressure: 'Давления', gdi: 'ГДИ', water: 'Вода' }
const LOAD_LABEL: Record<FolderLoad, string> = { loaded: 'загружен', changed: 'изменился, нужна загрузка', not_loaded: 'не загружен' }
const RESULT_LABEL: Record<FolderLoadResult['status'], string> = { loaded: 'Загружено', attention: 'Нужно внимание', error: 'Ошибка' }

function kb(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

/** Раздел «Источники»: папка проекта, роли файлов, статус загрузки в проект и кнопка загрузки через общий импорт. */
export function FolderSources({ project }: { project: Project | null }) {
  const [folder, setFolder] = useState('')
  const [scan, setScan] = useState<FolderScan | null>(null)
  const [edits, setEdits] = useState<Record<string, FolderEdit>>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [results, setResults] = useState<FolderLoadResult[]>([])
  const [warning, setWarning] = useState('')

  const run = async (work: () => Promise<FolderScan>, done: string) => {
    setBusy(true); setError(''); setMessage('')
    try {
      const next = await work()
      setScan(next); setFolder(next.folder); setEdits({}); setMessage(done); setResults([]); setWarning('')
    } catch (e) {
      setScan(null); setEdits({})          // старый список не должен выглядеть как открытая папка
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const pick = async () => {
    let chosen: string | null = null
    try {
      chosen = await openFilePicker({ mode: 'folder', start: folder || undefined, title: 'Папка проекта' })
    } catch (e) {
      setError((e as Error).message)
      return
    }
    if (chosen) await run(() => folderApi.scan(chosen!, project?.id), 'Папка прочитана.')
  }

  const current = (f: FolderFile) => ({
    role: f.role,
    normalized: f.normalized,
    ...edits[f.name],
  })

  const change = (f: FolderFile, patch: FolderEdit) => setEdits(prev => ({ ...prev, [f.name]: { ...prev[f.name], ...patch } }))

  const save = () => run(() => folderApi.saveManifest(scan!.folder, edits, project?.id), 'Роли сохранены в папке проекта.')

  // Грузим файлы с ролью, которые ещё не загружены или изменились; файлы без роли пропускаем.
  // Берём сохранённые роли: сервер при загрузке роли не читает. Несохранённые правки блокируют кнопку.
  const pending = scan?.files.filter(f => f.role && (f.load === 'not_loaded' || f.load === 'changed')).map(f => f.name) ?? []
  const unknownLoad = !!project && !!scan && scan.files.some(f => f.role && f.load === null)

  const loadPending = async () => {
    if (!project || !scan || dirty) return
    setBusy(true); setError(''); setMessage('')
    try {
      const reply = await folderApi.load(project.id, scan.folder, pending)
      setScan(reply.folder); setResults(reply.results); setWarning(reply.warning)
      setMessage(`Загрузка выполнена: ${reply.results.filter(r => r.status === 'loaded').length} из ${reply.results.length}.`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const counts = (kind: string) => scan?.files.filter(f => current(f).role === kind).length ?? 0
  const dirty = Object.keys(edits).length > 0

  return (
    <section className="folder-sources" aria-label="Источники данных">
      <h2>Источники</h2>
      <p className="lede">Папка с файлами проекта: какой файл чем является. Здесь только роли файлов: роли и признак нормированной базы сохраняются в папке рядом с данными.</p>

      <div className="folder-row">
        <input
          type="text"
          value={folder}
          placeholder="Путь к папке"
          onChange={e => setFolder(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && folder.trim()) void run(() => folderApi.scan(folder.trim(), project?.id), 'Папка прочитана.') }}
        />
        <button type="button" onClick={pick} disabled={busy}>Выбрать папку</button>
        <button type="button" onClick={() => run(() => folderApi.scan(folder.trim(), project?.id), 'Папка прочитана.')} disabled={busy || !folder.trim()}>Показать файлы</button>
      </div>

      {error && <div className="note warning">{error}</div>}
      {scan?.warning && <div className="note">{scan.warning}</div>}
      {message && <div className="note">{message}</div>}

      {scan && scan.files.length > 0 && (
        <>
          <ul className="folder-checklist" aria-label="Что назначено по ролям">
            {KINDS.map(kind => (
              <li key={kind}>
                <strong>{KIND_LABEL[kind]}:</strong> {counts(kind) ? `${counts(kind)} файл(ов)` : 'нет файлов'}
              </li>
            ))}
          </ul>

          {project && (
            <div className="folder-row">
              <button type="button" onClick={loadPending} disabled={busy || dirty || pending.length === 0}>
                Загрузить новые и изменённые ({pending.length})
              </button>
              <span className="muted">Грузятся только файлы с ролью. Загрузка идёт через общий импорт проекта «{project.name}».</span>
            </div>
          )}
          {!project && <div className="note">Выберите проект, чтобы видеть, что загружено, и загружать файлы.</div>}
          {unknownLoad && <div className="note">Статус загрузки не показан для выбранного проекта: нажмите «Показать файлы» ещё раз.</div>}
          {dirty && <div className="note">Сначала сохраните роли: загрузка идёт по сохранённым ролям.</div>}
          {warning && <div className="note warning">{warning}</div>}
          {results.length > 0 && (
            <ul className="folder-results">
              {results.map(r => (
                <li key={r.name}><strong>{r.name}:</strong> {RESULT_LABEL[r.status]}. {r.message}</li>
              ))}
            </ul>
          )}

          <table className="folder-table">
            <thead>
              <tr><th>Файл</th><th>Размер</th><th>Роль</th><th>Нормирована</th><th>Загрузка</th><th>Результат Базы ПХГ и проверка</th></tr>
            </thead>
            <tbody>
              {scan.files.map(f => {
                const cur = current(f)
                return (
                  <tr key={f.name}>
                    <td>{f.name}<div className="muted">{f.modified}</div></td>
                    <td>{kb(f.size)}</td>
                    <td>
                      <select value={cur.role ?? ''} onChange={e => change(f, { role: e.target.value || null })} aria-label={`Роль файла ${f.name}`}>
                        <option value="">не назначено</option>
                        {scan.roles.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                      </select>
                      {f.role_source && !edits[f.name]?.role && <div className="muted">{f.role_source === 'manifest' ? 'из манифеста' : 'по имени'}</div>}
                    </td>
                    <td>
                      {cur.role === 'production'
                        ? <input type="checkbox" checked={cur.normalized} onChange={e => change(f, { normalized: e.target.checked })} aria-label={`Нормирована ${f.name}`} />
                        : <span className="muted">—</span>}
                    </td>
                    <td>
                      {f.load ? LOAD_LABEL[f.load] : <span className="muted">—</span>}
                    </td>
                    <td>
                      {f.known && <div>{f.known}</div>}
                      {f.qc && (f.qc.error
                        ? <div className="muted">{f.qc.error}</div>
                        : <div>Проверка{f.qc.summary ? `: ${f.qc.summary}` : ''} <span className="muted">({f.qc.file})</span></div>)}
                      {!f.known && !f.qc && <span className="muted">—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          <div className="folder-row">
            <button type="button" onClick={save} disabled={busy || !dirty}>Сохранить роли</button>
            {dirty && <span className="muted">Есть несохранённые изменения</span>}
          </div>
        </>
      )}
    </section>
  )
}

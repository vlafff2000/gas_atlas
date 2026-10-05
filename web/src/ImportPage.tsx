// Раздел «Импорт данных»: таблицы (простой и подробный режим) и данные давлений для кроссплота.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Project } from './api'
import {
  importApi, type Applied, type Book, type CheckFile, type FileInfo, type FileOptions, type ImportOptions, type Pending,
  type GghInspect, type PressureChoice, type PressureDemo, type PressureInspect, type SheetChoice, type SimpleInspect, type Spec, type Upload,
} from './api_import'
import { projectsApi } from './api_projects'
import { SheetEditor } from './SheetEditor'
import { TableView } from './TableView'
import './import.css'

const ACCEPT = '.xlsx,.xls,.xlsm,.ods,.csv,.tsv,.txt,.dat'
const ENCODINGS = [['auto', 'Автоопределение'], ['utf-8-sig', 'utf-8-sig'], ['cp1251', 'cp1251'], ['utf-16', 'utf-16'],
  ['utf-16-le', 'utf-16-le'], ['utf-16-be', 'utf-16-be']]
const DELIMITERS = [['auto', 'Автоопределение'], ['\t', 'Табуляция'], [',', 'Запятая'], [';', 'Точка с запятой'],
  ['|', 'Вертикальная черта'], ['whitespace', 'Пробелы']]
const AUTO: FileOptions = { encoding: 'auto', delimiter: 'auto' }
const sep = '\u0000'

interface Message { text: string; ok: boolean; undo?: string }

/** Итог загрузки; после сохранения — кнопка «Откатить этот импорт» (данные возвращаются из копии, сделанной перед ним). */
function ImportNote({ message, project, onProject, onMessage }:
  { message: Message | null; project: Project; onProject: (p: Project) => void; onMessage: (m: Message | null) => void }) {
  const [busy, setBusy] = useState(false)
  if (!message) return null
  const undo = async () => {
    if (!message.undo) return
    setBusy(true)
    try {
      onProject(await projectsApi.rollback(project.id, message.undo, project.revision))
      onMessage({ text: 'Импорт отменён: данные проекта возвращены к состоянию до загрузки.', ok: true })
    } catch (e) { onMessage({ text: (e as Error).message, ok: false }) }
    setBusy(false)
  }
  return (
    <div className={'note ' + (message.ok ? 'info' : 'warning')} role="status">
      {message.text}
      {message.undo && <> <button type="button" className="quiet small" disabled={busy} onClick={undo}>Откатить этот импорт</button></>}
    </div>
  )
}

const DATASETS: Record<string, string> = { production: 'Эксплуатация', gdi: 'ГДИ', response: 'Реагирование' }

/** Проверка загруженных значений до сохранения: что выглядит сомнительно. Ничего не исключается само. */
function QualityReport({ quality, onDownload }: { quality: Pending['quality']; onDownload: (format: 'xlsx' | 'csv') => Promise<void> }) {
  if (!quality || (quality.errors + quality.attention === 0)) {
    return <div className="note info">Проверка данных: сомнительных значений не найдено.</div>
  }
  return (
    <>
      <div className={'note ' + (quality.errors ? 'warning' : 'info')}>
        Проверка данных: ошибок {quality.errors}, требуют внимания {quality.attention}.
        {' '}{quality.by_check.slice(0, 6).map(c => `${DATASETS[c.dataset] ?? c.dataset} — ${c.check.toLowerCase()}: ${c.count}`).join('; ')}.
        {' '}Загрузку это не останавливает: после сохранения находки можно разобрать и исключить в разделе «Проверка данных».
      </div>
      {quality.table && <TableView table={{ ...quality.table, collapsed: true }} onDownload={onDownload} />}
    </>
  )
}

interface Props {
  project: Project | null
  onProject: (p: Project) => void
  onCreated: (id: string) => Promise<void>
  /** Открыть сразу подраздел «Данные давлений» (адрес `#/@import/pressure`, ссылка со страницы кроссплота). */
  pressure?: boolean
}

export function ImportPage({ project, onProject, onCreated, pressure }: Props) {
  const [options, setOptions] = useState<ImportOptions | null>(null)
  const [tab, setTab] = useState<'tables' | 'pressure' | 'ggh'>(pressure ? 'pressure' : 'tables')
  const [failure, setFailure] = useState('')
  useEffect(() => { importApi.options().then(setOptions).catch(e => setFailure((e as Error).message)) }, [])

  return (
    <>
      <header className="module-title">
        <div>
          <h1>Импорт данных</h1>
          <p className="lede">Простой режим: перетащите все файлы сразу. Подробный: настройка шапки и колонок каждого листа.
            Данные давлений для кроссплота и газогидрохимия (ГГХ) — отдельные подразделы.
            Какие колонки и форматы нужны — в <a href={tab === 'pressure' ? '#/@help/pressure' : '#/@help'}>справке по форматам данных</a>.</p>
        </div>
      </header>
      {failure && <div className="note warning">{failure}</div>}
      <NewProject project={project} onCreated={onCreated} />
      {project && options && (
        <>
          <div className="tabs" role="tablist">
            <button type="button" role="tab" aria-selected={tab === 'tables'} onClick={() => setTab('tables')}>Таблицы исследований и эксплуатации</button>
            <button type="button" role="tab" aria-selected={tab === 'pressure'} onClick={() => setTab('pressure')}>Данные давлений (кроссплот)</button>
            <button type="button" role="tab" aria-selected={tab === 'ggh'} onClick={() => setTab('ggh')}>ГГХ (газогидрохимия)</button>
          </div>
          {project.demo && <div className="note warning">Это демонстрационный проект. Для рабочих файлов создайте отдельный проект.</div>}
          {tab === 'tables'
            ? <TablesImport key={project.id} project={project} options={options} onProject={onProject} />
            : tab === 'ggh'
              ? <GghImport key={project.id} project={project} onProject={onProject} />
              : <PressureImport key={project.id} project={project} options={options} onProject={onProject} />}
        </>
      )}
    </>
  )
}

function NewProject({ project, onCreated }: { project: Project | null; onCreated: (id: string) => Promise<void> }) {
  const [open, setOpen] = useState(!project)
  const [name, setName] = useState('')
  const [failure, setFailure] = useState('')
  useEffect(() => { if (!project) setOpen(true) }, [project])
  const create = async () => {
    if (!name.trim()) { setFailure('Введите название объекта'); return }
    try {
      const { id } = await importApi.createProject(name.trim())
      setName(''); setFailure(''); setOpen(false)
      await onCreated(id)
    } catch (e) { setFailure((e as Error).message) }
  }
  if (!open) {
    return (
      <div className="toolbar">
        <span className="muted">Загрузка в проект «{project?.name}».</span>
        <button type="button" className="quiet" onClick={() => setOpen(true)}>Новый проект</button>
      </div>
    )
  }
  return (
    <form className="new-project" onSubmit={e => { e.preventDefault(); create() }}>
      <strong>{project ? 'Новый проект' : 'Сначала создайте проект'}</strong>
      <label className="field">Название объекта
        <input value={name} onChange={e => setName(e.target.value)} autoFocus={!project} />
      </label>
      <button type="submit" className="primary">Создать</button>
      {project && <button type="button" className="quiet" onClick={() => setOpen(false)}>Отмена</button>}
      {failure && <div className="note warning">{failure}</div>}
    </form>
  )
}

/** Файлы: выбор, перетаскивание, вставка из буфера. */
function useUploads() {
  const [files, setFiles] = useState<Upload[]>([])
  const [busy, setBusy] = useState('')
  const [failure, setFailure] = useState('')
  const add = useCallback(async (list: { blob: Blob; name: string }[]) => {
    setFailure('')
    for (const [i, f] of list.entries()) {
      setBusy(`Чтение: ${f.name} (${i + 1} из ${list.length})`)
      try {
        const up = await importApi.upload(f.blob, f.name)
        setFiles(old => [...old, up])
      } catch (e) { setFailure(f.name + ': ' + (e as Error).message) }
    }
    setBusy('')
  }, [])
  const remove = (token: string) => setFiles(old => old.filter(f => f.token !== token))
  return { files, add, remove, clear: () => setFiles([]), busy, failure }
}

function FilePicker({ uploads, paste, help }: { uploads: ReturnType<typeof useUploads>; paste?: boolean; help: string }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [text, setText] = useState('')
  const pick = (list: FileList | null) => { if (list?.length) uploads.add([...list].map(f => ({ blob: f, name: f.name }))) }
  return (
    <div className="file-picker">
      <div className={'drop' + (over ? ' over' : '')}
           onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
           onDrop={e => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files) }}>
        <span>{help}</span>
        <button type="button" className="quiet" onClick={() => input.current?.click()}>Выбрать файлы</button>
        <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={e => { pick(e.target.files); e.target.value = '' }} />
      </div>
      {paste && (
        <details>
          <summary>Вставить таблицу из буфера</summary>
          <textarea rows={6} value={text} placeholder="Таблица с заголовками" onChange={e => setText(e.target.value)} />
          <button type="button" className="quiet" disabled={!text.trim()} onClick={() => {
            uploads.add([{ blob: new Blob([text], { type: 'text/plain' }), name: 'Вставленная_таблица.txt' }]); setText('')
          }}>Добавить</button>
        </details>
      )}
      {uploads.busy && <span className="pulse">{uploads.busy}</span>}
      {uploads.failure && <div className="note warning">{uploads.failure}</div>}
      {uploads.files.length > 0 && (
        <ul className="file-list">
          {uploads.files.map(f => (
            <li key={f.token}>
              <span>{f.name}</span><span className="muted">{f.format?.toUpperCase()} · {(f.bytes / 1024).toFixed(0)} КБ</span>
              {f.error && <span className="bad">{f.error}</span>}
              <button type="button" className="link" aria-label={'Убрать ' + f.name} onClick={() => uploads.remove(f.token)}>убрать</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function TextOptions({ name, value, onChange }: { name: string; value: FileOptions; onChange: (v: FileOptions) => void }) {
  return (
    <div className="form-row">
      <label className="field">Кодировка · {name}
        <select value={value.encoding} onChange={e => onChange({ ...value, encoding: e.target.value })}>
          {ENCODINGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      <label className="field">Разделитель · {name}
        <select value={value.delimiter} onChange={e => onChange({ ...value, delimiter: e.target.value })}>
          {DELIMITERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
    </div>
  )
}

function Metrics({ items }: { items: [string, number][] }) {
  return <div className="metrics">{items.map(([l, v]) => <div key={l}><span>{l}</span><strong>{v}</strong></div>)}</div>
}

// ---------------------------------------------------------------- таблицы
type Detailed = Record<string, Record<string, { spec: Spec | null; valid: boolean }>>
type Books = Record<string, Book & { duplicate: string }>

function TablesImport({ project, options, onProject }: { project: Project; options: ImportOptions; onProject: (p: Project) => void }) {
  const uploads = useUploads()
  const [view, setView] = useState<'simple' | 'detailed'>('simple')
  const [mode, setMode] = useState('auto')
  const [kind, setKind] = useState('withdrawal')
  const [punit, setPunit] = useState('м³/сут')
  const [gunit, setGunit] = useState('тыс. м³/сут')
  const [pressureUnit, setPressureUnit] = useState('кгс/см²')
  const [fileOpts, setFileOpts] = useState<Record<string, FileOptions>>({})
  const [choices, setChoices] = useState<Record<string, Record<string, SheetChoice>>>({})
  const [simple, setSimple] = useState<SimpleInspect | null>(null)
  const [infos, setInfos] = useState<FileInfo[] | null>(null)
  const [detailed, setDetailed] = useState<Detailed>({})
  const [books, setBooks] = useState<Books>({})
  const [fine, setFine] = useState('')
  const [pending, setPending] = useState<Pending | null>(null)
  const [policy, setPolicy] = useState('new')
  const [accept, setAccept] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<Message | null>(null)
  const files = uploads.files
  const opts = (token: string) => fileOpts[token] ?? AUTO

  // Любое изменение входа делает прежнюю проверку недействительной (как подпись в 5.8).
  useEffect(() => { setPending(null); setAccept(false) }, [files, view, mode, kind, punit, gunit, pressureUnit, fileOpts, choices, detailed, books])

  useEffect(() => {
    if (!files.length) { setSimple(null); setInfos(null); return }
    const ctrl = new AbortController()
    const list = files.map(f => ({ token: f.token, ...opts(f.token), choices: choices[f.token] ?? {} }))
    const req = view === 'simple'
      ? importApi.inspectSimple({ mode, files: list }, ctrl.signal).then(setSimple)
      : importApi.inspectDetailed({ mode, files: list }, ctrl.signal).then(r => {
        setInfos(r.files)
        setBooks(old => {
          const next: Books = {}
          for (const f of r.files) if (f.book) next[f.token] = old[f.token] ?? { ...f.book, duplicate: 'first' }
          return next
        })
      })
    req.catch(e => { if ((e as Error).name !== 'AbortError') setMessage({ text: (e as Error).message, ok: false }) })
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, view, mode, fileOpts, choices])

  const choose = (token: string, sheet: string, change: SheetChoice) =>
    setChoices(old => ({ ...old, [token]: { ...(old[token] ?? {}), [sheet]: { ...(old[token]?.[sheet] ?? {}), ...change } } }))
  const setSpec = useCallback((token: string, sheet: string) => (spec: Spec | null, valid: boolean) =>
    setDetailed(old => ({ ...old, [token]: { ...(old[token] ?? {}), [sheet]: { spec, valid } } })), [])

  const detailedBlocked = view === 'detailed' && (
    (infos ?? []).some(f => f.error) ||
    Object.values(detailed).some(sheets => Object.values(sheets).some(s => s.spec?.enabled && !s.valid)))
  const blocked = !files.length || (view === 'simple' ? !simple || simple.blocked : detailedBlocked || !infos)

  const body = () => ({
    view, mode, kind, production_unit: punit, gdi_unit: gunit, pressure_unit: pressureUnit,
    files: files.map((f): CheckFile => {
      const base = { token: f.token, ...opts(f.token) }
      if (view === 'simple') return { ...base, choices: choices[f.token] ?? {} }
      const specs = Object.fromEntries(Object.entries(detailed[f.token] ?? {}).filter(([, s]) => s.spec).map(([k, s]) => [k, s.spec!]))
      const book = books[f.token]
      if (book) {
        const wanted = [book.fact, ...book.models, ...book.fonds]
        return { ...base, pressure_book: { ...book, sheets: Object.fromEntries(wanted.filter(s => specs[s]).map(s => [s, specs[s]])) } }
      }
      return { ...base, sheets: specs }
    }),
  })

  const check = async () => {
    setBusy(true); setMessage(null)
    try { setPending(await importApi.check(project.id, body())) }
    catch (e) { setMessage({ text: (e as Error).message, ok: false }) }
    setBusy(false)
  }
  const apply = async () => {
    if (!pending) return
    setBusy(true)
    try {
      const r: Applied = await importApi.apply(project.id, pending.id, policy, accept)
      onProject(r.project)
      setPending(null); uploads.clear(); setChoices({}); setDetailed({}); setFileOpts({}); setFine('')
      setMessage({ text: r.message, ok: true, undo: r.undo?.snapshot })
    } catch (e) { setMessage({ text: (e as Error).message, ok: false }) }
    setBusy(false)
  }

  const fineRow = simple?.rows.find(r => r.token + sep + r.sheet === fine)
  const sheetTypes = options.sheet_types
  const rowTypes = options.sheet_types.filter(t => t.value !== 'auto')

  return (
    <section className="panel import">
      <div className="form-row">
        <div className="segmented" role="radiogroup" aria-label="Режим импорта"
             title="Простой: перетащите все файлы, программа определит тип каждого листа, проверка — в одной таблице. Подробный: ручная настройка шапки и колонок каждого листа.">
          {(['simple', 'detailed'] as const).map(v => (
            <label key={v}><input type="radio" checked={view === v} onChange={() => setView(v)} />{v === 'simple' ? 'Простой (автоматически)' : 'Подробный (по листам)'}</label>
          ))}
        </div>
      </div>
      <div className="form-row">
        <label className="field">Тип таблицы
          <select value={mode} onChange={e => setMode(e.target.value)}>{options.types.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}</select>
        </label>
        <label className="field">Динамика без названия
          <select value={kind} onChange={e => setKind(e.target.value)}><option value="withdrawal">Отбор</option><option value="injection">Закачка</option></select>
        </label>
        <label className="field">Расходы динамики
          <select value={punit} onChange={e => setPunit(e.target.value)}><option>м³/сут</option><option>тыс. м³/сут</option></select>
        </label>
        <label className="field">Q ГДИ без единиц
          <select value={gunit} onChange={e => setGunit(e.target.value)}><option>тыс. м³/сут</option><option>м³/сут</option></select>
        </label>
        <label className="field">Единицы давлений
          <select value={pressureUnit} onChange={e => setPressureUnit(e.target.value)}><option>кгс/см²</option><option>МПа</option></select>
        </label>
      </div>
      <p className="muted small">Давления внутри проекта: кгс/см². При выборе МПа пересчитываются давления, ΔP² и коэффициенты БД.
        Единицы Q в заголовке имеют приоритет; a и b БД считаются заданными для единиц Q исходного файла и пересчитываются вместе с ним.</p>

      <FilePicker uploads={uploads} paste help="Excel / ODS / CSV / TXT — можно сразу много файлов. Перетащите их сюда." />

      {view === 'simple' && simple && (
        <>
          {simple.problems.map(p => <div key={p} className="note warning">{p}</div>)}
          {simple.errors.map(p => <div key={p} className="note warning">{p}</div>)}
          {simple.rows.length > 0 && (
            <>
              <Metrics items={[['Файлов', simple.counts.files], ['Листов', simple.counts.sheets], ['Будет загружено', simple.counts.use], ['Не распознано', simple.counts.unknown]]} />
              <div className="table-scroll">
                <table className="grid">
                  <thead><tr><th>Исп.</th><th>Файл</th><th>Лист</th><th>Тип данных</th><th>Распознанные поля</th><th>Статус</th></tr></thead>
                  <tbody>
                    {simple.rows.map(r => (
                      <tr key={r.token + sep + r.sheet}>
                        <td><input type="checkbox" checked={r.use} disabled={r.book} aria-label="Использовать лист"
                                   onChange={e => choose(r.token, r.sheet, { use: e.target.checked })} /></td>
                        <td>{r.file}</td><td>{r.sheet}</td>
                        <td>{r.book ? 'Книга давлений' : (
                          <select value={r.module} title="Тип можно изменить: колонки будут сопоставлены заново"
                                  onChange={e => choose(r.token, r.sheet, { module: e.target.value, use: true })}>
                            {r.module === 'unknown' && <option value="unknown">не распознан</option>}
                            {rowTypes.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                          </select>)}</td>
                        <td>{r.fields}</td>
                        <td className={r.status === 'OK' ? 'ok' : r.status.startsWith('Не') || r.status.startsWith('Таблица') ? 'bad' : ''}>{r.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <label className="field">Нестандартный лист? Тонкая настройка шапки и колонок
                <select value={fine} onChange={e => setFine(e.target.value)}>
                  <option value="">— не нужна —</option>
                  {simple.rows.filter(r => !r.book).map(r => <option key={r.token + sep + r.sheet} value={r.token + sep + r.sheet}>{r.file} · {r.sheet}</option>)}
                </select>
              </label>
              {fineRow && (
                <div className="boxed">
                  {!fineRow.binary && <TextOptions name={fineRow.file} value={opts(fineRow.token)} onChange={v => setFileOpts({ ...fileOpts, [fineRow.token]: v })} />}
                  <SheetEditor key={fine} rememberable sheetTypes={sheetTypes} fields={options.fields} pressureFields={options.pressure_fields}
                               request={{ token: fineRow.token, sheet: fineRow.sheet, ...opts(fineRow.token), mode }}
                               onChange={(spec, valid) => {
                                 const current = choices[fineRow.token]?.[fineRow.sheet]?.spec
                                 const next = spec && spec.enabled && valid ? spec : undefined
                                 if (JSON.stringify(current) !== JSON.stringify(next)) {
                                   setChoices(old => {
                                     const sheet = { ...(old[fineRow.token]?.[fineRow.sheet] ?? {}) }
                                     if (next) sheet.spec = next; else delete sheet.spec
                                     return { ...old, [fineRow.token]: { ...(old[fineRow.token] ?? {}), [fineRow.sheet]: sheet } }
                                   })
                                 }
                               }} />
                  <button type="button" className="quiet" onClick={() => { choose(fineRow.token, fineRow.sheet, { spec: null }); setFine('') }}>
                    Вернуть автоматические настройки листа</button>
                </div>
              )}
            </>
          )}
        </>
      )}

      {view === 'detailed' && infos && (
        <>
          {infos.length > 6 && <div className="note info">Загружено много файлов. Для быстрой проверки в одной таблице переключитесь на «Простой» режим.</div>}
          {infos.map(f => (
            <div key={f.token} className="boxed">
              <h3>{f.name}</h3>
              {!f.binary && <TextOptions name={f.name} value={opts(f.token)} onChange={v => setFileOpts({ ...fileOpts, [f.token]: v })} />}
              {f.error ? <div className="note warning">{f.name}: {f.error}</div> : (
                <>
                  <p className="muted small">Формат по содержимому: {f.format?.toUpperCase()}</p>
                  {books[f.token] ? (
                    <BookEditor file={f} book={books[f.token]} options={options} fileOptions={opts(f.token)}
                                onBook={b => setBooks({ ...books, [f.token]: b })} onSpec={setSpec} />
                  ) : f.sheets.map(s => (
                    <SheetEditor key={s} sheetTypes={sheetTypes} fields={options.fields} pressureFields={options.pressure_fields}
                                 request={{ token: f.token, sheet: s, ...opts(f.token), mode }} onChange={setSpec(f.token, s)} />
                  ))}
                </>
              )}
            </div>
          ))}
        </>
      )}

      <Templates />

      <div className="toolbar">
        <button type="button" className="primary" disabled={blocked || busy} onClick={check}>Проверить файлы</button>
        {busy && <span className="pulse">Обработка…</span>}
      </div>
      <ImportNote message={message} project={project} onProject={onProject} onMessage={setMessage} />

      {pending && (
        <div className="check-result">
          <h2>Результат проверки</h2>
          {pending.counts.length
            ? <Metrics items={pending.counts.map(c => [c.label, c.rows] as [string, number])} />
            : <div className="note warning">Нет строк для загрузки.</div>}
          {pending.issues && (
            <>
              <div className="note warning">Отклоненных строк / файлов: {pending.rejected}. Предупреждений: {pending.warnings}. В журнале до 2000 замечаний на файл.</div>
              <TableView table={pending.issues} onDownload={format => importApi.table(project.id, pending.id, 'issues', format)} />
            </>
          )}
          <QualityReport quality={pending.quality} onDownload={format => importApi.table(project.id, pending.id, 'quality', format)} />
          {pending.previews.map(t => (
            <TableView key={t.id} table={{ ...t, collapsed: true }} onDownload={format => importApi.table(project.id, pending.id, t.id, format)} />
          ))}
          <fieldset className="choices">
            <legend>Повторы и обновление</legend>
            {pending.policies.map(p => (
              <label key={p.value}><input type="radio" checked={policy === p.value} onChange={() => setPolicy(p.value)} />{p.label}</label>
            ))}
          </fieldset>
          <p className="muted small">Повтор ГДИ заменяет исследование целиком по скважине, дате, методу и номеру исследования. Расходы за одну дату не суммируются.</p>
          {pending.rejected > 0 && (
            <label className="toggle"><input type="checkbox" checked={accept} onChange={e => setAccept(e.target.checked)} />
              <span>Загрузить корректные строки, исключив перечисленные ошибки</span></label>
          )}
          <button type="button" className="primary" disabled={busy || !pending.counts.length || (pending.rejected > 0 && !accept)} onClick={apply}>
            Применить загрузку</button>
        </div>
      )}
    </section>
  )
}

function BookEditor({ file, book, options, fileOptions, onBook, onSpec }: {
  file: FileInfo; book: Book & { duplicate: string }; options: ImportOptions; fileOptions: FileOptions
  onBook: (b: Book & { duplicate: string }) => void
  onSpec: (token: string, sheet: string) => (spec: Spec | null, valid: boolean) => void
}) {
  const others = file.sheets.filter(s => s !== book.fact)
  const toggle = (list: string[], s: string, on: boolean) => on ? [...list, s] : list.filter(x => x !== s)
  return (
    <>
      <div className="note info">Распознана книга кроссплота давлений: факт, модель и фонды.</div>
      <div className="form-row">
        <label className="field">Лист факта
          <select value={book.fact} onChange={e => onBook({ ...book, fact: e.target.value, models: book.models.filter(m => m !== e.target.value), fonds: book.fonds.filter(m => m !== e.target.value) })}>
            {file.sheets.map(s => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label className="field">Объект<input value={book.object} onChange={e => onBook({ ...book, object: e.target.value })} /></label>
        <label className="field">Повторы скважина / дата
          <select value={book.duplicate} onChange={e => onBook({ ...book, duplicate: e.target.value })}>
            {options.duplicates.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </label>
      </div>
      <div className="form-row">
        <fieldset className="choices"><legend>Листы моделей</legend>
          {others.map(s => <label key={s}><input type="checkbox" checked={book.models.includes(s)}
            onChange={e => onBook({ ...book, models: toggle(book.models, s, e.target.checked), fonds: book.fonds.filter(x => x !== s) })} />{s}</label>)}
        </fieldset>
        <fieldset className="choices"><legend>Листы фондов</legend>
          {others.filter(s => !book.models.includes(s)).map(s => <label key={s}><input type="checkbox" checked={book.fonds.includes(s)}
            onChange={e => onBook({ ...book, fonds: toggle(book.fonds, s, e.target.checked) })} />{s}</label>)}
        </fieldset>
      </div>
      {[book.fact, ...book.models, ...book.fonds].map(s => (
        <SheetEditor key={s + (book.fonds.includes(s) ? ':f' : '')} sheetTypes={options.sheet_types} fields={options.fields} pressureFields={options.pressure_fields}
                     request={{ token: file.token, sheet: s, ...fileOptions, pressure: true, fonds: book.fonds.includes(s) }}
                     onChange={onSpec(file.token, s)} />
      ))}
    </>
  )
}

function Templates() {
  const [list, setList] = useState<{ name: string; kind: string }[] | null>(null)
  const [failure, setFailure] = useState('')
  const download = (name: string) => importApi.template(name).catch(e => setFailure((e as Error).message))
  return (
    <details className="templates" onToggle={e => { if ((e.target as HTMLDetailsElement).open && !list) importApi.templates().then(setList).catch(err => setFailure((err as Error).message)) }}>
      <summary>Шаблоны и примеры</summary>
      {failure && <div className="note warning">{failure}</div>}
      <div className="links">
        {list?.filter(t => t.kind === 'template').map(t => <button key={t.name} type="button" className="quiet" onClick={() => download(t.name)}>Скачать {t.name}</button>)}
      </div>
      <p className="muted small">Давление объекта: ровно две колонки — Дата и Пластовое давление, кгс/см2. Выберите тип «Давление объекта» или автоопределение.</p>
      <p className="small"><strong>Динамика:</strong> Скважина, Дата, Расход. <strong>ГДИ:</strong> Скважина, Дата, Q, Рпл, Рзаб.
        <strong> Реагирование:</strong> Скважина, Дата, Горизонт, Уровень жидкости, Рпл привед.</p>
      <p className="muted small">Также поддерживаются матрицы расходов: даты в первом столбце, скважины в первой строке. Группы: Скважина, Группа, Подгруппа.</p>
      <div className="links">
        {list?.filter(t => t.kind === 'example').map(t => <button key={t.name} type="button" className="quiet" onClick={() => download(t.name)}>{t.name}</button>)}
      </div>
    </details>
  )
}

// ---------------------------------------------------------------- данные давлений
function PressureImport({ project, options, onProject }: { project: Project; options: ImportOptions; onProject: (p: Project) => void }) {
  const uploads = useUploads()
  const files = uploads.files
  const [duplicate, setDuplicate] = useState('first')
  const [fileOpts, setFileOpts] = useState<Record<string, FileOptions>>({})
  const [choices, setChoices] = useState<Record<string, Record<string, PressureChoice>>>({})
  const [overrides, setOverrides] = useState<Record<string, Record<string, Spec>>>({})
  const [result, setResult] = useState<PressureInspect | null>(null)
  const [running, setRunning] = useState(false)
  const [onlyIssues, setOnlyIssues] = useState(false)
  const [fine, setFine] = useState('')
  const [mode, setMode] = useState('add')
  const [message, setMessage] = useState<Message | null>(null)
  const opts = (token: string) => fileOpts[token] ?? AUTO

  useEffect(() => {
    if (!files.length) { setResult(null); return }
    const ctrl = new AbortController()
    setRunning(true)
    importApi.pressure(project.id, {
      files: files.map(f => ({ token: f.token, ...opts(f.token) })), choices, overrides, duplicate,
    }, ctrl.signal).then(r => { setResult(r); setRunning(false) })
      .catch(e => { if ((e as Error).name !== 'AbortError') { setMessage({ text: (e as Error).message, ok: false }); setRunning(false) } })
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, fileOpts, choices, overrides, duplicate, project.id])

  const choose = (token: string, sheet: string, change: PressureChoice) =>
    setChoices(old => ({ ...old, [token]: { ...(old[token] ?? {}), [sheet]: { ...(old[token]?.[sheet] ?? {}), ...change } } }))
  const rows = useMemo(() => result?.rows ?? [], [result])
  const shown = onlyIssues ? rows.filter(r => r['Статус'] !== 'OK' || (!r['Исп.'] && r['Роль'] !== 'Пропустить')) : rows
  const fineRow = rows.find(r => r.token + sep + r['Лист'] === fine)
  const fineRole = fineRow?.['Роль']

  const save = async () => {
    if (!result?.ready) return
    try {
      const r = await importApi.pressureApply(project.id, result.ready.id, mode)
      onProject(r.project)
      uploads.clear(); setChoices({}); setOverrides({}); setFileOpts({}); setFine(''); setResult(null)
      setMessage({ text: r.message, ok: true, undo: r.undo?.snapshot })
    } catch (e) { setMessage({ text: (e as Error).message, ok: false }) }
  }

  return (
    <section className="panel import">
      <div className="form-row">
        <label className="field">Повторные скважина / дата
          <select value={duplicate} onChange={e => setDuplicate(e.target.value)}>
            {options.duplicates.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </label>
      </div>
      <FilePicker uploads={uploads}
                  help="Перетащите сразу все файлы: книги Excel / ODS, CSV, TXT. Книга с листами «Факт», «Модель…», «Фонд» распознается автоматически; отдельные файлы — по словам «факт» и «модель» в названии." />
      {!files.length && <div className="note info">Выберите файлы. Программа сама определит факт, модели, фонды, шапку и структуру. Если данные уже есть в проекте, новые объекты добавятся к ним.</div>}
      <PressureDemos project={project} onProject={onProject} onMessage={setMessage}
                     onTry={list => { uploads.clear(); uploads.add(list) }} />
      <ImportNote message={message} project={project} onProject={onProject} onMessage={setMessage} />
      {result && (
        <>
          {result.bad.map(b => <div key={b} className="note warning">Файл не прочитан — {b}</div>)}
          {result.counts && <Metrics items={[['Файлов', result.counts.files], ['Листов', result.counts.sheets], ['Используется', result.counts.use], ['Объектов', result.counts.objects]]} />}
          {files.length > 8 && <p className="muted small">Загружено много файлов: листы отображаются в одной таблице. Фильтр по статусу — ниже.</p>}
          {rows.length > 12 && <label className="toggle"><input type="checkbox" checked={onlyIssues} onChange={e => setOnlyIssues(e.target.checked)} /><span>Показать только листы с замечаниями</span></label>}
          {rows.length > 0 && (
            <div className="table-scroll">
              <table className="grid">
                <thead><tr><th>Исп.</th><th>Файл</th><th>Лист</th><th>Роль</th><th>Объект</th><th>Сценарий</th><th>Статус</th><th>Значений</th><th>Скважин</th><th>Период</th><th>Структура</th></tr></thead>
                <tbody>
                  {shown.map(r => (
                    <tr key={r.token + sep + r['Лист']}>
                      <td><input type="checkbox" checked={r['Исп.']} aria-label="Использовать лист" onChange={e => choose(r.token, r['Лист'], { use: e.target.checked })} /></td>
                      <td>{r['Файл']}</td><td>{r['Лист']}</td>
                      <td><select value={r['Роль']} title="Факт — X, Модель — Y, Фонд — справочник «скважина → тип»"
                                  onChange={e => choose(r.token, r['Лист'], { role: e.target.value })}>
                        {options.roles.map(x => <option key={x}>{x}</option>)}</select>
                        {r['Роль'] === 'Факт' && (
                          <label className="toggle small" title="Один набор исторических данных для всех объектов загрузки, у которых нет своего факта: например, сравнить старую и новую модель с одними и теми же замерами">
                            <input type="checkbox" checked={r['Общая']} onChange={e => choose(r.token, r['Лист'], { shared: e.target.checked })} /><span>Общая история</span>
                          </label>)}</td>
                      <td><input key={r['Объект']} defaultValue={r['Объект']} title="Факт и модели с одинаковым названием объекта сопоставляются между собой" disabled={r['Общая']}
                                 onBlur={e => { const v = e.target.value.trim(); if (v && v !== r['Объект']) choose(r.token, r['Лист'], { object: v }) }} /></td>
                      <td><input key={r['Сценарий']} defaultValue={r['Сценарий']} title="Название модели на графиках" disabled={r['Роль'] !== 'Модель'}
                                 onBlur={e => { const v = e.target.value.trim(); if (v !== r['Сценарий']) choose(r.token, r['Лист'], { scenario: v }) }} /></td>
                      <td className={r['Статус'] === 'OK' ? 'ok' : r['Статус'].startsWith('Ошибка') ? 'bad' : ''}>{r['Статус']}</td>
                      <td>{r['Значений']}</td><td>{r['Скважин']}</td><td>{r['Период']}</td><td>{r['Структура']}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {rows.length > 0 && <p className="muted small">Роль, объект и сценарий можно править прямо в таблице. Фактические данные — по оси X, модельные — по оси Y.</p>}
          {rows.length > 0 && (
            <label className="field">Нестандартный лист? Тонкая настройка шапки и колонок
              <select value={fine} onChange={e => setFine(e.target.value)}>
                <option value="">— не нужна —</option>
                {rows.map(r => <option key={r.token + sep + r['Лист']} value={r.token + sep + r['Лист']}>{r['Файл']} · {r['Лист']}</option>)}
              </select>
            </label>
          )}
          {fineRow && (
            <div className="boxed">
              {!fineRow.binary && <TextOptions name={fineRow['Файл']} value={opts(fineRow.token)} onChange={v => setFileOpts({ ...fileOpts, [fineRow.token]: v })} />}
              <SheetEditor key={fine + fineRole} rememberable sheetTypes={options.sheet_types} fields={options.fields} pressureFields={options.pressure_fields}
                           request={{ token: fineRow.token, sheet: fineRow['Лист'], ...opts(fineRow.token), pressure: true, fonds: fineRole === 'Фонд' }}
                           onChange={(spec, valid) => {
                             const t = fineRow.token, s = fineRow['Лист']
                             const next = spec && spec.enabled && valid ? { ...spec, ...(fineRole === 'Фонд' ? { fonds: true } : {}) } : undefined
                             if (JSON.stringify(overrides[t]?.[s]) === JSON.stringify(next)) return
                             setOverrides(old => {
                               const sheets = { ...(old[t] ?? {}) }
                               if (next) sheets[s] = next; else delete sheets[s]
                               return { ...old, [t]: sheets }
                             })
                           }} />
              <button type="button" className="quiet" onClick={() => {
                setOverrides(old => { const sheets = { ...(old[fineRow.token] ?? {}) }; delete sheets[fineRow['Лист']]; return { ...old, [fineRow.token]: sheets } })
                setFine('')
              }}>Вернуть автоматические настройки листа</button>
            </div>
          )}
          {running && <span className="pulse">Сопоставление факта и моделей…</span>}
          {result.errors.map(e => <div key={e} className="note warning">{e}</div>)}
          {result.warnings.map(e => <div key={e} className="note info">{e}</div>)}
          {result.ready && (
            <div className="check-result">
              <div className="note info">{result.ready.text}</div>
              <TableView table={result.ready.summary} onDownload={f => importApi.table(project.id, result.ready!.id, 'summary', f)} />
              {result.ready.notes && <TableView table={{ ...result.ready.notes, collapsed: true }} onDownload={f => importApi.table(project.id, result.ready!.id, 'notes', f)} />}
              {result.ready.existing && (
                <>
                  <fieldset className="choices" title="«Добавить»: объекты с теми же названиями заменяются, остальные сохраняются.">
                    <legend>Что делать с уже загруженными данными давлений</legend>
                    {result.ready.modes.map(m => <label key={m.value}><input type="radio" checked={mode === m.value} onChange={() => setMode(m.value)} />{m.label}</label>)}
                  </fieldset>
                  {mode === 'scenarios' && <p className="muted small">Прежние сценарии объектов сохраняются; заменяются только сценарии с теми же названиями. Если у объекта нет факта в загрузке, берётся история из проекта.</p>}
                  {mode === 'add' && <p className="muted small">В проекте объектов: {result.ready.existing.objects}. Будут заменены: {result.ready.existing.replaced.join(', ') || 'нет совпадений'}.</p>}
                </>
              )}
              <button type="button" className="primary" disabled={running || result.errors.length > 0} onClick={save}>Сохранить в проект</button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function PressureDemos({ project, onProject, onMessage, onTry }: {
  project: Project; onProject: (p: Project) => void; onMessage: (m: { text: string; ok: boolean }) => void
  onTry: (list: { blob: Blob; name: string }[]) => void
}) {
  const [variants, setVariants] = useState<PressureDemo[]>([])
  const [chosen, setChosen] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    importApi.pressureDemos().then(v => { setVariants(v); setChosen(c => c || v[0]?.value || '') })
      .catch(e => onMessage({ text: (e as Error).message, ok: false }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const variant = variants.find(v => v.value === chosen)
  if (!variant) return null
  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    try { await work() } catch (e) { onMessage({ text: (e as Error).message, ok: false }) }
    setBusy(false)
  }
  const tryImport = () => run(async () => {
    const list = await Promise.all(variant.books.map(async name => ({ name, blob: await importApi.pressureDemoBook(variant.value, name) })))
    onTry(list)
  })
  const load = () => run(async () => {
    const r = await importApi.pressureDemoApply(project.id, variant.value)
    onProject(r.project); onMessage({ text: r.message, ok: true })
  })
  return (
    <details className="demo-variants">
      <summary>Демонстрационные варианты</summary>
      <div className="form-row">
        <label className="field">Вариант
          <select value={chosen} onChange={e => setChosen(e.target.value)}>
            {variants.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
          </select>
        </label>
      </div>
      <p className="muted small">{variant.description} Книги — обычные файлы Excel с листами «Факт», «Модель…», «Фонд»:
        их можно скачать и загрузить, как рабочие.</p>
      <div className="toolbar">
        {variant.books.map(name => (
          <button key={name} type="button" className="quiet" disabled={busy}
                  onClick={() => run(() => importApi.pressureDemoSave(variant.value, name))}>Скачать {name}</button>
        ))}
      </div>
      {project.demo ? (
        <div className="toolbar">
          <button type="button" className="quiet" disabled={busy} onClick={tryImport}
                  title="Книги варианта попадут в список файлов выше: проверка, сопоставление и сохранение — как с рабочими файлами">Открыть в импорте</button>
          <button type="button" className="primary" disabled={busy} onClick={load}
                  title="Данные давлений демонстрационного проекта заменяются выбранным вариантом">Загрузить в демонстрационный проект</button>
        </div>
      ) : (
        <p className="muted small">Загрузить вариант сразу в проект можно только в демонстрационном проекте: рабочие проекты не заполняются выдуманными замерами.</p>
      )}
    </details>
  )
}

// ---------------------------------------------------------------- ГГХ
/** Лист «Общий» книги отчёта по ГГХ: по строке на отбор пробы (скважина, дата, горизонт, газонасыщенность, состав газа). */
function GghImport({ project, onProject }: { project: Project; onProject: (p: Project) => void }) {
  const uploads = useUploads()
  const file = uploads.files[0]
  const [sheet, setSheet] = useState('')
  const [result, setResult] = useState<GghInspect | null>(null)
  const [running, setRunning] = useState(false)
  const [mode, setMode] = useState('merge')
  const [message, setMessage] = useState<Message | null>(null)

  useEffect(() => {
    if (!file) { setResult(null); return }
    const ctrl = new AbortController()
    setRunning(true)
    importApi.ggh(project.id, { token: file.token, ...(sheet ? { sheet } : {}) }, ctrl.signal)
      .then(r => { setResult(r); setRunning(false) })
      .catch(e => { if ((e as Error).name !== 'AbortError') { setMessage({ text: (e as Error).message, ok: false }); setRunning(false) } })
    return () => ctrl.abort()
  }, [file, sheet, project.id])

  const save = async () => {
    if (!result?.ready) return
    try {
      const r = await importApi.gghApply(project.id, result.ready.id, mode)
      onProject(r.project)
      uploads.clear(); setSheet(''); setResult(null)
      setMessage({ text: r.message, ok: true, undo: r.undo?.snapshot })
    } catch (e) { setMessage({ text: (e as Error).message, ok: false }) }
  }

  return (
    <section className="panel import">
      <FilePicker uploads={uploads}
                  help="Перетащите книгу Excel с данными ГГХ: нужен лист с колонками «№№ скв.», «Дата отбора», «Водоносный горизонт», «Газонасыщенность», «Сумма УВ», «Не», «Н2», «N2», «O2», «СО2» (лист «Общий» отчёта)." />
      {uploads.files.length > 1 && <div className="note info">Обрабатывается первый файл ({file.name}); остальные уберите или загрузите после сохранения.</div>}
      {!file && <div className="note info">Выберите файл. Лист с данными найдётся сам; числа с запятой читаются, строки без номера скважины или даты отклоняются и перечисляются ниже. После загрузки данные видны в разделе «ГГХ», а графики для отчёта — в разделе «Экспорт».</div>}
      <ImportNote message={message} project={project} onProject={onProject} onMessage={setMessage} />
      {running && <span className="pulse">Проверка листа…</span>}
      {result && (
        <>
          {result.sheets.length > 1 && (
            <label className="field">Лист
              <select value={result.sheet ?? ''} onChange={e => setSheet(e.target.value)}>
                {result.sheets.map(s => <option key={s}>{s}</option>)}
              </select>
            </label>
          )}
          {result.error && <div className="note warning">{result.error}</div>}
          {result.ready && (
            <div className="check-result">
              <div className="note info">{result.ready.text}</div>
              <TableView table={{ ...result.ready.summary, collapsed: true }} onDownload={f => importApi.table(project.id, result.ready!.id, 'summary', f)} />
              {result.ready.issues && <TableView table={result.ready.issues} onDownload={f => importApi.table(project.id, result.ready!.id, 'issues', f)} />}
              {result.ready.existing && (
                <fieldset className="choices">
                  <legend>Что делать с уже загруженными данными ГГХ</legend>
                  {result.ready.modes.map(m => <label key={m.value}><input type="radio" checked={mode === m.value} onChange={() => setMode(m.value)} />{m.label}</label>)}
                  <p className="muted small">В проекте: {result.ready.existing.rows} замеров, скважин {result.ready.existing.wells}.
                    Совпадают по номеру: {result.ready.existing.replaced.length}.</p>
                </fieldset>
              )}
              <button type="button" className="primary" disabled={running} onClick={save}>Сохранить в проект</button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

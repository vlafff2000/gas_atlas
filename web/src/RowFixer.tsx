// Правка проблемной строки из журнала проверки: окно строк листа, ввод значений, запись в исходный файл.
import { useEffect, useRef, useState } from 'react'
import { importApi, type CellEdit, type IssueSource, type RowsWindow } from './api_import'
import type { Project } from './api'

interface FilePicker { showSaveFilePicker?: (o: { suggestedName: string }) => Promise<{ createWritable: () => Promise<{ write: (b: Blob) => Promise<void>; close: () => Promise<void> }> }> }

const letters = (i: number) => { let s = ''; for (i += 1; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + (i - 1) % 26) + s; return s }

/** Записывает файл на диск: через окно «Сохранить как» (можно выбрать исходный файл и заменить его) или обычной загрузкой. */
async function writeFile(blob: Blob, name: string): Promise<string> {
  const picker = window as unknown as FilePicker
  if (picker.showSaveFilePicker) {
    try {
      const handle = await picker.showSaveFilePicker({ suggestedName: name })
      const out = await handle.createWritable()
      await out.write(blob); await out.close()
      return 'Файл записан в выбранное место.'
    } catch (e) {
      if ((e as Error).name === 'AbortError') return 'Запись файла на диск отменена: исправления остались только в загруженном файле.'
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return 'Исправленный файл скачан: замените им исходный.'
}

export function RowFixer({ project, source, onFixed, onClose }: {
  project: Project; source: IssueSource; onFixed: (message: string) => void; onClose: () => void
}) {
  const [center, setCenter] = useState(source.row)
  const [win, setWin] = useState<RowsWindow | null>(null)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const issue = useRef<HTMLTableRowElement>(null)

  useEffect(() => { setCenter(source.row); setEdits({}); setConfirm(false); setFailure(''); initial.current = {} }, [source])
  useEffect(() => {
    setWin(null)
    importApi.rows({ token: source.token, sheet: source.sheet, row: center, encoding: source.encoding, delimiter: source.delimiter })
      .then(setWin).catch(e => setFailure((e as Error).message))
  }, [source, center])
  useEffect(() => { issue.current?.scrollIntoView({ block: 'nearest' }) }, [win])

  const key = (row: number, col: number) => `${row}:${col}`
  const changed = Object.keys(edits).length
  // правки хранятся только для изменённых ячеек; прежние значения запоминаем при каждом показе окна
  const initial = useRef<Record<string, string>>({})
  const set = (row: number, col: number, value: string) => setEdits(old => {
    const next = { ...old }
    if (value === initial.current[key(row, col)]) delete next[key(row, col)]; else next[key(row, col)] = value
    return next
  })
  useEffect(() => { if (win) for (const r of win.rows) r.cells.forEach((v, c) => { initial.current[key(r.n, c)] = v }) }, [win])

  const save = async () => {
    setBusy(true); setFailure('')
    try {
      const list: CellEdit[] = Object.entries(edits).map(([k, value]) => {
        const [row, col] = k.split(':').map(Number)
        return { row, col, value }
      })
      const done = await importApi.fix(project.id, { token: source.token, sheet: source.sheet, edits: list, confirm,
        encoding: source.encoding, delimiter: source.delimiter })
      const written = await writeFile(await importApi.fileBlob(source.token), done.name)
      onFixed(`Исправлено ячеек: ${done.changed}. ${written} Копия оригинала: ${done.backup}. Файл проверен заново.`)
    } catch (e) { setFailure((e as Error).message) }
    setBusy(false)
  }

  return (
    <div className="boxed row-fixer">
      <div className="block-head">
        <h3>{source.file} · {source.sheet} · строка {source.row}</h3>
        <button type="button" className="quiet small" onClick={onClose}>Закрыть</button>
      </div>
      <div className="note warning reason">{source.reason}</div>
      {win && !win.editable && <div className="note warning">{win.note}</div>}
      {win && (
        <>
          <div className="toolbar">
            <button type="button" className="quiet small" disabled={win.first <= 1} onClick={() => setCenter(Math.max(1, win.first - 8))}>Выше</button>
            <button type="button" className="quiet small" disabled={win.last >= win.total} onClick={() => setCenter(Math.min(win.total, win.last + 8))}>Ниже</button>
            <button type="button" className="quiet small" disabled={center === source.row} onClick={() => setCenter(source.row)}>К проблемной строке</button>
            <span className="muted small">Строки {win.first}–{win.last} из {win.total}. Измените значения прямо в ячейках.</span>
          </div>
          <div className="sheet-preview">
            <table className="fix-grid">
              <thead><tr><th />{Array.from({ length: win.width }, (_, c) => <th key={c}>{letters(c)}</th>)}</tr></thead>
              <tbody>
                {win.rows.map(r => (
                  <tr key={r.n} className={r.n === source.row ? 'issue-row' : ''} ref={r.n === source.row ? issue : undefined}>
                    <th>{r.n}</th>
                    {r.cells.map((v, c) => {
                      const k = key(r.n, c), edited = k in edits
                      return (
                        <td key={c} className={edited ? 'changed' : ''}>
                          <input value={edited ? edits[k] : v} disabled={!win.editable} aria-label={`${letters(c)}${r.n}`}
                                 onChange={e => set(r.n, c, e.target.value)} />
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <label className="toggle">
        <input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} disabled={!changed} />
        <span>Подтверждаю: перезаписать исходный файл «{source.file}» с исправлениями. Копия оригинала сохранится в папке проекта.</span>
      </label>
      <div className="toolbar">
        <button type="button" className="primary" disabled={!changed || !confirm || busy} onClick={save}>
          {busy ? 'Сохраняю…' : `Записать исправления в файл${changed ? ` (${changed})` : ''}`}</button>
        {!changed && <span className="muted small">Измените хотя бы одну ячейку.</span>}
      </div>
      {failure && <div className="note warning">{failure}</div>}
    </div>
  )
}

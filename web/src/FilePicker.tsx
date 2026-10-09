// Проводник: окно выбора файла в браузере. Копия pxg_core/web-ui/FilePicker.tsx из репозитория all_scripts (держать в согласии).
// Использование: const path = await openFilePicker({ start: текущийПуть }); null — отмена.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

interface Item { name: string; dir: boolean; size: number; mtime: string; ext: string; locked: boolean }
interface Listing { path: string; parent: string; items: Item[]; total: number; truncated: boolean; error: string }
interface Place { name: string; path: string; kind: string }
interface Last { dir: string; recent: string[] }

export interface PickerOptions {
  start?: string
  /** 'file' — один файл, 'files' — несколько (вернётся по пути на строку), 'folder' — папка */
  mode?: 'file' | 'files' | 'folder'
  /** расширения, которые показываем (без «Все файлы») */
  filter?: string
  title?: string
}

const DEFAULT_FILTER = 'xlsx xlsm xls ods csv txt dat'

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  return (await r.json()) as T
}
const remember = (body: { dir?: string; file?: string }) =>
  fetch('/api/fs/last', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).catch(() => undefined)

const sep = (p: string) => (p.includes('\\') && !p.includes('/') ? '\\' : '/')
const join = (dir: string, name: string) => dir + (dir.endsWith('/') || dir.endsWith('\\') ? '' : sep(dir)) + name
const baseName = (p: string) => p.split(/[\\/]/).filter(Boolean).pop() || p

function crumbs(path: string): { name: string; path: string }[] {
  const s = sep(path)
  const parts = path.split(/[\\/]/)
  const out: { name: string; path: string }[] = []
  let acc = ''
  parts.forEach((part, i) => {
    if (i === 0 && part === '') { acc = ''; out.push({ name: '/', path: '/' }); return }
    if (!part) return
    acc = i === 0 ? part + (s === '\\' ? '\\' : '') : join(acc || '/', part)
    if (acc.length === 2 && acc[1] === ':') acc += '\\'
    out.push({ name: part, path: acc })
  })
  return out
}

const fmtSize = (n: number) => (n < 1024 ? n + ' Б' : n < 1048576 ? (n / 1024).toFixed(0) + ' КБ' : (n / 1048576).toFixed(1) + ' МБ')
const icon = (it: Item) => (it.dir ? '📁' : /^(xlsx|xlsm|xls|ods)$/.test(it.ext) ? '📗' : /^(csv|txt|dat)$/.test(it.ext) ? '📄' : '▫️')

function Picker({ opts, done }: { opts: PickerOptions; done: (p: string | null) => void }) {
  const folderMode = opts.mode === 'folder'
  const multi = opts.mode === 'files'
  const [marked, setMarked] = useState<string[]>([])
  const [places, setPlaces] = useState<Place[]>([])
  const [recent, setRecent] = useState<string[]>([])
  const [list, setList] = useState<Listing | null>(null)
  const [pathText, setPathText] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<'name' | 'mtime' | 'size'>('name')
  const [desc, setDesc] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [all, setAll] = useState(false)
  const [sel, setSel] = useState(-1)
  const [busy, setBusy] = useState(false)
  const dirRef = useRef('')
  const box = useRef<HTMLDivElement>(null)
  const filter = opts.filter ?? DEFAULT_FILTER

  const load = useCallback(async (path: string, over?: { q?: string; sort?: string; desc?: boolean; hidden?: boolean; all?: boolean }) => {
    const o = { q: query, sort, desc, hidden, all, ...over }
    const p = new URLSearchParams({ path, sort: o.sort, q: o.q, limit: '2000' })
    if (o.desc) p.set('desc', '1')
    if (o.hidden) p.set('hidden', '1')
    if (!o.all && !folderMode && filter) p.set('filter', filter)
    if (folderMode) p.set('kind', 'folder')
    setBusy(true)
    const r = await getJson<Listing>('/api/fs/list?' + p).catch(() => null)
    setBusy(false)
    if (!r) return
    setList(r)
    setSel(-1)
    if (r.path && !r.error) { dirRef.current = r.path; setPathText(r.path) }
  }, [query, sort, desc, hidden, all, filter, folderMode])

  useEffect(() => {
    let live = true
    ;(async () => {
      const [pl, last] = await Promise.all([
        getJson<{ places: Place[] }>('/api/fs/places').catch(() => ({ places: [] as Place[] })),
        getJson<Last>('/api/fs/last').catch(() => ({ dir: '', recent: [] as string[] })),
      ])
      if (!live) return
      setPlaces(pl.places); setRecent(last.recent)
      await load(opts.start || '')
    })()
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const close = (p: string | null) => {
    if (dirRef.current) void remember({ dir: dirRef.current })
    done(p)
  }
  const choose = (full: string) => { void remember({ dir: folderMode ? full : dirRef.current, file: folderMode ? '' : full }); done(full) }
  const open = (path: string) => { setQuery(''); void load(path, { q: '' }) }
  const items = useMemo(() => list?.items ?? [], [list])

  const activate = (it: Item) => {
    if (!list) return
    if (it.dir) { if (!it.locked) open(join(list.path, it.name)); return }
    if (!folderMode) { multi ? toggle(it.name) : choose(join(list.path, it.name)) }
  }
  const toggle = (name: string) => setMarked(m => (m.includes(name) ? m.filter(x => x !== name) : [...m, name]))
  const chooseMany = () => { if (!list) return; const files = marked.map(n => join(list.path, n)); void remember({ dir: list.path, file: files[files.length - 1] }); done(files.join('\n')) }
  const resort = (k: 'name' | 'mtime' | 'size') => {
    const d = sort === k ? !desc : false
    setSort(k); setDesc(d); void load(dirRef.current, { sort: k, desc: d })
  }
  const arrow = sort ? (desc ? ' ▾' : ' ▴') : ''

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { close(null); return }
    if ((e.target as HTMLElement).tagName === 'INPUT' && e.key !== 'ArrowDown') return
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(items.length - 1, s + 1)); box.current?.focus() }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(0, s - 1)) }
    else if (e.key === 'Backspace' && list?.parent) { e.preventDefault(); open(list.parent) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      if (multi && marked.length && !(sel >= 0 && items[sel]?.dir)) chooseMany()
      else if (sel >= 0 && items[sel]) activate(items[sel])
      else if (folderMode && list) choose(list.path)
    }
  }
  useEffect(() => {
    const row = box.current?.querySelector('.fp-row.sel') as HTMLElement | null
    row?.scrollIntoView({ block: 'nearest' })
  }, [sel])

  const cur = items[sel]
  const canPick = folderMode ? !!list && !list.error : multi ? marked.length > 0 : !!cur && !cur.dir

  return (
    <div className="fp-back" onMouseDown={e => { if (e.target === e.currentTarget) close(null) }} onKeyDown={onKey}>
      <div className="fp-win" role="dialog" aria-label={opts.title || 'Выбор файла'}>
        <div className="fp-head">
          <b>{opts.title || (folderMode ? 'Выбор папки' : multi ? 'Выбор файлов' : 'Выбор файла')}</b>
          <button className="fp-x" onClick={() => close(null)} aria-label="Закрыть">✕</button>
        </div>
        <div className="fp-bar">
          <button disabled={!list?.parent} onClick={() => list && open(list.parent)} title="Вверх (Backspace)">↑</button>
          <form onSubmit={e => { e.preventDefault(); void load(pathText.trim()) }} className="fp-path">
            <input value={pathText} onChange={e => setPathText(e.target.value)} placeholder="Вставьте путь и нажмите Enter" aria-label="Путь" />
          </form>
          <input className="fp-search" value={query} placeholder="Поиск по имени" aria-label="Поиск"
            onChange={e => { setQuery(e.target.value); void load(dirRef.current, { q: e.target.value }) }} />
        </div>
        <div className="fp-crumbs">
          {crumbs(list?.path || pathText).map((c, i) => (
            <button key={c.path + i} onClick={() => open(c.path)}>{c.name}</button>
          ))}
        </div>
        <div className="fp-main">
          <div className="fp-side">
            <div className="fp-cap">Места</div>
            {places.map(p => <button key={p.path} className={list?.path === p.path ? 'on' : ''} onClick={() => open(p.path)} title={p.path}>
              {p.kind === 'drive' ? '💽' : '📁'} {p.name}</button>)}
            {!folderMode && recent.length > 0 && <>
              <div className="fp-cap">Недавние файлы</div>
              {recent.map(f => <button key={f} onClick={() => choose(f)} title={f}>🕘 {baseName(f)}</button>)}
            </>}
          </div>
          <div className="fp-list" ref={box} tabIndex={0} role="listbox">
            <div className="fp-row fp-th">
              <span className="fp-n" onClick={() => resort('name')}>Имя{sort === 'name' ? arrow : ''}</span>
              <span className="fp-d" onClick={() => resort('mtime')}>Изменён{sort === 'mtime' ? arrow : ''}</span>
              <span className="fp-s" onClick={() => resort('size')}>Размер{sort === 'size' ? arrow : ''}</span>
            </div>
            {list?.error && <div className="fp-note bad">{list.error}</div>}
            {busy && !list?.error && <div className="fp-note">Читаю папку…</div>}
            {!busy && list && !list.error && items.length === 0 && (
              <div className="fp-note">{query ? 'Ничего не найдено.' : folderMode ? 'Вложенных папок нет.' : all ? 'Папка пуста.' : 'Подходящих файлов нет. Включите «Все файлы», если нужного не видно.'}</div>)}
            {items.map((it, i) => (
              <div key={it.name} role="option" aria-selected={i === sel}
                className={'fp-row' + (i === sel ? ' sel' : '') + (it.locked ? ' locked' : '')}
                onClick={() => { setSel(i); if (multi && !it.dir) toggle(it.name) }} onDoubleClick={() => (multi && !it.dir ? undefined : activate(it))}>
                <span className="fp-n" title={it.name}>{multi && !it.dir && <input type="checkbox" readOnly checked={marked.includes(it.name)} />} {icon(it)} {it.name}{it.locked ? ' (нет доступа)' : ''}</span>
                <span className="fp-d">{it.mtime}</span>
                <span className="fp-s">{it.dir ? '' : fmtSize(it.size)}</span>
              </div>))}
            {list?.truncated && <div className="fp-note">Папка читается медленно: показана только часть. Уточните поиск.</div>}
            {list && list.total > items.length && <div className="fp-note">Показано {items.length} из {list.total}.</div>}
          </div>
        </div>
        <div className="fp-foot">
          {!folderMode && <label><input type="checkbox" checked={all} onChange={e => { setAll(e.target.checked); void load(dirRef.current, { all: e.target.checked }) }} /> Все файлы</label>}
          <label><input type="checkbox" checked={hidden} onChange={e => { setHidden(e.target.checked); void load(dirRef.current, { hidden: e.target.checked }) }} /> Скрытые</label>
          <span className="fp-sp" />
          <span className="fp-pick">{folderMode ? (list?.path || '') : multi ? (marked.length ? 'Выбрано: ' + marked.length : '') : cur && !cur.dir ? cur.name : ''}</span>
          <button onClick={() => close(null)}>Отмена</button>
          <button className="primary" disabled={!canPick} onClick={() => (folderMode ? list && choose(list.path) : multi ? chooseMany() : cur && choose(join(list!.path, cur.name)))}>
            {folderMode ? 'Выбрать эту папку' : multi ? 'Добавить' : 'Открыть'}</button>
        </div>
      </div>
    </div>
  )
}

/** Открыть проводник; вернёт путь или null при отмене. */
export function openFilePicker(opts: PickerOptions = {}): Promise<string | null> {
  return new Promise(resolve => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    const done = (p: string | null) => { root.unmount(); host.remove(); resolve(p) }
    root.render(<Picker opts={opts} done={done} />)
  })
}

/** Выбрать файлы проводником и получить их как обычные File (содержимое читает локальный сервер). null — отмена. */
export async function pickLocalFiles(multiple: boolean, filter?: string): Promise<File[] | null> {
  const picked = await openFilePicker({ mode: multiple ? 'files' : 'file', filter })
  if (!picked) return null
  const out: File[] = []
  for (const path of picked.split('\n').filter(Boolean)) {
    const r = await fetch('/api/fs/file?path=' + encodeURIComponent(path))
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { error?: string }).error || 'Не удалось прочитать файл')
    out.push(new File([await r.blob()], baseName(path)))
  }
  return out
}

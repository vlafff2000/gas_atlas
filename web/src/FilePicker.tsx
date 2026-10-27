// Проводник: окно выбора файла в браузере (замена окна Tk). Общий для трёх приложений.
// Использование: const path = await openFilePicker({ start: текущийПуть }); null — отмена.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

interface Item { name: string; dir: boolean; size: number; mtime: string; ext: string; locked: boolean }
interface Listing { path: string; parent: string; items: Item[]; total: number; truncated: boolean; error: string; network?: boolean; cached?: boolean; lazy?: boolean; ms?: number }
interface Place { name: string; path: string; kind: string }
interface Fav { path: string; name: string; network?: boolean; n?: number }
interface Favs { favorites: Fav[]; frequent: Fav[] }
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
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const sizeRef = useRef<{ w: number; h: number } | null>(null)
  const [favs, setFavs] = useState<Favs>({ favorites: [], frequent: [] })
  const [favText, setFavText] = useState('')
  const [editFav, setEditFav] = useState<{ path: string; name: string } | null>(null)
  const anchor = useRef(-1)
  const dragged = useRef(false)
  const [band, setBand] = useState<{ x: number; y: number; w: number; h: number } | null>(null)
  const dirRef = useRef('')
  const box = useRef<HTMLDivElement>(null)
  const filter = opts.filter ?? DEFAULT_FILTER

  const reqId = useRef(0)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const load = useCallback(async (path: string, over?: { q?: string; sort?: string; desc?: boolean; hidden?: boolean; all?: boolean }, fresh = false, revalidate = false) => {
    const o = { q: query, sort, desc, hidden, all, ...over }
    const p = new URLSearchParams({ path, sort: o.sort, q: o.q, limit: '1000' })
    if (o.desc) p.set('desc', '1')
    if (o.hidden) p.set('hidden', '1')
    if (!o.all && !folderMode && filter) p.set('filter', filter)
    if (folderMode) p.set('kind', 'folder')
    if (fresh) p.set('fresh', '1')
    const id = ++reqId.current
    if (!fresh) setBusy(true)
    const t0 = performance.now()
    let t1 = t0, t2 = t0
    const r = await fetch('/api/fs/list?' + p).then(async resp => { t1 = performance.now(); const j = (await resp.json()) as Listing; t2 = performance.now(); return j }).catch(() => null)
    if (id !== reqId.current) return // пришёл более новый запрос
    setBusy(false)
    if (!r) return
    setList(r)
    // тайминги окна в журнал: запрос, разбор ответа, отрисовка (только для медленных и сетевых папок)
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const total = performance.now() - t0
      if (total > 300 || r.network || r.error) {
        void fetch('/api/fs/perf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
          path: r.path, fetch: Math.round(t1 - t0), parse: Math.round(t2 - t1), render: Math.round(performance.now() - t2), rows: r.items.length, cached: !!r.cached }) }).catch(() => undefined)
      }
    }))
    if (!fresh) setSel(-1)
    if (r.path && !r.error) { dirRef.current = r.path; setPathText(r.path) }
    // сеть: листинг пришёл из кэша — при переходе в папку обновляем его в фоне (при поиске, сортировке и фильтрах — нет:
    // иначе каждая буква в поиске перечитывала бы сетевую папку заново)
    if (r.cached && !r.error && revalidate) { void load(r.path, over, true); return }
    // без stat: размер и дату берём для видимых строк (первые 60), остальные — порциями, пока пользователь не ушёл в другую папку
    if (r.lazy && !r.error) {
      const names = r.items.map(i => i.name)
      for (let i = 0; i < names.length; i += i === 0 ? 60 : 100) {
        if (i > 0) await new Promise(res => setTimeout(res, 300))
        if (id !== reqId.current) return
        const chunk = names.slice(i, i + (i === 0 ? 60 : 100))
        const st = await getJson<{ stats: Record<string, { size: number; mtime: string; locked?: boolean; dir?: boolean }> }>('/api/fs/stat', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: r.path, names: chunk }) }).catch(() => null)
        if (!st || id !== reqId.current) return
        setList(l => l && l.path === r.path ? { ...l, lazy: false, items: l.items.map(it => st.stats[it.name] ? { ...it, ...st.stats[it.name], ext: (st.stats[it.name].dir ?? it.dir) ? '' : it.name.includes('.') ? it.name.split('.').pop()!.toLowerCase() : '' } : it).sort((a, b) => Number(b.dir) - Number(a.dir)) } : l)
      }
    }
  }, [query, sort, desc, hidden, all, filter, folderMode])

  const more = async () => {
    if (!list) return
    const p = new URLSearchParams({ path: list.path, sort, q: query, limit: '1000', offset: String(list.items.length) })
    if (desc) p.set('desc', '1')
    if (hidden) p.set('hidden', '1')
    if (!all && !folderMode && filter) p.set('filter', filter)
    if (folderMode) p.set('kind', 'folder')
    const r = await getJson<Listing>('/api/fs/list?' + p).catch(() => null)
    if (r && !r.error) setList(l => l && l.path === r.path ? { ...l, items: [...l.items, ...r.items], total: r.total } : l)
  }

  useEffect(() => {
    let live = true
    // папка открывается сразу, не дожидаясь мест, избранного и размера окна (сбор мест может быть медленным)
    void load(opts.start || '', undefined, false, true)
    getJson<{ places: Place[] }>('/api/fs/places').then(pl => { if (live) setPlaces(pl.places) }).catch(() => undefined)
    getJson<Last>('/api/fs/last').then(last => { if (live) setRecent(last.recent) }).catch(() => undefined)
    getJson<Favs>('/api/fs/favorites').then(f => { if (live && f.favorites) setFavs(f) }).catch(() => undefined)
    getJson<{ w?: number; h?: number }>('/api/fs/win').then(win => {
      if (live && win.w && win.h) { const v = { w: win.w, h: win.h }; sizeRef.current = v; setSize(v) }
    }).catch(() => undefined)
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const postFav = (url: string, body: object) =>
    getJson<Favs>(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(f => { if (f && f.favorites) setFavs(f) }).catch(() => undefined)
  const favAction = (action: string, path: string, extra: object = {}) => postFav('/api/fs/favorites', { action, path, ...extra })

  const close = (p: string | null) => {
    if (dirRef.current) void remember({ dir: dirRef.current })
    done(p)
  }
  const choose = (full: string) => { void remember({ dir: folderMode ? full : dirRef.current, file: folderMode ? '' : full }); done(full) }
  const open = (path: string) => { setQuery(''); void postFav('/api/fs/visit', { path }); void load(path, { q: '' }, false, true) }
  const items = useMemo(() => list?.items ?? [], [list])

  const activate = (it: Item) => {
    if (!list) return
    if (it.dir) { if (!it.locked) open(join(list.path, it.name)); return }
    if (!folderMode) { multi ? setMarked([it.name]) : choose(join(list.path, it.name)) }
  }
  const toggle = (name: string) => setMarked(m => (m.includes(name) ? m.filter(x => x !== name) : [...m, name]))
  // выбор строки: обычный клик — только она, Ctrl/⌘ — добавить или снять, Shift — диапазон от опорной строки
  const rowClick = (e: React.MouseEvent, i: number, it: Item) => {
    setSel(i)
    if (!multi || it.dir) return
    if (e.shiftKey && anchor.current >= 0) {
      const [a, b] = [Math.min(anchor.current, i), Math.max(anchor.current, i)]
      const range = items.slice(a, b + 1).filter(x => !x.dir).map(x => x.name)
      setMarked(m => (e.ctrlKey || e.metaKey ? Array.from(new Set([...m, ...range])) : range))
    } else if (e.ctrlKey || e.metaKey) { toggle(it.name); anchor.current = i }
    else { setMarked([it.name]); anchor.current = i }
  }
  const markAll = () => setMarked(items.filter(x => !x.dir).map(x => x.name))
  // выделение рамкой: тянем мышью по списку, строки под рамкой выбираются (с Ctrl/Shift — добавляются к выбранным)
  const bandStart = (e: React.PointerEvent) => {
    if (!multi || e.button !== 0 || (e.target as HTMLElement).closest('.fp-th, input, button')) return
    const el = box.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const x0 = e.clientX - r.left + el.scrollLeft, y0 = e.clientY - r.top + el.scrollTop
    const base = e.ctrlKey || e.metaKey || e.shiftKey ? marked : []
    let moved = false
    const move = (ev: PointerEvent) => {
      const x1 = ev.clientX - r.left + el.scrollLeft, y1 = ev.clientY - r.top + el.scrollTop
      if (!moved && Math.abs(x1 - x0) + Math.abs(y1 - y0) < 5) return
      moved = true; dragged.current = true
      const top = Math.min(y0, y1), bottom = Math.max(y0, y1)
      setBand({ x: Math.min(x0, x1), y: top, w: Math.abs(x1 - x0), h: bottom - top })
      const hit: string[] = []
      el.querySelectorAll<HTMLElement>('.fp-row[data-name]').forEach(row => {
        if (row.dataset.dir === '1') return
        const rt = row.offsetTop, rb = rt + row.offsetHeight
        if (rb >= top && rt <= bottom) hit.push(row.dataset.name as string)
      })
      setMarked(Array.from(new Set([...base, ...hit])))
    }
    const up = () => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up)
      setBand(null)
      if (moved) setTimeout(() => { dragged.current = false }, 0)
    }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
  }
  const chooseMany = () => { if (!list) return; const files = marked.map(n => join(list.path, n)); void remember({ dir: list.path, file: files[files.length - 1] }); done(files.join('\n')) }
  const resort = (k: 'name' | 'mtime' | 'size') => {
    const d = sort === k ? !desc : false
    setSort(k); setDesc(d); void load(dirRef.current, { sort: k, desc: d })
  }
  const arrow = sort ? (desc ? ' ▾' : ' ▴') : ''

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { close(null); return }
    if (multi && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a' && (e.target as HTMLElement).tagName !== 'INPUT') { e.preventDefault(); markAll(); return }
    if ((e.target as HTMLElement).tagName === 'INPUT' && e.key !== 'ArrowDown') return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const n = e.key === 'ArrowDown' ? Math.min(items.length - 1, sel + 1) : Math.max(0, sel - 1)
      setSel(n); box.current?.focus()
      if (multi && e.shiftKey && !items[n]?.dir) {
        if (anchor.current < 0) anchor.current = Math.max(sel, 0)
        const [a, b] = [Math.min(anchor.current, n), Math.max(anchor.current, n)]
        setMarked(items.slice(a, b + 1).filter(x => !x.dir).map(x => x.name))
      } else if (multi && !e.shiftKey && !e.ctrlKey && items[n] && !items[n].dir) { anchor.current = n; setMarked([items[n].name]) }
    }
    else if (multi && e.key === ' ' && items[sel] && !items[sel].dir) { e.preventDefault(); toggle(items[sel].name); anchor.current = sel }
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

  // растягивание окна за углы: окно по центру, поэтому сдвиг угла меняет размер вдвое
  const startResize = (sx: number, sy: number) => (e: React.PointerEvent) => {
    e.preventDefault()
    const win = (e.currentTarget as HTMLElement).parentElement as HTMLElement
    const w0 = win.offsetWidth, h0 = win.offsetHeight, x0 = e.clientX, y0 = e.clientY
    const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
    const move = (ev: PointerEvent) => {
      const v = { w: Math.round(clamp(w0 + sx * 2 * (ev.clientX - x0), 520, window.innerWidth - 16)),
                  h: Math.round(clamp(h0 + sy * 2 * (ev.clientY - y0), 340, window.innerHeight - 16)) }
      sizeRef.current = v; setSize(v)
    }
    const up = () => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up)
      if (sizeRef.current) void fetch('/api/fs/win', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sizeRef.current) }).catch(() => undefined)
    }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
  }

  const cur = items[sel]
  const canPick = folderMode ? !!list && !list.error : multi ? marked.length > 0 : !!cur && !cur.dir

  return (
    <div className="fp-back" onMouseDown={e => { if (e.target === e.currentTarget) close(null) }} onKeyDown={onKey}>
      <div className="fp-win" role="dialog" aria-label={opts.title || 'Выбор файла'}
        style={size ? { width: Math.min(size.w, window.innerWidth - 16), height: Math.min(size.h, window.innerHeight - 16) } : undefined}>
        <span className="fp-rs nw" onPointerDown={startResize(-1, -1)} />
        <span className="fp-rs ne" onPointerDown={startResize(1, -1)} />
        <span className="fp-rs sw" onPointerDown={startResize(-1, 1)} />
        <span className="fp-rs se" onPointerDown={startResize(1, 1)} />
        <div className="fp-head">
          <b>{opts.title || (folderMode ? 'Выбор папки' : multi ? 'Выбор файлов' : 'Выбор файла')}</b>
          <button className="fp-x" onClick={() => close(null)} aria-label="Закрыть">✕</button>
        </div>
        <div className="fp-bar">
          <button disabled={!list?.parent} onClick={() => list && open(list.parent)} title="Вверх (Backspace)">↑</button>
          <button onClick={() => void load(dirRef.current, undefined, true)} title="Обновить">↻</button>
          <form onSubmit={e => { e.preventDefault(); void postFav('/api/fs/visit', { path: pathText.trim() }); void load(pathText.trim(), undefined, false, true) }} className="fp-path">
            <input value={pathText} onChange={e => setPathText(e.target.value)} placeholder="Вставьте путь и нажмите Enter" aria-label="Путь" />
          </form>
          <input className="fp-search" value={query} placeholder="Поиск по имени" aria-label="Поиск"
            onChange={e => {
              const v = e.target.value; setQuery(v)
              if (searchTimer.current) clearTimeout(searchTimer.current)
              searchTimer.current = setTimeout(() => void load(dirRef.current, { q: v }), 200)
            }} />
        </div>
        <div className="fp-crumbs">
          {crumbs(list?.path || pathText).map((c, i) => (
            <button key={c.path + i} onClick={() => open(c.path)}>{c.name}</button>
          ))}
        </div>
        <div className="fp-main">
          <div className="fp-side">
            <div className="fp-cap">Места</div>
            {places.map(p => <button key={p.path} className={list?.path === p.path ? 'on' : ''} onClick={() => open(p.path)} title={p.name + '\n' + p.path}>
              <span className="fp-pn">{p.kind === 'drive' ? '💽' : p.kind === 'network' ? '🌐' : '📁'} {p.name}</span>
              {(p.kind === 'drive' || p.kind === 'network') && <span className="fp-pp">{p.path}</span>}</button>)}
            <div className="fp-cap">Избранное</div>
            {favs.favorites.map(f => editFav?.path === f.path ? (
              <form key={f.path} className="fp-favedit" onSubmit={e => { e.preventDefault(); void favAction('rename', f.path, { name: editFav.name }); setEditFav(null) }}>
                <input autoFocus value={editFav.name} onChange={e => setEditFav({ path: f.path, name: e.target.value })} onBlur={() => setEditFav(null)} />
              </form>
            ) : (
              <div key={f.path} className="fp-fav">
                <button className={list?.path === f.path ? 'on' : ''} onClick={() => open(f.path)} title={f.name + '\n' + f.path}>
                  <span className="fp-pn">{f.network ? '🌐' : '⭐'} {f.name}</span><span className="fp-pp">{f.path}</span></button>
                <span className="fp-fa">
                  <i onMouseDown={e => e.preventDefault()} onClick={() => setEditFav({ path: f.path, name: f.name })} title="Переименовать">✎</i>
                  <i onClick={() => void favAction('remove', f.path)} title="Убрать из избранного">✕</i>
                </span>
              </div>))}
            {favs.favorites.length === 0 && <div className="fp-note small">Пусто. Добавьте текущую папку или впишите путь (можно сетевой).</div>}
            <form className="fp-favadd" onSubmit={e => { e.preventDefault(); if (favText.trim()) { void favAction('add', favText.trim()); setFavText('') } }}>
              <input value={favText} onChange={e => setFavText(e.target.value)} placeholder="Путь в избранное" aria-label="Добавить путь в избранное" />
              <button type="submit" title="Добавить путь">＋</button>
            </form>
            <button disabled={!list?.path || list.error !== '' || favs.favorites.some(f => f.path === list.path)}
              onClick={() => list && void favAction('add', list.path)}>⭐ Добавить текущую папку</button>
            {favs.frequent.length > 0 && <>
              <div className="fp-cap">Часто посещаемые</div>
              {favs.frequent.map(f => (
                <div key={f.path} className="fp-fav">
                  <button onClick={() => open(f.path)} title={f.path + '\nзаходов: ' + f.n}><span className="fp-pn">{f.network ? '🌐' : '🔁'} {f.name}</span><span className="fp-pp">{f.path}</span></button>
                  <span className="fp-fa">
                    <i onClick={() => void favAction('add', f.path)} title="В избранное">⭐</i>
                    <i onClick={() => void favAction('hide', f.path)} title="Убрать из подсказок">✕</i>
                  </span>
                </div>))}
            </>}
            {!folderMode && recent.length > 0 && <>
              <div className="fp-cap">Недавние файлы</div>
              {recent.map(f => <button key={f} onClick={() => choose(f)} title={f}>🕘 {baseName(f)}</button>)}
            </>}
          </div>
          <div className="fp-list" ref={box} tabIndex={0} role="listbox" aria-multiselectable={multi} onPointerDown={bandStart}>
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
              <div key={it.name} role="option" aria-selected={multi ? marked.includes(it.name) : i === sel} data-name={it.name} data-dir={it.dir ? '1' : '0'}
                className={'fp-row' + (i === sel ? ' sel' : '') + (multi && marked.includes(it.name) ? ' mark' : '') + (it.locked ? ' locked' : '')}
                onClick={e => { if (dragged.current) return; rowClick(e, i, it) }}
                onDoubleClick={() => { if (multi && !it.dir) { setMarked([it.name]); if (list) { void remember({ dir: list.path, file: join(list.path, it.name) }); done(join(list.path, it.name)) } } else activate(it) }}>
                <span className="fp-n" title={it.name}>{multi && !it.dir && <input type="checkbox" checked={marked.includes(it.name)}
                  onChange={() => { toggle(it.name); anchor.current = i }} onClick={e => e.stopPropagation()} />} {icon(it)} {it.name}{it.locked ? ' (нет доступа)' : ''}</span>
                <span className="fp-d">{it.mtime}</span>
                <span className="fp-s">{it.dir ? '' : fmtSize(it.size)}</span>
              </div>))}
            {band && <div className="fp-band" style={{ left: band.x, top: band.y, width: band.w, height: band.h }} />}
            {list?.truncated && <div className="fp-note">Папка читается медленно: показана только часть. Уточните поиск или нажмите «Обновить».</div>}
            {list && list.total > items.length && <div className="fp-note">Показано {items.length} из {list.total}. <button onClick={() => void more()}>Показать ещё</button></div>}
          </div>
        </div>
        <div className="fp-foot">
          {!folderMode && <label><input type="checkbox" checked={all} onChange={e => { setAll(e.target.checked); void load(dirRef.current, { all: e.target.checked }) }} /> Все файлы</label>}
          <label><input type="checkbox" checked={hidden} onChange={e => { setHidden(e.target.checked); void load(dirRef.current, { hidden: e.target.checked }) }} /> Скрытые</label>
          {multi && <>
            <button onClick={markAll} title="Ctrl+A">Выделить всё</button>
            <button disabled={!marked.length} onClick={() => setMarked([])}>Снять</button>
          </>}
          <span className="fp-sp" />
          {!!list?.ms && list.ms > 500 && !list.error && <span className="fp-pick" title="Время чтения папки сервером">чтение {(list.ms / 1000).toFixed(1)} с</span>}
          <span className="fp-pick">{folderMode ? (list?.path || '') : multi ? (marked.length ? 'Выбрано: ' + marked.length : 'Shift, Ctrl, рамка мышью') : cur && !cur.dir ? cur.name : ''}</span>
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

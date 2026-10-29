import { useEffect, useRef, useState } from 'react'
import { builderApi, type LayoutItem } from './api'
import type { BuilderLayout } from './ChartBuilder'

// Библиотека макетов проекта и выгрузка текущего графика (этап 5). Сам расчёт и проверка макета — на стороне ядра.
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export function BuilderLibrary({ project, layout, onOpen }:
  { project: string; layout: BuilderLayout; onOpen: (layout: unknown) => BuilderLayout }) {
  const [items, setItems] = useState<LayoutItem[]>([])
  const [current, setCurrent] = useState('')                 // выбранный макет
  const [saved, setSaved] = useState<unknown>(null)          // что лежало в нём при открытии или сохранении
  const [name, setName] = useState('')
  const [mode, setMode] = useState<'' | 'new' | 'rename'>('')
  const [word, setWord] = useState({ title: '', caption: '', orientation: 'landscape', caption_mode: 'field' })
  const [message, setMessage] = useState<{ text: string; level: 'info' | 'warning' } | null>(null)
  const [missing, setMissing] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const item = items.find(i => i.id === current)
  const filled = layout.series.length > 0
  const dirty = !!item && !same(saved, layout)

  useEffect(() => { builderApi.list(project).then(setItems).catch(e => setMessage({ text: (e as Error).message, level: 'warning' })) }, [project])

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    try { await work() } catch (e) { setMissing([]); setMessage({ text: (e as Error).message, level: 'warning' }) } finally { setBusy(false) }
  }
  const info = (text: string) => setMessage({ text, level: 'info' })
  const show = (found: string[]) => { setMissing(found); if (found.length) setMessage(null) }

  const open = () => run(async () => {
    if (!item) return
    if (filled && !same(saved, layout) && !window.confirm('Текущий график не сохранён в макете и будет заменён. Открыть макет «' + item.name + '»?')) return
    const r = await builderApi.open(project, item.id)
    setSaved(onOpen(r.layout)); show(r.missing)
    info(r.missing.length ? '' : `Открыт макет «${r.name}».`)
  })
  const create = () => run(async () => {
    const r = await builderApi.save(project, name, layout)
    setItems(r.items); setCurrent(r.item.id); setSaved(layout); setMode(''); setName(''); show([]); info(`Макет «${r.item.name}» сохранён в проекте.`)
  })
  const overwrite = () => run(async () => {
    if (!item) return
    const r = await builderApi.update(project, item.id, { layout })
    setItems(r.items); setSaved(layout); info(`Макет «${item.name}» обновлён.`)
  })
  const rename = () => run(async () => {
    if (!item) return
    const r = await builderApi.update(project, item.id, { name })
    setItems(r.items); setMode(''); setName(''); info(`Макет переименован: «${r.item.name}».`)
  })
  const copy = () => run(async () => {
    if (!item) return
    const r = await builderApi.duplicate(project, item.id)
    setItems(r.items); setCurrent(r.item.id); setSaved(null); info(`Создана копия «${r.item.name}». Нажмите «Открыть», чтобы работать с ней.`)
  })
  const remove = () => run(async () => {
    if (!item || !window.confirm(`Удалить макет «${item.name}» из проекта? Это нельзя отменить. Текущий график на экране не изменится.`)) return
    const r = await builderApi.remove(project, item.id)
    setItems(r.items); setCurrent(''); setSaved(null); show([]); info(`Макет «${item.name}» удалён.`)
  })
  const importFile = (f: File | undefined) => run(async () => {
    if (!f) return
    if (filled && !window.confirm('Текущий график будет заменён макетом из файла (в проекте он сохранится под своим именем). Продолжить?')) return
    const r = await builderApi.importFile(project, await f.text(), f.name)
    setItems(r.items); setCurrent(r.item.id); setSaved(onOpen(r.layout)); show(r.missing)
    info(r.missing.length ? '' : `Макет «${r.item.name}» загружен из файла и сохранён в проекте.`)
  }).finally(() => { if (file.current) file.current.value = '' })

  return (
    <details className="builder-library" open={items.length > 0 || undefined}>
      <summary>Макеты проекта <span className="muted">{items.length}</span></summary>
      <div className="lib-row">
        <select value={current} onChange={e => { setCurrent(e.target.value); setMode(''); setSaved(null) }} aria-label="Сохранённые макеты"
          disabled={!items.length}>
          <option value="">{items.length ? 'выберите макет…' : 'макетов пока нет'}</option>
          {items.map(i => <option key={i.id} value={i.id}>{i.name} · рядов: {i.series}</option>)}
        </select>
        <button type="button" className="quiet" disabled={!item || busy} onClick={open}>Открыть</button>
      </div>
      <div className="lib-row wrap">
        <button type="button" className="quiet" disabled={!filled || busy} onClick={() => { setMode(mode === 'new' ? '' : 'new'); setName('') }}
          title="Сохранить график на экране под новым именем">Сохранить как…</button>
        <button type="button" className="quiet" disabled={!item || !filled || busy} onClick={overwrite} title="Записать график на экране в выбранный макет">
          Обновить{dirty ? ' *' : ''}</button>
        <button type="button" className="quiet" disabled={!item || busy} onClick={() => { setMode(mode === 'rename' ? '' : 'rename'); setName(item?.name ?? '') }}>Переименовать</button>
        <button type="button" className="quiet" disabled={!item || busy} onClick={copy}>Дублировать</button>
        <button type="button" className="quiet" disabled={!item || busy} onClick={remove}>Удалить</button>
      </div>
      {mode && (
        <form className="lib-row" onSubmit={e => { e.preventDefault(); if (mode === 'new') create(); else rename() }}>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Имя макета" aria-label="Имя макета" maxLength={120} autoFocus />
          <button type="submit" className="primary" disabled={!name.trim() || busy}>{mode === 'new' ? 'Создать макет' : 'Переименовать'}</button>
          <button type="button" className="quiet" onClick={() => setMode('')}>Отмена</button>
        </form>
      )}
      <div className="lib-row wrap">
        <button type="button" className="quiet" disabled={!filled || busy} title="Файл JSON: макет можно открыть в другом проекте и на другом компьютере"
          onClick={() => run(() => builderApi.exportFile(project, item?.name ?? (layout.title || 'Макет'), layout))}>Экспорт макета</button>
        <button type="button" className="quiet" disabled={busy} onClick={() => file.current?.click()}>Импорт макета</button>
        <input ref={file} type="file" accept=".json,application/json" hidden onChange={e => importFile(e.target.files?.[0])} />
      </div>
      {message?.text && <div className={'note ' + message.level} role="status">{message.text}</div>}
      {missing.length > 0 && (
        <div className="note warning" role="alert">
          <strong>В этом проекте нет части данных макета.</strong> Макет открыт, недостающие ряды покажутся пустыми, пока вы не выберете другие поля:
          <ul>{missing.map(m => <li key={m}>{m}</li>)}</ul>
        </div>
      )}
      <h3>Выгрузка графика</h3>
      <p className="muted lib-hint">PNG, SVG и PDF — значок загрузки над графиком. Здесь Word и данные.</p>
      <div className="lib-row wrap">
        <button type="button" className="quiet" disabled={!filled || busy} onClick={() => run(() => builderApi.data(project, layout, 'xlsx'))}
          title="Все точки каждого ряда и график средствами Excel">Данные XLSX</button>
        <button type="button" className="quiet" disabled={!filled || busy} onClick={() => run(() => builderApi.data(project, layout, 'csv'))}
          title="По строке на точку: ряд, ось, X, Y">Данные CSV</button>
      </div>
      <details className="lib-word">
        <summary>Word: график с заголовком и подписью</summary>
        <label className="field">Заголовок<input value={word.title} placeholder={layout.title || 'как у графика'} onChange={e => setWord({ ...word, title: e.target.value })} /></label>
        <label className="field">Подпись («Рисунок 1 – …»)<input value={word.caption} placeholder="как заголовок" onChange={e => setWord({ ...word, caption: e.target.value })} /></label>
        <label className="field">Лист
          <select value={word.orientation} onChange={e => setWord({ ...word, orientation: e.target.value })}>
            <option value="landscape">альбомный</option><option value="portrait">книжный</option>
          </select>
        </label>
        <label className="field">Номер рисунка
          <select value={word.caption_mode} onChange={e => setWord({ ...word, caption_mode: e.target.value })}>
            <option value="field">поле Word (ссылка)</option><option value="text">обычный текст</option>
          </select>
        </label>
        <button type="button" className="primary" disabled={!filled || busy}
          onClick={() => run(() => builderApi.word(project, { layout, title: word.title || layout.title, caption: word.caption, orientation: word.orientation, caption_mode: word.caption_mode }))}>Скачать Word</button>
      </details>
      <p className="muted lib-hint">В отчёт «Авторский надзор» макет добавляется в его параметре «Макеты конструктора в отчёте».</p>
    </details>
  )
}

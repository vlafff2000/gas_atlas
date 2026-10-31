import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'
import { builderApi, type SeriesWells } from './api'
import { Dialog } from './BuilderDialogs'
import type { BuilderLayout } from './ChartBuilder'

// Скважина макета: переключение графика по скважинам и выгрузка серии (рисунки по скважинам в zip, PDF или Word).

export function WellPicker({ wells, value, onChange, onSeries }:
  { wells: string[]; value: string; onChange: (well: string) => void; onSeries: () => void }) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const shown = useMemo(() => (q ? wells.filter(w => w.toLowerCase().includes(q)) : wells), [wells, q])
  const list = shown.includes(value) || !value ? shown : [value, ...shown]
  const at = wells.indexOf(value)
  const go = (step: number) => { if (wells.length) onChange(wells[Math.min(wells.length - 1, Math.max(0, at < 0 ? (step > 0 ? 0 : wells.length - 1) : at + step))]) }
  const keys = (e: KeyboardEvent) => {
    if (!(e.target instanceof HTMLSelectElement) && !(e.target instanceof HTMLButtonElement)) return   // в поле поиска стрелки двигают курсор
    if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1) } else if (e.key === 'ArrowRight') { e.preventDefault(); go(1) }
  }
  return (
    <fieldset className="well-picker" onKeyDown={keys}>
      <legend>Скважина макета</legend>
      <div className="lib-row">
        <button type="button" className="quiet" onClick={() => go(-1)} disabled={at <= 0} title="Предыдущая скважина (←)" aria-label="Предыдущая скважина">←</button>
        <select value={value} onChange={e => onChange(e.target.value)} aria-label="Скважина макета" title="← и → переключают скважину">
          <option value="">не выбрана</option>
          {list.map(w => <option key={w} value={w}>№ {w}</option>)}
        </select>
        <button type="button" className="quiet" onClick={() => go(1)} disabled={at >= wells.length - 1} title="Следующая скважина (→)" aria-label="Следующая скважина">→</button>
      </div>
      <div className="lib-row">
        <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Найти скважину…" aria-label="Поиск скважины" />
        <button type="button" className="quiet" onClick={onSeries} title="PNG, PDF или Word по выбранным скважинам">Серия по скважинам</button>
      </div>
      <p className="muted">Ряды в режиме «Текущая скважина» берут её. В заголовке и названии ряда <code>{'{скважина}'}</code> заменится номером.</p>
    </fieldset>
  )
}

type Pick = 'data' | 'all' | 'list' | 'groups'

export function SeriesDialog({ project, layout, onClose }: { project: string; layout: BuilderLayout; onClose: () => void }) {
  const [info, setInfo] = useState<SeriesWells | null>(null)
  const [error, setError] = useState('')
  const [pick, setPick] = useState<Pick>('data')
  const [chosen, setChosen] = useState<string[]>([])
  const [groups, setGroups] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [format, setFormat] = useState('png')
  const [orientation, setOrientation] = useState('landscape')
  const [captionMode, setCaptionMode] = useState('field')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    builderApi.seriesWells(project, layout).then(setInfo).catch(e => setError((e as Error).message))
  }, [project]) // eslint-disable-line react-hooks/exhaustive-deps

  const wells = useMemo(() => {
    if (!info) return []
    if (pick === 'all') return info.wells
    if (pick === 'data') return info.with_data
    if (pick === 'groups') return info.wells.filter(w => info.groups.some(g => groups.includes(g.name) && g.wells.includes(w)))
    return info.wells.filter(w => chosen.includes(w))
  }, [info, pick, chosen, groups])
  const q = query.trim().toLowerCase()
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter(x => x !== v) : [...list, v])
  const tooMany = !!info && wells.length > info.limit
  const run = async () => {
    setBusy(true); setMessage(''); setError('')
    try {
      const notes = await builderApi.series(project, { layout, wells, format, orientation, title, caption_mode: captionMode })
      setMessage(`Файл сохранён: графиков ${wells.length}.` + (notes ? ' ' + notes : ''))
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Dialog title="Серия по скважинам" subtitle={layout.title || undefined} onClose={onClose}>
      <div className="series-body">
        {!info && !error && <p className="muted">Загрузка скважин…</p>}
        {info && !info.enabled && <div className="note warning">В макете нет ряда в режиме «Текущая скважина»: включите его в карточке ряда.</div>}
        {info && (
          <>
            <label className="field"><span className="field-label">Какие скважины</span>
              <select value={pick} onChange={e => setPick(e.target.value as Pick)}>
                <option value="data">все, у кого есть данные ({info.with_data.length})</option>
                <option value="all">все скважины проекта ({info.wells.length})</option>
                <option value="list">выбрать из списка</option>
                {info.groups.length > 0 && <option value="groups">выбрать группы</option>}
              </select>
            </label>
            {(pick === 'list' || pick === 'groups') && (
              <>
                <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder={pick === 'list' ? 'Найти скважину…' : 'Найти группу…'} aria-label="Поиск" />
                <ul className="series-list">
                  {pick === 'list' ? info.wells.filter(w => !q || w.toLowerCase().includes(q)).map(w => (
                    <li key={w}><label><input type="checkbox" checked={chosen.includes(w)} onChange={() => setChosen(toggle(chosen, w))} /> № {w}
                      {!info.with_data.includes(w) && <small className="muted"> нет данных</small>}</label></li>
                  )) : info.groups.filter(g => !q || g.name.toLowerCase().includes(q)).map(g => (
                    <li key={g.name}><label><input type="checkbox" checked={groups.includes(g.name)} onChange={() => setGroups(toggle(groups, g.name))} /> {g.name}
                      <small className="muted"> {g.wells.length} скв.</small></label></li>
                  ))}
                </ul>
                {pick === 'list' && (
                  <div className="lib-row">
                    <button type="button" className="quiet" onClick={() => setChosen(info.wells.filter(w => !q || w.toLowerCase().includes(q)))}>Отметить найденные</button>
                    <button type="button" className="quiet" onClick={() => setChosen([])}>Снять все</button>
                  </div>
                )}
              </>
            )}
            <label className="field"><span className="field-label">Формат</span>
              <select value={format} onChange={e => setFormat(e.target.value)}>
                {Object.entries(info.formats).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            {format === 'docx' && (
              <>
                <label className="field"><span className="field-label">Заголовок документа</span>
                  <input value={title} onChange={e => setTitle(e.target.value)} placeholder="без заголовка" /></label>
                <label className="field"><span className="field-label">Лист</span>
                  <select value={orientation} onChange={e => setOrientation(e.target.value)}>
                    <option value="landscape">альбомный</option><option value="portrait">книжный</option>
                  </select></label>
                <label className="field"><span className="field-label">Номер рисунка</span>
                  <select value={captionMode} onChange={e => setCaptionMode(e.target.value)}>
                    <option value="field">поле Word (ссылка)</option><option value="text">обычный текст</option>
                  </select></label>
              </>
            )}
            <p className={tooMany ? 'note warning' : 'muted'}>
              {tooMany ? `Выбрано ${wells.length} скважин, за один раз можно не больше ${info.limit}. Выберите меньше.` : `К выгрузке: ${wells.length} скв. Скважины без данных пропускаются, их перечень будет в заметке.`}
            </p>
            <button type="button" className="primary" disabled={busy || !info.enabled || !wells.length || tooMany} onClick={run}>
              {busy ? 'Готовим файл…' : 'Скачать серию'}</button>
          </>
        )}
        {message && <div className="note info" role="status">{message}</div>}
        {error && <div className="note warning" role="alert">{error}</div>}
      </div>
    </Dialog>
  )
}

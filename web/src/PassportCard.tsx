import { ChartView } from './ChartView'
import { HeatView } from './HeatView'
import { TableDock } from './TableDock'
import { TableView } from './TableView'
import { SchematicNotes, WellSchematic } from './WellFigure'
import { useState } from 'react'
import type { Project, Table } from './api'
import { passportApi, type DepressionType, type PassportCard as Card } from './api_passport'

/** Дашборд паспорта: показатели, схема забоя, графики и таблицы — те же ChartView и TableView, что в остальных модулях. */
const LEVELS: [string, string][] = [['strong', 'сильная'], ['weak', 'слабая'], ['none', 'нет'], ['unknown', 'неизвестно']]

/** Решение инженера по механизму оценки: главнее автоматической подсказки, сохраняется в проекте; «Снять» возвращает расчёт. */
function AssessOverride({ card, project, revision, onProject }: { card: Card; project: string; revision?: number; onProject: (p: Project) => void }) {
  const rows = card.assess ?? []
  const [mech, setMech] = useState('')
  const [level, setLevel] = useState('weak')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  if (!rows.length) return null
  const current = mech || rows[0].mechanism
  const save = async (value: string | null) => {
    setError('')
    try { onProject(await passportApi.saveAssess(project, card.well, current, value, note, revision)); setNote('') } catch (e) { setError((e as Error).message) }
  }
  return (
    <div className="note info assess-override">
      <b>Решение инженера</b>{' '}
      <select value={current} onChange={e => setMech(e.target.value)} aria-label="Механизм">{rows.map(r => <option key={r.mechanism} value={r.mechanism}>{r.name}</option>)}</select>{' '}
      <select value={level} onChange={e => setLevel(e.target.value)} aria-label="Уровень">{LEVELS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>{' '}
      <input value={note} onChange={e => setNote(e.target.value)} placeholder="Примечание (необязательно)" aria-label="Примечание" />{' '}
      <button type="button" onClick={() => save(level)}>Записать</button>{' '}
      <button type="button" className="quiet" onClick={() => save(null)}>Снять решение</button>
      {error && <span className="muted"> {error}</span>}
    </div>)
}

/** Проверка критериев на истории: улики на 1 января каждого года против фактических КР; считается по запросу (по всем скважинам проекта). */
function Backtest({ project }: { project: string }) {
  const [tables, setTables] = useState<Table[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = async () => {
    setBusy(true); setError('')
    try { setTables((await passportApi.backtest(project, [2022, 2023, 2024, 2025])).tables) } catch (e) { setError((e as Error).message) }
    setBusy(false)
  }
  return (
    <details className="note info">
      <summary>Проверка критериев на истории (КР 2022–2025)</summary>
      <p>Что показали бы улики на 1 января года, в котором скважину потом ремонтировали: только данные до этой даты. Считает все скважины проекта, это занимает время.</p>
      <button type="button" onClick={run} disabled={busy}>{busy ? 'Считаю…' : 'Проверить'}</button>
      {error && <p className="error">{error}</p>}
      {tables?.map(t => <TableView key={t.id} table={t} docked onDownload={async () => { throw new Error('Выгрузка проверки пока не сделана: скопируйте таблицу с экрана.') }} />)}
    </details>
  )
}

/** Таблица «механизм → операция»: что подсказывать при сильной и слабой улике; правит инженер, «Сбросить» возвращает умолчания. */
function Operations({ card, project, revision, onProject }: { card: Card; project: string; revision?: number; onProject: (p: Project) => void }) {
  const ops = card.operations
  const [draft, setDraft] = useState<Record<string, { strong?: string; weak?: string }>>({})
  const [error, setError] = useState('')
  if (!ops) return null
  const run = async (body: Record<string, { strong?: string; weak?: string }> | null) => {
    setError('')
    try { onProject(await passportApi.saveOperations(project, body, revision)); setDraft({}) } catch (e) { setError((e as Error).message) }
  }
  const text = (m: string, lvl: 'strong' | 'weak', base: string) => draft[m]?.[lvl] ?? base
  const edit = (m: string, lvl: 'strong' | 'weak', v: string) => setDraft(d => ({ ...d, [m]: { ...d[m], [lvl]: v } }))
  return (
    <details className="note info assess-override">
      <summary>Таблица «механизм → операция»{ops.edited ? ' (есть ваши правки)' : ''}</summary>
      <p>Что подсказывать, когда улика механизма сильная или слабая. Это подсказка: решает инженер. Пустое поле возвращает умолчание.</p>
      <table><thead><tr><th>Механизм</th><th>Сильная улика</th><th>Слабая улика</th></tr></thead><tbody>
        {ops.rows.map(r => (
          <tr key={r.mechanism}><td>{r.name}</td>
            {(['strong', 'weak'] as const).map(l => <td key={l}><input style={{ width: '100%' }} value={text(r.mechanism, l, r[l])} onChange={e => edit(r.mechanism, l, e.target.value)} aria-label={`${r.name}: ${l === 'strong' ? 'сильная' : 'слабая'}`} /></td>)}
          </tr>))}
      </tbody></table>
      <button type="button" onClick={() => run(Object.fromEntries(ops.rows.map(r => [r.mechanism, { strong: text(r.mechanism, 'strong', r.strong), weak: text(r.mechanism, 'weak', r.weak) }])))}>Записать</button>{' '}
      <button type="button" onClick={() => run(null)}>Сбросить к умолчаниям</button>
      {error && <p className="error">{error}</p>}
    </details>
  )
}

/** Кандидаты в КРС по всему фонду: скважины по убыванию суммы улик; считается по запросу. */
function Fund({ project }: { project: string }) {
  const [tables, setTables] = useState<Table[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = async () => {
    setBusy(true); setError('')
    try { setTables((await passportApi.fund(project)).tables) } catch (e) { setError((e as Error).message) }
    setBusy(false)
  }
  return (
    <details className="note info">
      <summary>Кандидаты в КРС по фонду</summary>
      <p>Скважины проекта по убыванию суммы улик с причинами и подсказкой операции. Считает все скважины, это занимает время.</p>
      <button type="button" onClick={run} disabled={busy}>{busy ? 'Считаю…' : 'Составить список'}</button>
      {error && <p className="error">{error}</p>}
      {tables && !tables.length && <p>Улик ни у одной скважины нет.</p>}
      {tables?.map(t => <TableView key={t.id} table={t} docked onDownload={async () => { throw new Error('Выгрузка списка пока не сделана: скопируйте таблицу с экрана.') }} />)}
    </details>
  )
}

/** Пределы депрессии и тип забоя скважины: редактирует инженер; авто-тип — подсказка по конструкции, «авто» снимает ручной выбор. */
function DepressionSettings({ card, project, revision, onProject }: { card: Card; project: string; revision?: number; onProject: (p: Project) => void }) {
  const dep = card.depression
  const [limits, setLimits] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  if (!dep || !dep.rows.length) return null
  const text = (t: DepressionType) => limits[t.key] ?? String(t.limit)
  const run = async (body: Parameters<typeof passportApi.saveDepression>[1]) => {
    setError('')
    try { onProject(await passportApi.saveDepression(project, body, revision)); setLimits({}) } catch (e) { setError((e as Error).message) }
  }
  const saveLimits = () => run({ types: dep.types.map(t => ({ ...t, limit: Number(text(t).replace(',', '.')) })) })
  return (
    <div className="note info assess-override">
      <b>Предел депрессии, кгс/см²</b>{' '}
      {dep.types.map(t => (
        <label key={t.key}>{t.name}{' '}
          <input value={text(t)} size={4} onChange={e => setLimits(v => ({ ...v, [t.key]: e.target.value }))} aria-label={`Предел: ${t.name}`} />{' '}</label>))}
      <button type="button" onClick={saveLimits}>Записать пределы</button>{' · '}
      <label>Тип забоя скважины{' '}
        <select value={dep.type === dep.type_auto ? '' : dep.type ?? ''} onChange={e => run({ well: card.well, type: e.target.value || null })} aria-label="Тип забоя">
          <option value="">авто{dep.type_auto ? `: ${dep.types.find(t => t.key === dep.type_auto)?.name}` : ': не определён'}</option>
          {dep.types.map(t => <option key={t.key} value={t.key}>{t.name}</option>)}
        </select></label>
      {error && <span className="muted"> {error}</span>}
    </div>)
}

export function PassportDashboard({ card, project, seasons, revision, onProject }: { card: Card; project: string; seasons: string[]; revision?: number; onProject?: (p: Project) => void }) {
  const none = (value: Card['kpi'][number]) => value.value === null && !value.text
  const num = (v: number, digits: number) => v.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return (
    <div className="passport-dash">
      <dl className="summary-strip" aria-label="Показатели скважины">
        {card.kpi.map(k => (
          <div key={k.label} title={[k.hint, k.extra].filter(Boolean).join(' · ') || undefined}>
            <dt>{k.label}</dt>
            <dd>{none(k) ? '—' : k.text ?? `${num(k.value!, k.digits ?? 1)}${k.unit ? ' ' + k.unit : ''}`}</dd>
          </div>))}
      </dl>
      <section className="panel schematic-panel">
        <h2>Забойная часть скважины № {card.well}</h2>
        <WellSchematic s={card.schematic} />
        <SchematicNotes s={card.schematic} />
        <p className="muted small">Показаны эксплуатационная колонна, НКТ, фильтр, перфорация, расширка, пакер и забой; кондуктор и прочие колонны
          скрыты. Ширина условная, диаметры — в подписях.{card.construction_date ? ` Конструкция на ${card.construction_date}.` : ''}</p>
      </section>
      {card.notes.map(n => <div key={n} className="note info">{n}</div>)}
      <div className="chart-grid">
        {card.charts.map(c => c.heat ? (          // плитки КРУ и КРС по годам — общая тепловая карта
          <HeatView key={c.id} chart={c} module="passport"
            onCopy={() => passportApi.exportBlob(project, card.well, seasons, 'chart', c.id, 'png', 300)}
            onDownload={(format, dpi) => passportApi.exportFile(project, card.well, seasons, 'chart', c.id, format, dpi)} />
        ) : (
          <ChartView key={c.id} chart={c} excludeMode={false} onExclude={() => {}}
            onCopy={view => passportApi.exportBlob(project, card.well, seasons, 'chart', c.id, 'png', 300, view)}
            onDownload={(format, dpi, view) => passportApi.exportFile(project, card.well, seasons, 'chart', c.id, format, dpi, view)} />))}
      </div>
      <TableDock tables={card.tables} scope="passport" render={t => (
        <TableView key={t.id} table={t} docked onDownload={format => passportApi.exportFile(project, card.well, seasons, 'table', t.id, format)} />)} />
      {onProject && <Operations card={card} project={project} revision={revision} onProject={onProject} />}
      {onProject && <Fund project={project} />}
      {onProject && <Backtest project={project} />}
      {onProject && <DepressionSettings card={card} project={project} revision={revision} onProject={onProject} />}
      {onProject && <AssessOverride card={card} project={project} revision={revision} onProject={onProject} />}
      {(card.elpro_help ?? []).length > 0 && card.tables.some(t => t.id === 'passport-elpro') && (
        <details className="note info"><summary>Как читать данные ЭЛПРО</summary>
          <ul>{(card.elpro_help ?? []).map(t => <li key={t}>{t}</li>)}</ul></details>)}
      {!card.tables.some(t => t.id === 'passport-krs') && card.krs.note && <div className="note info">{card.krs.note}</div>}
      {card.krs.priority && card.krs.priority.value !== null && (
        <div className="note info">Приоритет КР (подсказка, решает инженер): <b>{card.krs.priority.value}</b>
          {card.krs.priority.reason ? ` — ${card.krs.priority.reason}` : ''}</div>)}
    </div>
  )
}

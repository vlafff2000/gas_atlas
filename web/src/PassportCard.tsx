import { ChartView } from './ChartView'
import { HeatView } from './HeatView'
import { TableDock } from './TableDock'
import { TableView } from './TableView'
import { SchematicNotes, WellSchematic } from './WellFigure'
import { useState } from 'react'
import type { Project } from './api'
import { passportApi, type PassportCard as Card } from './api_passport'

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

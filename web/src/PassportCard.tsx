import { ChartView } from './ChartView'
import { TableDock } from './TableDock'
import { TableView } from './TableView'
import { WellSchematic } from './WellFigure'
import { passportApi, type PassportCard as Card } from './api_passport'

/** Дашборд паспорта: показатели, схема забоя, графики и таблицы — те же ChartView и TableView, что в остальных модулях. */
export function PassportDashboard({ card, project, seasons }: { card: Card; project: string; seasons: string[] }) {
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
        {card.schematic.shapes && card.schematic.notes.map(n => <div key={n} className="note info">{n}</div>)}
        <p className="muted small">Показаны эксплуатационная колонна, НКТ, фильтр, перфорация, расширка, пакер и забой; кондуктор и прочие колонны
          скрыты. Ширина условная, диаметры — в подписях.{card.construction_date ? ` Конструкция на ${card.construction_date}.` : ''}</p>
      </section>
      {card.notes.map(n => <div key={n} className="note info">{n}</div>)}
      <div className="chart-grid">
        {card.charts.map(c => (
          <ChartView key={c.id} chart={c} excludeMode={false} onExclude={() => {}}
            onCopy={view => passportApi.exportBlob(project, card.well, seasons, 'chart', c.id, 'png', 300, view)}
            onDownload={(format, dpi, view) => passportApi.exportFile(project, card.well, seasons, 'chart', c.id, format, dpi, view)} />))}
      </div>
      <TableDock tables={card.tables} scope="passport" render={t => (
        <TableView key={t.id} table={t} docked onDownload={format => passportApi.exportFile(project, card.well, seasons, 'table', t.id, format)} />)} />
      {!card.tables.some(t => t.id === 'passport-krs') && card.krs.note && <div className="note info">{card.krs.note}</div>}
      {card.krs.priority && card.krs.priority.value !== null && (
        <div className="note info">Приоритет КР (подсказка, решает инженер): <b>{card.krs.priority.value}</b>
          {card.krs.priority.reason ? ` — ${card.krs.priority.reason}` : ''}</div>)}
    </div>
  )
}

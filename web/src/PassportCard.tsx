import { ChartView } from './ChartView'
import { TableDock } from './TableDock'
import { TableView } from './TableView'
import { passportApi, type PassportCard as Card, type Schematic } from './api_passport'

/** Забойная часть: рисуется по фигурам ядра (те же, что на странице PDF), глубина вниз. */
export function WellSchematic({ s }: { s: Schematic }) {
  if (!s.shapes || s.items.length === 0) return <p className="muted">{s.notes[0] ?? 'Нет конструкции.'}</p>
  const W = 720, H = 500, left = 46, scaleX = 68, cx = left + 3.2 * scaleX
  const y = (m: number) => 12 + (m - s.top) / (s.bottom - s.top) * (H - 24)
  const x = (u: number) => cx + u * scaleX
  const step = Math.max(Math.round((s.bottom - s.top) / 5 / 10) * 10, 5)
  const ticks: number[] = []
  for (let t = (Math.floor(s.top / step) + 1) * step; t < s.bottom; t += step) ticks.push(t)
  return (
    <svg className="well-schematic" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Схема забойной части: эксплуатационная колонна, НКТ, фильтр, интервалы расширки, забой">
      <defs>
        <pattern id="pp-slots" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="#14b8a6" /><line x1="0" y1="0" x2="0" y2="6" stroke="#0f766e" strokeWidth="2" />
        </pattern>
        <pattern id="pp-sand" width="5" height="5" patternUnits="userSpaceOnUse">
          <rect width="5" height="5" fill="#e8c987" /><circle cx="1.5" cy="1.5" r=".8" fill="#a8791f" /><circle cx="4" cy="4" r=".8" fill="#a8791f" />
        </pattern>
      </defs>
      <rect x="0" y="0" width={W} height={H} rx="8" className="schematic-bg" />
      {ticks.map(t => (
        <g key={t}><line x1={left - 6} x2={left} y1={y(t)} y2={y(t)} className="schematic-tick" />
          <text x={left - 9} y={y(t)} className="schematic-tick-text" textAnchor="end" dominantBaseline="middle">{t}</text></g>))}
      <text x={left - 9} y="10" className="schematic-tick-text" textAnchor="end">м</text>
      {s.shapes.map((f, i) => f.t === 'rect'
        ? <rect key={i} x={x(f.x0)} y={y(f.y0)} width={(f.x1 - f.x0) * scaleX} height={Math.max(y(f.y1) - y(f.y0), 1)}
                fill={f.pattern === 'slots' ? 'url(#pp-slots)' : f.pattern === 'sand' ? 'url(#pp-sand)' : f.fill}>
            <title>{f.name}</title></rect>
        : <line key={i} x1={x(f.x0)} x2={x(f.x1)} y1={y(f.y0)} y2={y(f.y1)} stroke={f.stroke} strokeWidth={f.width} />)}
      {(s.labels ?? []).map((l, i) => (
        <g key={i}>
          <polyline points={`${x(1.15)},${y(l.y)} ${x(2.2)},${y(l.y)} ${x(2.4)},${y(l.at)} ${x(2.6)},${y(l.at)}`}
                    fill="none" stroke={l.color} strokeWidth=".8" />
          <text x={x(2.65)} y={y(l.at)} fill={l.color} className="schematic-label" dominantBaseline="middle">{l.text}</text>
        </g>))}
    </svg>
  )
}

/** Дашборд паспорта: показатели, схема забоя, графики и таблицы — те же ChartView и TableView, что в остальных модулях. */
export function PassportDashboard({ card, project }: { card: Card; project: string }) {
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
            onCopy={view => passportApi.exportBlob(project, card.well, 'chart', c.id, 'png', 300, view)}
            onDownload={(format, dpi, view) => passportApi.exportFile(project, card.well, 'chart', c.id, format, dpi, view)} />))}
      </div>
      <TableDock tables={card.tables} scope="passport" render={t => (
        <TableView key={t.id} table={t} docked onDownload={format => passportApi.exportFile(project, card.well, 'table', t.id, format)} />)} />
      {!card.tables.some(t => t.id === 'passport-krs') && card.krs.note && <div className="note info">{card.krs.note}</div>}
      {card.krs.priority && card.krs.priority.value !== null && (
        <div className="note info">Приоритет КР (подсказка, решает инженер): <b>{card.krs.priority.value}</b>
          {card.krs.priority.reason ? ` — ${card.krs.priority.reason}` : ''}</div>)}
    </div>
  )
}

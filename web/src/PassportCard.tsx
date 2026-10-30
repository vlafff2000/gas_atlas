import { DailyChart, GdiDiagrams } from './PassportCharts'
import type { Kpi, PassportCard as Card, SeasonRow, Schematic } from './api_passport'

const fmt = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : v.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })

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

function KpiCard({ k }: { k: Kpi }) {
  const empty = k.value === null && !k.text
  return (
    <div className={'kpi-card' + (empty ? ' kpi-none' : '')}>
      <span className="kpi-label">{k.label}</span>
      <span className="kpi-value">{k.text ?? fmt(k.value, k.digits ?? 1)}{!empty && k.unit && k.value !== null ? <small> {k.unit}</small> : null}</span>
      <span className="kpi-hint">{[k.hint, k.extra].filter(Boolean).join(' · ') || ' '}</span>
    </div>
  )
}

/** Объём по сезонам: столбики, высота — объём; подпись — Qmax сезона. */
function SeasonBars({ rows, kind }: { rows: SeasonRow[]; kind: 'withdrawal' | 'injection' }) {
  const part = rows.filter(r => r.kind === kind && r.volume !== null).reverse()   // таблица идёт от свежего сезона, столбики — слева направо по времени
  if (part.length === 0) return null
  const top = Math.max(...part.map(r => r.volume!)) || 1
  const W = Math.max(280, part.length * 74), H = 150
  return (
    <svg className="season-bars" viewBox={`0 0 ${W} ${H}`} width={W} role="img" aria-label={kind === 'withdrawal' ? 'Отбор по сезонам' : 'Закачка по сезонам'}>
      {part.map((r, i) => {
        const h = (r.volume! / top) * (H - 56)
        return (
          <g key={r.period} transform={`translate(${i * 74 + 14},0)`}>
            <rect x="0" y={H - 24 - h} width="46" height={h} rx="3" className={'bar-' + kind}><title>{`${r.period}: ${fmt(r.volume, 2)} млн м³`}</title></rect>
            <text x="23" y={H - 28 - h} textAnchor="middle" className="bar-value">{fmt(r.volume, 2)}</text>
            <text x="23" y={H - 8} textAnchor="middle" className="bar-axis">{r.period}</text>
          </g>)
      })}
    </svg>
  )
}

function SeasonsTable({ rows }: { rows: SeasonRow[] }) {
  if (rows.length === 0) return <p className="muted">Нет данных по сезонам.</p>
  const label = (k: string) => (k === 'withdrawal' ? 'Отбор' : 'Закачка')
  return (
    <table className="passport-table">
      <thead><tr><th>Вид</th><th>Сезон</th><th className="num">Объём, млн м³</th><th className="num">Отработано дней</th><th className="num">Qmax, тыс. м³/сут</th><th>Дата Qmax</th>
        <th className="num">Qср, тыс. м³/сут</th><th className="num">Часы</th><th className="num">Вода, м³</th></tr></thead>
      <tbody>{rows.map(r => (
        <tr key={r.kind + r.period}><td>{label(r.kind)}</td><td>{r.period}</td><td className="num">{fmt(r.volume, 2)}</td>
          <td className="num">{r.days}</td><td className="num"><b>{fmt(r.max_rate, 1)}</b></td><td>{r.max_date}</td>
          <td className="num">{fmt(r.mean_rate, 1)}</td><td className="num">{fmt(r.hours, 0)}</td><td className="num">{fmt(r.water, 1)}</td></tr>))}</tbody>
    </table>
  )
}

/** Дашборд паспорта: показатели, схема забоя, сезоны, ГДИ за всё время, КРС. */
export function PassportDashboard({ card }: { card: Card }) {
  return (
    <div className="passport-dash">
      <div className="kpi-grid">{card.kpi.map(k => <KpiCard key={k.label} k={k} />)}</div>
      <div className="dash-row">
        <section className="dash-panel schematic-panel">
          <h2>Забойная часть скважины № {card.well}</h2>
          <WellSchematic s={card.schematic} />
          <p className="muted small">Показаны эксплуатационная колонна, НКТ, фильтр, перфорация, расширка, пакер и забой; кондуктор и прочие колонны
            скрыты. Ширина условная, диаметры — в подписях.{card.construction_date ? ` Конструкция на ${card.construction_date}.` : ''}</p>
        </section>
        <section className="dash-panel">
          <h2>Объём по сезонам</h2>
          <h3>Отбор</h3><SeasonBars rows={card.seasons} kind="withdrawal" />
          <h3>Закачка</h3><SeasonBars rows={card.seasons} kind="injection" />
          {card.seasons.length === 0 && <p className="muted">Нет данных по сезонам.</p>}
        </section>
      </div>
      <section className="dash-panel"><h2>Сезоны эксплуатации</h2>
        <p className="muted small">Сверху самый свежий сезон, затем предыдущий другого вида (отбор / закачка) и так далее.</p>
        <div className="table-scroll"><SeasonsTable rows={card.seasons} /></div></section>
      <section className="dash-panel"><h2>Суточные расходы</h2><DailyChart daily={card.daily} /></section>
      <section className="dash-panel"><h2>Индикаторные диаграммы ГДИ</h2><GdiDiagrams items={card.gdi_diagrams} /></section>
      <div className="dash-row">
        <section className="dash-panel">
          <h2>ГДИ за всё время</h2>
          <div className="table-scroll">
          {card.gdi.length === 0 ? <p className="muted">ГДИ по скважине нет.</p> : (
            <table className="passport-table">
              <thead><tr><th>Дата</th><th>Метод</th><th className="num">a</th><th className="num">b</th><th className="num">R²</th><th className="num">Qmax</th><th className="num">Qсв</th><th>Надёжно</th></tr></thead>
              <tbody>{card.gdi.map((g, i) => (
                <tr key={i} className={g.reliable ? '' : 'unreliable'} title={g.note}><td>{g.date}</td><td>{g.method || '—'}</td>
                  <td className="num">{fmt(g.a, 3)}</td><td className="num">{fmt(g.b, 4)}</td><td className="num">{fmt(g.r2, 3)}</td>
                  <td className="num">{fmt(g.q_max, 0)}</td><td className="num">{fmt(g.q_free, 0)}</td><td>{g.reliable ? 'да' : 'нет'}</td></tr>))}</tbody>
            </table>)}
          </div>
        </section>
        <section className="dash-panel">
          <h2>Проведённые КРС</h2>
          {card.krs.works.length === 0 ? <p className="muted">{card.krs.note}</p> : (
            <table className="passport-table">
              <thead><tr><th>Год</th><th>Тип ремонта</th><th>Подробности</th></tr></thead>
              <tbody>{card.krs.works.map((w, i) => <tr key={i}><td>{w.year ?? ''}</td><td>{w.type}</td><td>{w.detail}</td></tr>)}</tbody>
            </table>)}
          {card.krs.priority && card.krs.priority.value !== null && (
            <p className="small">Приоритет КР (подсказка, решает инженер): <b>{card.krs.priority.value}</b>
              {card.krs.priority.reason ? ` — ${card.krs.priority.reason}` : ''}</p>)}
        </section>
      </div>
      {card.notes.map(n => <div key={n} className="note info">{n}</div>)}
    </div>
  )
}

import type { Chart } from './api'
import { CopyButton, DownloadMenu } from './ChartView'

// Скважины × сезоны: строка — скважина, квадрат — сезон. Цвет квадрата — цвет ГСП, штриховка — в сезоне по ГСП ревизии не было.
const PALETTE = ['#2a6f97', '#d1495b', '#3a9d5d', '#e0a100', '#7b4fa3', '#e07a1f', '#2b9aa0', '#8c5a3c', '#5b6c8f', '#a3a33a']

interface Props {
  chart: Chart
  onDownload: (format: string, dpi: number) => Promise<void>
  onCopy?: () => Promise<Blob>
}

export function StripView({ chart, onDownload, onCopy }: Props) {
  const s = chart.strips
  if (!s) return null
  const groups = [...new Set(s.groups)]
  const color = (g: string) => PALETTE[groups.indexOf(g) % PALETTE.length]
  // Плитка скважины: номер, ряд мелких квадратов по сезонам и число сезонов; плитки идут потоком, сколько влезет в строку.
  const block = (idx: number[], key: string, title?: string) => (
    <div key={key} className="strip-group">
      {title && <p className="strip-sub" style={{ color: color(title) }}>{title}</p>}
      <div className="strip-chips">
        {idx.map(i => (
          <span key={s.rows[i]} className="strip-chip" title={s.rows[i] + ' · ' + s.groups[i] + ': ' + s.columns.map((c, j) => c + ' ' + (s.cells[i][j] === null ? s.missing_text : s.cells[i][j] ? 'да' : 'нет')).join(', ')}>
            <b>{s.rows[i].replace('№ ', '')}</b>
            <span className="dots">
              {s.cells[i].map((v, j) => v === null ? <i key={j} className="miss" /> : <i key={j} className={v ? 'on' : ''} style={v ? { background: color(s.groups[i]) } : undefined} />)}
            </span>
            <em>{s.counts[i]}</em>
          </span>))}
      </div>
    </div>
  )
  const all = s.rows.map((_, i) => i)
  return (
    <figure className="chart strips">
      <figcaption>
        <span title={chart.title}>{chart.title}</span>
        <span className="chart-actions">
          {onCopy && <CopyButton onCopy={onCopy} />}
          <DownloadMenu onDownload={onDownload} />
        </span>
      </figcaption>
      <div className="strip-wrap" role="img" aria-label={chart.title}>
        {s.layout === 'panels'
          ? <div className="strip-panels">{groups.map(g => block(all.filter(i => s.groups[i] === g), g, g))}</div>
          : block(all, 'all')}
        <div className="strip-legend">
          <span>Квадраты слева направо: {s.columns.join(' · ')}; число справа — сколько сезонов</span>
          {groups.map(g => <span key={g}><i style={{ background: color(g) }} />{g}</span>)}
          <span><i style={{ background: 'repeating-linear-gradient(45deg, transparent 0 3px, #b9c4c7 3px 4px)' }} />{s.missing_text}</span>
        </div>
      </div>
    </figure>
  )
}

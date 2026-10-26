import type { Chart } from './api'
import { CopyButton, DownloadMenu } from './ChartView'

// Тепловая карта «строка × столбец» (ГСП × сезоны): цветная таблица с числами. Нет данных — штриховка с подписью.
const SCALE = [[255, 247, 236], [253, 212, 158], [252, 141, 89], [215, 48, 31], [127, 0, 0]]

function shade(t: number): string {
  const x = Math.min(1, Math.max(0, t)) * (SCALE.length - 1), i = Math.min(SCALE.length - 2, Math.floor(x)), f = x - i
  const c = SCALE[i].map((v, k) => Math.round(v + (SCALE[i + 1][k] - v) * f))
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
}

interface Props {
  chart: Chart
  onDownload: (format: string, dpi: number) => Promise<void>
  onCopy?: () => Promise<Blob>
}

export function HeatView({ chart, onDownload, onCopy }: Props) {
  const h = chart.heat
  if (!h) return null
  const top = h.maximum || Math.max(1, ...h.values.flat().filter((v): v is number => v !== null))
  return (
    <figure className="chart heat">
      <figcaption>
        <span title={chart.title}>{chart.title}</span>
        <span className="chart-actions">
          {onCopy && <CopyButton onCopy={onCopy} />}
          <DownloadMenu onDownload={onDownload} />
        </span>
      </figcaption>
      <div className="heat-wrap">
        <table className="heat-table" role="img" aria-label={chart.title}>
          <thead><tr><th />{h.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {h.rows.map((row, i) => (
              <tr key={row}><th scope="row">{row}</th>
                {h.values[i].map((v, j) => v === null
                  ? <td key={j} className="heat-missing" title={h.texts[i][j] || h.missing_text}>{h.texts[i][j] || h.missing_text}</td>
                  : <td key={j} style={{ background: shade(v / top), color: v / top > 0.55 ? '#fff' : undefined }}>{h.texts[i][j]}</td>)}
              </tr>))}
          </tbody>
        </table>
        <div className="heat-scale" aria-hidden="true">
          <span>{h.unit}</span>
          <i style={{ background: `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map(shade).join(', ')})` }} />
          <span className="heat-ends"><b>0</b><b>{Math.round(top)}</b></span>
        </div>
      </div>
    </figure>
  )
}

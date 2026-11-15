import type { Chart } from './api'
import { CopyButton, DownloadMenu } from './ChartView'
import { useSpecialFormat } from './SpecialFormat'
import { heatColor, isDark, rgb } from './heatScale'

// Тепловая карта «строка × столбец» (ГСП × сезоны): цветная таблица с числами. Нет данных — штриховка. Шкала, пределы, числа и текст «нет данных» — из оформления (chart.style, heat_*).

interface Props {
  chart: Chart
  onDownload: (format: string, dpi: number) => Promise<void>
  onCopy?: () => Promise<Blob>
  module?: string
}

export function HeatView({ chart: given, onDownload, onCopy, module }: Props) {
  const fmt = useSpecialFormat(given, module)
  const chart = fmt.chart
  const h = chart.heat
  if (!h) return null
  const st = chart.style ?? {}
  const scheme = st.heat_scale ?? 'orange', reverse = !!st.heat_reverse
  const data = h.values.flat().filter((v): v is number => v !== null)
  const low = st.heat_min ?? 0
  const top = st.heat_max ?? (h.maximum || Math.max(1, ...data))
  const span = top > low ? top - low : 1
  const shade = (v: number) => heatColor((v - low) / span, scheme, reverse)
  const missing = st.heat_missing || h.missing_text
  const cellStyle = st.heat_cell_size ? { fontSize: st.heat_cell_size } : undefined
  return (
    <figure className="chart heat" style={fmt.frame}>
      <figcaption>
        <span title={chart.title} style={fmt.title} onDoubleClick={() => fmt.open()}>{chart.title}</span>
        <span className="chart-actions">
          <span className="chart-tools">{fmt.button}</span>
          {onCopy && <CopyButton onCopy={onCopy} />}
          <DownloadMenu onDownload={onDownload} />
        </span>
      </figcaption>
      {fmt.pane}
      <div className="heat-wrap">
        <table className="heat-table" role="img" aria-label={chart.title}>
          <thead><tr><th />{h.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {h.rows.map((row, i) => (
              <tr key={row}><th scope="row">{row}</th>
                {h.values[i].map((v, j) => v === null
                  ? <td key={j} className="heat-missing" style={cellStyle} title={h.texts[i][j] || missing}>{h.texts[i][j] || missing}</td>
                  : <td key={j} style={{ ...cellStyle, background: rgb(shade(v)), color: isDark(shade(v)) ? '#fff' : undefined }}>{st.heat_values === false ? '' : h.texts[i][j]}</td>)}
              </tr>))}
          </tbody>
        </table>
        {st.heat_bar !== 'hide' && <div className={'heat-scale' + (st.heat_bar === 'right' ? ' right' : '')} aria-hidden="true">
          <span>{h.unit}</span>
          <i style={{ background: `linear-gradient(to ${st.heat_bar === 'right' ? 'top' : 'right'}, ${[0, 0.25, 0.5, 0.75, 1].map(t => rgb(heatColor(t, scheme, reverse))).join(', ')})` }} />
          <span className="heat-ends"><b>{Math.round(low)}</b><b>{Math.round(top)}</b></span>
        </div>}
      </div>
    </figure>
  )
}

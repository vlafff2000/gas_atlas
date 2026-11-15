import type { Chart } from './api'
import { CopyButton, DownloadMenu } from './ChartView'
import { useState } from 'react'
import { tooltipsOn, usePref } from './chartPrefs'
import { useSpecialFormat } from './SpecialFormat'
import { heatColor, isDark, rgb } from './heatScale'
import { heatLayout, totalText } from './heatLayout'

// Тепловая карта «строка × столбец» (ГСП × сезоны): цветная таблица с числами. Нет данных — штриховка. Шкала, пределы, числа и текст «нет данных» — из оформления (chart.style, heat_*).

interface Props {
  chart: Chart
  onDownload: (format: string, dpi: number) => Promise<void>
  onCopy?: () => Promise<Blob>
  module?: string
}

export function HeatView({ chart: given, onDownload, onCopy, module }: Props) {
  const fmt = useSpecialFormat(given, module)
  const tips = usePref(tooltipsOn)
  const [mark, setMark] = useState<[number, number] | null>(null)      // наведённая ячейка: подсвечиваются её строка и столбец
  const [pinned, setPinned] = useState<[number, number] | null>(null)  // закреплённая щелчком
  const chart = fmt.chart
  const h = chart.heat
  if (!h) return null
  const st = chart.style ?? {}
  const lay = heatLayout(h.rows, h.values, st)
  const rows = lay.order.map(i => h.rows[i]), values = lay.order.map(i => h.values[i]), texts = lay.order.map(i => h.texts[i])
  const scheme = st.heat_scale ?? 'orange', reverse = !!st.heat_reverse
  const data = h.values.flat().filter((v): v is number => v !== null)
  const low = st.heat_min ?? 0
  const top = st.heat_max ?? (h.maximum || Math.max(1, ...data))
  const span = top > low ? top - low : 1
  const shade = (v: number) => heatColor((v - low) / span, scheme, reverse)
  const missing = st.heat_missing || h.missing_text
  const at = pinned ?? mark
  const tip = (i: number, j: number, text: string) => tips ? `${rows[i]} · ${h.columns[j]}: ${text}${h.unit && values[i][j] !== null ? ' ' + h.unit : ''}` : undefined
  const cls = (i: number, j: number) => at && (at[0] === i || at[1] === j) ? (at[0] === i && at[1] === j ? ' hl-cell' : ' hl-line') : ''
  const hot = (i: number, j: number) => ({ onMouseEnter: () => setMark([i, j]), onMouseLeave: () => setMark(null), onClick: () => setPinned(p => p && p[0] === i && p[1] === j ? null : [i, j]) })
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
          <thead><tr><th />{h.columns.map((c, j) => <th key={c} className={at?.[1] === j ? 'hl' : undefined}>{c}</th>)}{lay.rowTotals && <th>Итого</th>}</tr></thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row}><th scope="row" className={at?.[0] === i ? 'hl' : undefined}>{row}</th>
                {values[i].map((v, j) => v === null
                  ? <td key={j} className={'heat-missing' + cls(i, j)} style={cellStyle} title={tip(i, j, texts[i][j] || missing)} {...hot(i, j)}>{texts[i][j] || missing}</td>
                  : <td key={j} className={cls(i, j).trim() || undefined} title={tip(i, j, texts[i][j] || String(v))} {...hot(i, j)} style={{ ...cellStyle, background: rgb(shade(v)), color: isDark(shade(v)) ? '#fff' : undefined }}>{st.heat_values === false ? '' : texts[i][j]}</td>)}
                {lay.rowTotals && <td className="heat-total" style={cellStyle}>{totalText(lay.rowTotals[i])}</td>}
              </tr>))}
            {lay.colTotals && <tr><th scope="row">Итого</th>{lay.colTotals.map((t, j) => <td key={j} className="heat-total" style={cellStyle}>{totalText(t)}</td>)}{lay.rowTotals && <td />}</tr>}
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

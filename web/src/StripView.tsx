import type { Chart } from './api'
import { CopyButton, DownloadMenu } from './ChartView'
import { useState } from 'react'
import { tooltipsOn, usePref } from './chartPrefs'
import { useSpecialFormat } from './SpecialFormat'

/** Порядок плиток (strip_order): как в данных, по числу сезонов (больше — раньше), по номеру скважины. Зеркало atlas/chart_special.py: strip_order. */
function stripOrder(rows: string[], counts: number[], idx: number[], order?: string): number[] {
  const num = (i: number) => (rows[i].match(/\d+/g) ?? ['1000000000']).map(Number)
  const cmp = (a: number[], b: number[]) => { for (let k = 0; k < Math.min(a.length, b.length); k++) if (a[k] !== b[k]) return a[k] - b[k]; return a.length - b.length }
  if (order === 'count') return [...idx].sort((a, b) => counts[b] - counts[a] || a - b)
  if (order === 'number') return [...idx].sort((a, b) => cmp(num(a), num(b)) || a - b)
  return idx
}

// Скважины × сезоны: строка — скважина, квадрат — сезон. Цвет квадрата — цвет ГСП, штриховка — в сезоне по ГСП ревизии не было.
const PALETTE = ['#2a6f97', '#d1495b', '#3a9d5d', '#e0a100', '#7b4fa3', '#e07a1f', '#2b9aa0', '#8c5a3c', '#5b6c8f', '#a3a33a']

interface Props {
  chart: Chart
  onDownload: (format: string, dpi: number) => Promise<void>
  onCopy?: () => Promise<Blob>
  module?: string
}

export function StripView({ chart: given, onDownload, onCopy, module }: Props) {
  const fmt = useSpecialFormat(given, module)
  const tips = usePref(tooltipsOn)
  const [find, setFind] = useState('')                 // подсветка скважин по номеру: найденные яркие, остальные приглушены
  const [pinned, setPinned] = useState<string[]>([])   // закреплённые щелчком по плитке
  const chart = fmt.chart
  const s = chart.strips
  if (!s) return null
  const st = chart.style ?? {}
  const groups = [...new Set(s.groups)]
  const query = find.trim().toLowerCase()
  const lit = (i: number) => pinned.includes(s.rows[i]) || (query !== '' && s.rows[i].replace('№ ', '').toLowerCase().includes(query))
  const anyLit = query !== '' || pinned.length > 0
  const ordered = (idx: number[]) => stripOrder(s.rows, s.counts, idx, st.strip_order)
  const missingText = st.strip_missing || s.missing_text
  const empty = st.strip_empty_color
  const color = (g: string) => s.colors?.[g] ?? PALETTE[groups.indexOf(g) % PALETTE.length]
  // Плитка скважины: номер, ряд мелких квадратов по сезонам и число сезонов; плитки идут потоком, сколько влезет в строку.
  const block = (idx: number[], key: string, title?: string) => (
    <div key={key} className="strip-group">
      {title && <p className="strip-sub" style={{ color: color(title) }}>{title}</p>}
      <div className="strip-chips" style={st.strip_per_row ? { display: 'grid', gridTemplateColumns: `repeat(${st.strip_per_row}, max-content)` } : undefined}>
        {ordered(idx).map(i => (
          <span key={s.rows[i]} className={'strip-chip' + (anyLit ? (lit(i) ? ' lit' : ' dim') : '')} onClick={() => setPinned(p => p.includes(s.rows[i]) ? p.filter(x => x !== s.rows[i]) : [...p, s.rows[i]])} title={!tips ? undefined : s.rows[i] + ' · ' + s.groups[i] + ': ' + s.columns.map((c, j) => c + ' ' + (s.cells[i][j] === null ? missingText : s.cells[i][j] ? 'да' : 'нет')).join(', ')}>
            <b>{s.rows[i].replace('№ ', '')}</b>
            <span className="dots">
              {s.cells[i].map((v, j) => v === null ? <i key={j} className="miss" /> : <i key={j} className={v ? 'on' : ''} style={v ? { background: color(s.groups[i]) } : empty ? { background: empty, opacity: 1 } : undefined} />)}
            </span>
            {st.strip_counts !== false && <em>{s.counts[i]}</em>}
          </span>))}
      </div>
    </div>
  )
  const all = s.rows.map((_, i) => i)
  return (
    <figure className="chart strips" style={fmt.frame}>
      <figcaption>
        <span title={chart.title} style={fmt.title} onDoubleClick={() => fmt.open()}>{chart.title}</span>
        <span className="chart-actions">
          <span className="chart-tools">{fmt.button}</span>
          {onCopy && <CopyButton onCopy={onCopy} />}
          <DownloadMenu onDownload={onDownload} />
        </span>
      </figcaption>
      {fmt.pane}
      <div className="strip-find"><input value={find} onChange={e => setFind(e.target.value)} placeholder="Найти скважину по номеру" aria-label="Найти скважину по номеру" />
        {(find || pinned.length > 0) && <button type="button" onClick={() => { setFind(''); setPinned([]) }}>Снять выделение</button>}</div>
      <div className="strip-wrap" role="img" aria-label={chart.title}>
        {s.layout === 'panels'
          ? <div className="strip-panels">{groups.map(g => block(all.filter(i => s.groups[i] === g), g, g))}</div>
          : block(all, 'all')}
        {st.strip_legend !== false && <div className="strip-legend">
          <span>Квадраты слева направо: {s.columns.join(' · ')}{st.strip_counts !== false ? '; число справа — сколько сезонов' : ''}</span>
          {groups.map(g => <span key={g}><i style={{ background: color(g) }} />{g}</span>)}
          <span><i style={{ background: 'repeating-linear-gradient(45deg, #fff4d6 0 2px, #8a5a00 2px 4px)' }} />{missingText}</span>
        </div>}
      </div>
    </figure>
  )
}

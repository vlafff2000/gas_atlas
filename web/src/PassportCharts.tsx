import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart, ScatterChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { GdiDiagram, DailySeries } from './api_passport'

echarts.use([LineChart, ScatterChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

/** Холст ECharts под паспорт: пересоздаётся при смене настроек, подстраивается под ширину. */
function useChart(option: echarts.EChartsCoreOption | null, height: number) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = box.current
    if (!el || !option) return
    const chart = echarts.init(el, undefined, { renderer: 'canvas' })
    chart.setOption(option)
    const watch = new ResizeObserver(() => chart.resize())
    watch.observe(el)
    return () => { watch.disconnect(); chart.dispose() }
  }, [option])
  return <div ref={box} className="passport-chart" style={{ height }} />
}

const PALETTE = ['#0f766e', '#2563eb', '#d97706', '#be123c', '#7c3aed', '#0891b2', '#65a30d', '#c026d3']
const num = (v: number, d = 1) => v.toLocaleString('ru-RU', { maximumFractionDigits: d })

/** Индикаторные диаграммы: точки режимов (q, Δp²) и кривая Δp² = a·q + b·q² каждого исследования; ненадёжные — пунктиром. */
export function GdiDiagrams({ items }: { items: GdiDiagram[] }) {
  const [shown, setShown] = useState<Set<number> | null>(null)       // null — показаны первые пять (свежие)
  const active = useMemo(() => shown ?? new Set(items.slice(0, 5).map((_, i) => i)), [shown, items])
  const option = useMemo(() => {
    const series: echarts.EChartsCoreOption[] = []
    items.forEach((g, i) => {
      if (!active.has(i)) return
      const color = PALETTE[i % PALETTE.length]
      const name = `${g.date}${g.method ? ' · ' + g.method : ''}`
      series.push({ name, type: 'scatter', symbolSize: 8, itemStyle: { color }, data: g.points })
      if (g.a !== null && g.b !== null) {
        const top = Math.max(...g.points.map(p => p[0]))
        const curve = Array.from({ length: 41 }, (_, k) => { const q = (top * 1.05 * k) / 40; return [q, g.a! * q + g.b! * q * q] })
        series.push({ name, type: 'line', showSymbol: false, silent: true, lineStyle: { color, width: 1.6, type: g.reliable ? 'solid' : 'dashed' }, data: curve })
      }
    })
    return {
      animation: false, grid: { left: 70, right: 20, top: 30, bottom: 50 },
      tooltip: { trigger: 'item', formatter: (p: { seriesName: string; value: number[] }) => `${p.seriesName}<br/>q = ${num(p.value[0], 2)}; Δp² = ${num(p.value[1], 1)}` },
      xAxis: { type: 'value', name: 'Дебит q, тыс. м³/сут', nameLocation: 'middle', nameGap: 30, min: 0 },
      yAxis: { type: 'value', name: 'Δp² = p_пл² − p_заб², (кгс/см²)²', nameLocation: 'end', min: 0 },
      series,
    }
  }, [items, active])
  const chart = useChart(items.length ? option : null, 380)
  if (items.length === 0) return <p className="muted">Нет режимов ГДИ для индикаторных диаграмм.</p>
  const toggle = (i: number) => setShown(() => { const n = new Set(active); if (n.has(i)) n.delete(i); else n.add(i); return n })
  return (
    <>
      <div className="gdi-picks">
        {items.map((g, i) => (
          <label key={i} className="toggle" title={g.reliable ? 'Надёжное исследование' : 'Ненадёжное: R² или число режимов ниже порога; решает инженер'}>
            <input type="checkbox" checked={active.has(i)} onChange={() => toggle(i)} />
            <span style={{ color: PALETTE[i % PALETTE.length] }}>●</span>
            <span>{g.date}{g.reliable ? '' : ' (ненадёжное)'}</span>
          </label>))}
      </div>
      {chart}
      <p className="muted small">Точки — режимы исследования, линия — аппроксимация Δp² = a·q + b·q². Пунктир — ненадёжное исследование.</p>
    </>
  )
}

/** Суточные расходы скважины за все сезоны: масштаб колесом и ползунком, подсказка с часами работы. */
export function DailyChart({ daily }: { daily: Record<'withdrawal' | 'injection', DailySeries> }) {
  const [kind, setKind] = useState<'withdrawal' | 'injection'>(daily.withdrawal.date.length || !daily.injection.date.length ? 'withdrawal' : 'injection')
  const s = daily[kind]
  const option = useMemo(() => ({
    animation: false, grid: { left: 70, right: 20, top: 30, bottom: 70 },
    tooltip: {
      trigger: 'axis',
      formatter: (items: { dataIndex: number }[]) => {
        const i = items[0].dataIndex
        const hours = s.hours[i]
        return `${s.date[i].split('-').reverse().join('.')} · ${s.period[i]}<br/>Суточный объём: <b>${s.volume[i] === null ? '—' : num(s.volume[i]!, 2)}</b> тыс. м³`
          + `<br/>Часы работы: ${hours === null ? 'нет данных' : num(hours, 1)}`
      },
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 10 }],
    xAxis: { type: 'category', data: s.date, axisLabel: { formatter: (v: string) => v.split('-').reverse().join('.') } },
    yAxis: { type: 'value', name: 'тыс. м³/сут', min: 0 },
    series: [{ type: 'line', showSymbol: s.date.length < 200, symbolSize: 4, connectNulls: false, lineStyle: { width: 1.3, color: kind === 'withdrawal' ? '#0f766e' : '#4f63c9' },
      itemStyle: { color: kind === 'withdrawal' ? '#0f766e' : '#4f63c9' }, data: s.volume }],
  }), [s, kind])
  const chart = useChart(s.date.length ? option : null, 360)
  return (
    <>
      <div className="passport-tabs">
        <button type="button" aria-pressed={kind === 'withdrawal'} onClick={() => setKind('withdrawal')}>Отбор</button>
        <button type="button" aria-pressed={kind === 'injection'} onClick={() => setKind('injection')}>Закачка</button>
      </div>
      {s.date.length ? chart : <p className="muted">Суточных расходов по этому виду нет.</p>}
    </>
  )
}

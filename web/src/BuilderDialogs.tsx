import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { AxisStyle, ChartStyle } from './api'
import { SeriesLookFields } from './ChartSettings'
import { AxisStyleFields, ChartStyleFields, Commit, Flag, Text, compact } from './FormatFields'
import type { Look } from './chartStyle'
import { RichField } from './RichField'
import './builder.css'

// Всплывающие окна настройки конструктора: «Ряд», «Ось», «График». Всё необязательно: пустое поле — авто.
// Значения лежат в макете (layout.series[].look, layout.axis_style, layout.chart_style), график меняется сразу.

export { compact }
export type AxisKey = 'x' | 'y' | 'y2' | 'y3' | 'y4' | 'y5'
/** Настройки оси в макете: границы и шаг — текстом (у оси дат границы — даты), остальное — значения. */
export interface AxisFmt {
  min?: string; max?: string; step?: string; log?: boolean; inverse?: boolean; from_zero?: boolean; color?: string
  decimals?: number; date_format?: string; font?: string; tick_size?: number; title_size?: number
  title_bold?: boolean; title_italic?: boolean; tick_bold?: boolean; tick_italic?: boolean
  ticks?: AxisStyle['ticks']; minor_ticks?: AxisStyle['ticks']; line?: boolean; line_color?: string; line_width?: number; label_rotate?: number
  units?: AxisStyle['units']; title_place?: 'end' | 'middle'; minor_step?: string; cross?: string
}

/** Окно настройки: перетаскивается за заголовок, не закрывает график, Esc закрывает. */
export function Dialog({ title, subtitle, onClose, dockRight, children }: { title: string; subtitle?: string; onClose: () => void; dockRight?: boolean; children: ReactNode }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const drag = useRef<{ dx: number; dy: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div ref={box} className={'chart-settings builder-dialog' + (dockRight ? ' dock-right' : '')} role="dialog" aria-label={title}
      style={pos ? { left: pos.x, top: pos.y, right: 'auto' } : undefined}>
      <header
        onPointerDown={e => {
          if ((e.target as HTMLElement).closest('button')) return
          const r = box.current!.getBoundingClientRect()
          drag.current = { dx: e.clientX - r.left, dy: e.clientY - r.top }
          e.currentTarget.setPointerCapture(e.pointerId)
        }}
        onPointerMove={e => {
          const d = drag.current
          if (d) setPos({ x: Math.max(0, Math.min(window.innerWidth - 120, e.clientX - d.dx)), y: Math.max(0, Math.min(window.innerHeight - 40, e.clientY - d.dy)) })
        }}
        onPointerUp={() => { drag.current = null }}
        title="Окно можно перетащить за заголовок">
        <b>{title}</b>
        {subtitle && <span className="cs-title" title={subtitle}>{subtitle}</span>}
        <button type="button" className="cs-close" onClick={onClose} aria-label="Закрыть окно">×</button>
      </header>
      {children}
    </div>, document.body)
}

// ---------- ряд ----------

export type BuilderView = 'line' | 'points' | 'line_points' | 'bar' | 'area' | 'step' | 'hist'
/** Вид ряда в карточке: линия, точки, линия с точками, столбцы, область (линия с заливкой), ступенчатая линия. */
export const VIEWS: [BuilderView, string][] = [['line', 'линия'], ['points', 'точки'], ['line_points', 'линия с точками'],
  ['bar', 'столбцы'], ['area', 'область'], ['step', 'ступенчатая'], ['hist', 'гистограмма']]
const VIEW_LABEL = Object.fromEntries(VIEWS) as Record<BuilderView, string>

export interface RowItem { id: string; title: string; view: BuilderView; look: Look }

export function SeriesDialog({ rows, activeId, onActive, onChange, onClose }:
  { rows: RowItem[]; activeId: string | null; onActive: (id: string) => void; onChange: (id: string, look: Look) => void; onClose: () => void }) {
  const row = rows.find(r => r.id === activeId) ?? rows[0]
  return (
    <Dialog title="Ряд: линия и маркеры" subtitle="пусто — авто" onClose={onClose}>
      <div className="cs-body">
        <ul className="cs-list">
          {rows.map((r, i) => (
            <li key={r.id}>
              <button type="button" aria-pressed={r.id === row?.id} onClick={() => onActive(r.id)} title={r.title}>
                <i style={{ background: r.look.color ?? 'var(--line)' }} /><span>{i + 1}. {r.title}</span>
              </button>
            </li>
          ))}
        </ul>
        {row && <div className="cs-editor">
          <h3>{row.title} <small>{VIEW_LABEL[row.view]}</small></h3>
          <SeriesLookFields s={{ kind: row.view === 'points' ? 'points' : row.view === 'bar' || row.view === 'hist' ? 'bar' : 'line', fill: row.view === 'area', dash: '', dashed: false, width: 0, markers: row.view === 'line_points', symbol: 'circle', opacity: 1 }}
            color="#2a78d6" look={row.look} onChange={patch => onChange(row.id, compact({ ...row.look, ...patch }))} />
          <p className="cs-hint">Цвет «авто» — по палитре: каждая скважина своим цветом. Заданный цвет получают все кривые ряда.</p>
          <div className="cs-actions">
            <button type="button" onClick={() => onChange(row.id, {})} disabled={Object.keys(row.look).length === 0}>Сбросить ряд</button>
          </div>
        </div>}
      </div>
    </Dialog>
  )
}

// ---------- ось ----------

export interface AxisItem { key: AxisKey; title: string; label: string; auto: string; time: boolean }


export function AxisDialog({ axes, activeKey, onActive, fmt, onLabel, onChange, onClose }: {
  axes: AxisItem[]; activeKey: AxisKey; onActive: (k: AxisKey) => void; fmt: Partial<Record<AxisKey, AxisFmt>>
  onLabel: (k: AxisKey, label: string) => void; onChange: (k: AxisKey, f: AxisFmt) => void; onClose: () => void
}) {
  const axis = axes.find(a => a.key === activeKey) ?? axes[0]
  const f: AxisFmt = (axis && fmt[axis.key]) || {}
  const set = (patch: Partial<AxisFmt>) => axis && onChange(axis.key, compact({ ...f, ...patch }))
  return (
    <Dialog title="Ось: подпись, границы, шрифт" subtitle="пусто — авто" onClose={onClose}>
      <div className="cs-body">
        <ul className="cs-list">
          {axes.map(a => (
            <li key={a.key}>
              <button type="button" aria-pressed={a.key === axis?.key} onClick={() => onActive(a.key)} title={a.auto}>
                <i style={{ background: fmt[a.key]?.color ?? 'var(--line)' }} /><span>{a.title}{a.key === 'x' ? ' (по горизонтали)' : a.key === 'y' ? ' (слева)' : ' (справа)'}</span>
              </button>
            </li>
          ))}
        </ul>
        {axis && <div className="cs-editor">
          <h3>Ось {axis.title}</h3>
          <fieldset>
            <legend>Подпись</legend>
            <Text label="Название оси" value={axis.label} placeholder={axis.auto} onChange={v => onLabel(axis.key, v)} />
          </fieldset>
          <fieldset>
            <legend>Шкала</legend>
            <div className="cs-row">
              <Commit key={axis.key + 'min'} label="Минимум" value={f.min} placeholder={axis.time ? 'авто (дата)' : 'авто'} onChange={v => set({ min: v })} />
              <Commit key={axis.key + 'max'} label="Максимум" value={f.max} placeholder={axis.time ? 'авто (дата)' : 'авто'} onChange={v => set({ max: v })} />
            </div>
            {axis.time
              ? <p className="cs-hint">Границы по датам: 31.12.2025 или 2025-12-31; применяются по Enter. Деления по времени подбираются сами.</p>
              : <>
                <Commit key={axis.key + 'step'} label="Шаг делений" value={f.step} placeholder="авто" onChange={v => set({ step: v })} />
                <Commit key={axis.key + 'minor'} label="Дополнительный шаг" value={f.minor_step} placeholder="нет" onChange={v => set({ minor_step: v })} />
              </>}
            {!axis.time && <Flag label="Логарифмическая шкала" value={f.log} onChange={v => set({ log: v })} title="Только для положительных значений" />}
            <Flag label="Обратное направление" value={f.inverse} onChange={v => set({ inverse: v })} />
            {!axis.time && <Flag label="Начинать с нуля" value={f.from_zero} onChange={v => set({ from_zero: v })} />}
          </fieldset>
          <AxisStyleFields value={f} set={set} time={axis.time} />
          <div className="cs-actions">
            <button type="button" onClick={() => { onChange(axis.key, {}); onLabel(axis.key, '') }}
              disabled={Object.keys(f).length === 0 && !axis.label}>Сбросить ось</button>
          </div>
        </div>}
      </div>
    </Dialog>
  )
}

// ---------- график ----------

export function ChartDialog({ title, autoTitle, style, onTitle, onChange, onClose }: {
  title: string; autoTitle: string; style: ChartStyle; onTitle: (t: string) => void; onChange: (s: ChartStyle) => void; onClose: () => void
}) {
  const set = (patch: Partial<ChartStyle>) => onChange(compact({ ...style, ...patch }))
  return (
    <Dialog title="График: заголовок, легенда, сетка, фон" subtitle="пусто — авто" onClose={onClose}>
      <div className="cs-body single">
        <div className="cs-editor">
          <ChartStyleFields value={style} set={set}
            title={<RichField label="Текст" value={title} placeholder={autoTitle} onChange={onTitle} />} />
          <div className="cs-actions">
            <button type="button" onClick={() => { onChange({}); onTitle('') }} disabled={Object.keys(style).length === 0 && !title}>Сбросить оформление</button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

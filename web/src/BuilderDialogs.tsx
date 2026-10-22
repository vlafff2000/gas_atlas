import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { ChartStyle } from './api'
import { HEX, SeriesLookFields } from './ChartSettings'
import { FONT_CHOICES } from './chartTheme'
import type { Look } from './chartStyle'
import './builder.css'

// Всплывающие окна настройки конструктора: «Ряд», «Ось», «График». Всё необязательно: пустое поле — авто.
// Значения лежат в макете (layout.series[].look, layout.axis_style, layout.chart_style), график меняется сразу.

export type AxisKey = 'x' | 'y' | 'y2' | 'y3' | 'y4' | 'y5'
/** Настройки оси в макете: границы и шаг — текстом (у оси дат границы — даты), остальное — значения. */
export interface AxisFmt {
  min?: string; max?: string; step?: string; log?: boolean; inverse?: boolean; from_zero?: boolean; color?: string
  decimals?: number; date_format?: string; font?: string; tick_size?: number; title_size?: number
}

/** Убирает пустые значения: пусто — авто, в макете не хранится (ложь остаётся: «без линии», «обычный» — тоже выбор). */
export function compact<T extends object>(value: T): T {
  const out = {} as Record<string, unknown>
  for (const [k, v] of Object.entries(value)) if (v !== undefined && v !== '' && !(typeof v === 'number' && Number.isNaN(v))) out[k] = v
  return out as T
}

/** Окно настройки: перетаскивается за заголовок, не закрывает график, Esc закрывает. */
export function Dialog({ title, subtitle, onClose, children }: { title: string; subtitle?: string; onClose: () => void; children: ReactNode }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const drag = useRef<{ dx: number; dy: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div ref={box} className="chart-settings builder-dialog" role="dialog" aria-label={title}
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label>{label}{children}</label>
}

/** Список из вариантов с пунктом «авто»: пустое значение — в макете поля нет. */
function Choice<T extends string>({ label, value, options, onChange, auto = 'авто' }:
  { label: string; value: T | undefined; options: { value: T; label: string }[]; onChange: (v: T | undefined) => void; auto?: string }) {
  return (
    <Field label={label}>
      <select value={value ?? ''} onChange={e => onChange((e.target.value || undefined) as T | undefined)}>
        <option value="">{auto}</option>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Field>
  )
}

function Num({ label, value, min, max, step = 1, unit, onChange }:
  { label: string; value: number | undefined; min: number; max: number; step?: number; unit?: string; onChange: (v: number | undefined) => void }) {
  return (
    <Field label={label}>
      <span className="cs-range">
        <input type="number" min={min} max={max} step={step} value={value ?? ''} placeholder="авто"
          onChange={e => { const n = e.target.value === '' ? undefined : Number(e.target.value); onChange(n !== undefined && Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : undefined) }} />
        {unit && <output>{unit}</output>}
      </span>
    </Field>
  )
}

function Text({ label, value, placeholder, onChange }: { label: string; value: string | undefined; placeholder: string; onChange: (v: string) => void }) {
  return <Field label={label}><input type="text" value={value ?? ''} placeholder={placeholder} onChange={e => onChange(e.target.value)} /></Field>
}

/** Текстовое поле, которое применяется по Enter или при выходе из поля: недописанная дата или число не даёт ошибку на каждом знаке. */
function Commit({ label, value, placeholder, onChange }: { label: string; value: string | undefined; placeholder: string; onChange: (v: string) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const done = () => { if (draft !== null && draft !== (value ?? '')) onChange(draft.trim()); setDraft(null) }
  return (
    <Field label={label}>
      <input type="text" value={draft ?? value ?? ''} placeholder={placeholder} onChange={e => setDraft(e.target.value)} onBlur={done}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); done() } }} />
    </Field>
  )
}

function Color({ label, value, onChange }: { label: string; value: string | undefined; onChange: (v: string | undefined) => void }) {
  return (
    <Field label={label}>
      <span className="cs-range">
        <input type="color" value={value && HEX.test(value) ? value : '#888888'} onChange={e => onChange(e.target.value)} />
        <button type="button" className="cs-auto" disabled={value === undefined} onClick={() => onChange(undefined)} title="Вернуть: авто">авто</button>
      </span>
    </Field>
  )
}

function Flag({ label, value, onChange, title }: { label: string; value: boolean | undefined; onChange: (v: boolean) => void; title?: string }) {
  return <label className="cs-check" title={title}><input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} /> {label}</label>
}

const FONT_OPTIONS = FONT_CHOICES.map(f => ({ value: f.value, label: f.label }))

// ---------- ряд ----------

export type BuilderView = 'line' | 'points' | 'line_points' | 'bar' | 'area' | 'step'
/** Вид ряда в карточке: линия, точки, линия с точками, столбцы, область (линия с заливкой), ступенчатая линия. */
export const VIEWS: [BuilderView, string][] = [['line', 'линия'], ['points', 'точки'], ['line_points', 'линия с точками'],
  ['bar', 'столбцы'], ['area', 'область'], ['step', 'ступенчатая']]
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
          <SeriesLookFields s={{ kind: row.view === 'points' ? 'points' : row.view === 'bar' ? 'bar' : 'line', fill: row.view === 'area', dash: '', dashed: false, width: 0, markers: row.view === 'line_points', symbol: 'circle', opacity: 1 }}
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

const DATE_FORMATS = [
  { value: 'dd.MM.yyyy', label: '31.12.2025' }, { value: 'MM.yyyy', label: '12.2025' },
  { value: 'yyyy', label: '2025' }, { value: 'dd.MM', label: '31.12' },
]

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
              : <Commit key={axis.key + 'step'} label="Шаг делений" value={f.step} placeholder="авто" onChange={v => set({ step: v })} />}
            {!axis.time && <Flag label="Логарифмическая шкала" value={f.log} onChange={v => set({ log: v })} title="Только для положительных значений" />}
            <Flag label="Обратное направление" value={f.inverse} onChange={v => set({ inverse: v })} />
            {!axis.time && <Flag label="Начинать с нуля" value={f.from_zero} onChange={v => set({ from_zero: v })} />}
            <Color label="Цвет оси и подписей" value={f.color} onChange={v => set({ color: v })} />
          </fieldset>
          <fieldset>
            <legend>Подписи делений</legend>
            {axis.time
              ? <Choice label="Формат даты" value={f.date_format} options={DATE_FORMATS} onChange={v => set({ date_format: v })} />
              : <Num label="Знаков после запятой" value={f.decimals} min={0} max={8} onChange={v => set({ decimals: v })} />}
            <Choice label="Шрифт" value={f.font} options={FONT_OPTIONS} onChange={v => set({ font: v })} auto="как у графика" />
            <div className="cs-row">
              <Num label="Размер подписей" value={f.tick_size} min={5} max={30} onChange={v => set({ tick_size: v })} />
              <Num label="Размер названия" value={f.title_size} min={5} max={30} onChange={v => set({ title_size: v })} />
            </div>
          </fieldset>
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

const LEGENDS: { value: NonNullable<ChartStyle['legend']>; label: string }[] = [
  { value: 'bottom', label: 'Снизу' }, { value: 'top', label: 'Сверху' }, { value: 'right', label: 'Справа' }, { value: 'hide', label: 'Скрыть' },
]
const GRIDS: { value: NonNullable<ChartStyle['grid']>; label: string }[] = [
  { value: 'both', label: 'Горизонтальная и вертикальная' }, { value: 'h', label: 'Только горизонтальная' },
  { value: 'v', label: 'Только вертикальная' }, { value: 'none', label: 'Без сетки' },
]
const ALIGNS: { value: NonNullable<ChartStyle['title_align']>; label: string }[] = [
  { value: 'left', label: 'Слева' }, { value: 'center', label: 'По центру' }, { value: 'right', label: 'Справа' },
]

export function ChartDialog({ title, autoTitle, style, onTitle, onChange, onClose }: {
  title: string; autoTitle: string; style: ChartStyle; onTitle: (t: string) => void; onChange: (s: ChartStyle) => void; onClose: () => void
}) {
  const set = (patch: Partial<ChartStyle>) => onChange(compact({ ...style, ...patch }))
  return (
    <Dialog title="График: заголовок, легенда, сетка, фон" subtitle="пусто — авто" onClose={onClose}>
      <div className="cs-body single">
        <div className="cs-editor">
          <fieldset>
            <legend>Заголовок</legend>
            <Text label="Текст" value={title} placeholder={autoTitle} onChange={onTitle} />
            <Choice label="Шрифт" value={style.title_font} options={FONT_OPTIONS} onChange={v => set({ title_font: v })} auto="как у графика" />
            <div className="cs-row">
              <Num label="Размер" value={style.title_size} min={6} max={48} onChange={v => set({ title_size: v })} />
              <Choice label="Начертание" value={style.title_bold === undefined ? undefined : style.title_bold ? 'b' : 'n'}
                options={[{ value: 'b', label: 'Жирный' }, { value: 'n', label: 'Обычный' }]}
                onChange={v => onChange(compact({ ...style, title_bold: v === undefined ? undefined : v === 'b' }))} />
            </div>
            <Choice label="Выравнивание" value={style.title_align} options={ALIGNS} onChange={v => set({ title_align: v })} />
            <Color label="Цвет" value={style.title_color} onChange={v => set({ title_color: v })} />
          </fieldset>
          <fieldset>
            <legend>Текст графика</legend>
            <Choice label="Шрифт" value={style.font} options={FONT_OPTIONS} onChange={v => set({ font: v })} />
            <Color label="Цвет текста" value={style.text_color} onChange={v => set({ text_color: v })} />
            <p className="cs-hint">Шрифт и цвет действуют на заголовок, оси и легенду, если для них не заданы свои.</p>
          </fieldset>
          <fieldset>
            <legend>Легенда</legend>
            <Choice label="Положение" value={style.legend} options={LEGENDS} onChange={v => set({ legend: v })} auto="авто (снизу)" />
            <Choice label="Шрифт" value={style.legend_font} options={FONT_OPTIONS} onChange={v => set({ legend_font: v })} auto="как у графика" />
            <Num label="Размер" value={style.legend_size} min={5} max={30} onChange={v => set({ legend_size: v })} />
          </fieldset>
          <fieldset>
            <legend>Сетка и фон</legend>
            <Choice label="Сетка" value={style.grid} options={GRIDS} onChange={v => set({ grid: v })} />
            <Color label="Цвет сетки" value={style.grid_color} onChange={v => set({ grid_color: v })} />
            <Color label="Фон графика" value={style.background} onChange={v => set({ background: v })} />
            <Color label="Фон области построения" value={style.plot_background} onChange={v => set({ plot_background: v })} />
          </fieldset>
          <div className="cs-actions">
            <button type="button" onClick={() => { onChange({}); onTitle('') }} disabled={Object.keys(style).length === 0 && !title}>Сбросить оформление</button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

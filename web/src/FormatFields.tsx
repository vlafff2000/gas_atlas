import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { Annotation, AxisStyle, ChartStyle } from './api'
import { LINE_STYLES, type Look } from './chartStyle'
import { HEX } from './ChartSettings'
import { FONT_CHOICES } from './chartTheme'

// Общие поля настройки оформления: используются панелью «Формат» на графике (FormatPane) и окнами конструктора.
// Всё необязательно: пустое поле — авто, в документе оформления его нет.

/** Убирает пустые значения: пусто — авто, в макете не хранится (ложь остаётся: «без линии», «обычный» — тоже выбор). */
export function compact<T extends object>(value: T): T {
  const out = {} as Record<string, unknown>
  for (const [k, v] of Object.entries(value)) if (v !== undefined && v !== '' && !(typeof v === 'number' && Number.isNaN(v))) out[k] = v
  return out as T
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label>{label}{children}</label>
}

/** Список из вариантов с пунктом «авто»: пустое значение — в макете поля нет. */
export function Choice<T extends string>({ label, value, options, onChange, auto = 'авто' }:
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

export function Num({ label, value, min, max, step = 1, unit, onChange }:
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

export function Text({ label, value, placeholder, onChange }: { label: string; value: string | undefined; placeholder: string; onChange: (v: string) => void }) {
  return <Field label={label}><input type="text" value={value ?? ''} placeholder={placeholder} onChange={e => onChange(e.target.value)} /></Field>
}

/** Текстовое поле, которое применяется по Enter или при выходе из поля: недописанная дата или число не даёт ошибку на каждом знаке. */
export function Commit({ label, value, placeholder, onChange }: { label: string; value: string | undefined; placeholder: string; onChange: (v: string) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const done = () => { if (draft !== null && draft !== (value ?? '')) onChange(draft.trim()); setDraft(null) }
  return (
    <Field label={label}>
      <input type="text" value={draft ?? value ?? ''} placeholder={placeholder} onChange={e => setDraft(e.target.value)} onBlur={done}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); done() } }} />
    </Field>
  )
}

export function Color({ label, value, onChange }: { label: string; value: string | undefined; onChange: (v: string | undefined) => void }) {
  return (
    <Field label={label}>
      <span className="cs-range">
        <input type="color" value={value && HEX.test(value) ? value : '#888888'} onChange={e => onChange(e.target.value)} />
        <button type="button" className="cs-auto" disabled={value === undefined} onClick={() => onChange(undefined)} title="Вернуть: авто">авто</button>
      </span>
    </Field>
  )
}

export function Flag({ label, value, onChange, title }: { label: string; value: boolean | undefined; onChange: (v: boolean) => void; title?: string }) {
  return <label className="cs-check" title={title}><input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} /> {label}</label>
}

export const FONT_OPTIONS = FONT_CHOICES.map(f => ({ value: f.value, label: f.label }))


// ---------- группы полей: одни и те же на графике и в конструкторе ----------

type Opt<T extends string> = { value: T; label: string }[]
export const LEGENDS: Opt<NonNullable<ChartStyle['legend']>> = [
  { value: 'bottom', label: 'Снизу' }, { value: 'top', label: 'Сверху' }, { value: 'right', label: 'Справа' }, { value: 'left', label: 'Слева' }, { value: 'hide', label: 'Скрыть' }]
export const GRIDS: Opt<NonNullable<ChartStyle['grid']>> = [
  { value: 'both', label: 'Горизонтальная и вертикальная' }, { value: 'h', label: 'Только горизонтальная' },
  { value: 'v', label: 'Только вертикальная' }, { value: 'none', label: 'Без сетки' }]
const ALIGNS: Opt<NonNullable<ChartStyle['title_align']>> = [{ value: 'left', label: 'Слева' }, { value: 'center', label: 'По центру' }, { value: 'right', label: 'Справа' }]
const TICKS: Opt<NonNullable<AxisStyle['ticks']>> = [{ value: 'out', label: 'Наружу' }, { value: 'in', label: 'Внутрь' }, { value: 'cross', label: 'Через ось' }, { value: 'none', label: 'Нет' }]
const UNITS: Opt<NonNullable<AxisStyle['units']>> = [{ value: 'thousands', label: 'Тысячи (×10³)' }, { value: 'millions', label: 'Миллионы (×10⁶)' }, { value: 'billions', label: 'Миллиарды (×10⁹)' }]
const PLACES: Opt<NonNullable<AxisStyle['title_place']>> = [{ value: 'end', label: 'У конца оси' }, { value: 'middle', label: 'Вдоль оси' }]
const LABEL_PLACES: Opt<NonNullable<Look['label_position']>> = [
  { value: 'top', label: 'Сверху' }, { value: 'bottom', label: 'Снизу' }, { value: 'left', label: 'Слева' }, { value: 'right', label: 'Справа' },
  { value: 'inside', label: 'Внутри' }, { value: 'center', label: 'По центру' }]
export const DATE_FORMATS = [{ value: 'dd.MM.yyyy', label: '31.12.2025' }, { value: 'MM.yyyy', label: '12.2025' }, { value: 'yyyy', label: '2025' }, { value: 'dd.MM', label: '31.12' }]
const BOLD = [{ value: 'b', label: 'Жирный' }, { value: 'n', label: 'Обычный' }]
const boolOf = (v: string | undefined) => (v === undefined ? undefined : v === 'b')

interface Setter<T> { value: T; set: (patch: Partial<T>) => void }

/** Заголовок, текст, легенда, сетка, рамки и фоны графика. `title` — поле текста заголовка (в конструкторе оно в макете). */
const ANNOTATION_KINDS: { value: Annotation['kind']; label: string }[] = [
  { value: 'hline', label: 'Линия уровня (Y)' }, { value: 'vline', label: 'Вертикальная линия (X)' },
  { value: 'hband', label: 'Полоса по Y' }, { value: 'vband', label: 'Полоса по X' }, { value: 'text', label: 'Подпись' },
]
const NEEDS: Record<Annotation['kind'], (keyof Annotation)[]> = { hline: ['value'], vline: ['value'], hband: ['value', 'to'], vband: ['value', 'to'], text: ['x', 'y', 'text'] }
const complete = (a: Partial<Annotation>) => !!a.kind && NEEDS[a.kind].every(k => String(a[k] ?? '').trim() !== '')

/** Аннотации: линии уровня, полосы и подписи в координатах данных. Неполная строка живёт в панели и в график не попадает. */
function AnnotationFields({ value, set }: { value: Annotation[] | undefined; set: (v: Annotation[] | undefined) => void }) {
  const [rows, setRows] = useState<Partial<Annotation>[]>(value ?? [])
  const sent = useRef(JSON.stringify(value ?? []))
  useEffect(() => {      // изменили снаружи (шаблон, «Сбросить всё»): строки берутся из графика
    if (JSON.stringify(value ?? []) !== sent.current) { sent.current = JSON.stringify(value ?? []); setRows(value ?? []) }
  }, [value])
  const commit = (next: Partial<Annotation>[]) => {
    setRows(next)
    const done = next.filter(complete) as Annotation[]
    sent.current = JSON.stringify(done)
    set(done.length ? done : undefined)
  }
  const edit = (i: number, patch: Partial<Annotation>) => commit(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <fieldset>
      <legend>Аннотации</legend>
      {rows.map((a, i) => (
        <div key={i} className="cs-annotation">
          <Choice label="Вид" value={a.kind} options={ANNOTATION_KINDS} auto="— выберите —" onChange={v => edit(i, { kind: v })} />
          {a.kind && <>
            {(a.kind === 'hline' || a.kind === 'vline' || a.kind === 'hband' || a.kind === 'vband') && (
              <Text label={a.kind.endsWith('band') ? 'От' : 'Значение'} value={a.value} placeholder={a.kind[0] === 'v' ? 'число или дд.мм.гггг' : 'число'} onChange={v => edit(i, { value: v })} />)}
            {(a.kind === 'hband' || a.kind === 'vband') && <Text label="До" value={a.to} placeholder={a.kind === 'vband' ? 'число или дд.мм.гггг' : 'число'} onChange={v => edit(i, { to: v })} />}
            {a.kind === 'text' && <div className="cs-row">
              <Text label="X" value={a.x} placeholder="число или дата" onChange={v => edit(i, { x: v })} />
              <Text label="Y" value={a.y} placeholder="число" onChange={v => edit(i, { y: v })} />
            </div>}
            <Text label="Текст" value={a.text} placeholder={a.kind === 'text' ? 'обязательно' : 'нет'} onChange={v => edit(i, { text: v })} />
            <div className="cs-row">
              <Color label="Цвет" value={a.color} onChange={v => edit(i, { color: v })} />
              {a.kind !== 'text' && !a.kind.endsWith('band') && <Num label="Толщина" value={a.width} min={0.5} max={8} step={0.5} onChange={v => edit(i, { width: v })} />}
              {a.kind === 'text' && <Num label="Размер" value={a.size} min={6} max={36} onChange={v => edit(i, { size: v })} />}
            </div>
          </>}
          <div className="cs-actions"><button type="button" onClick={() => commit(rows.filter((_, j) => j !== i))}>Удалить</button></div>
        </div>))}
      <div className="cs-actions"><button type="button" disabled={rows.length >= 30} onClick={() => setRows([...rows, {}])}>Добавить аннотацию</button></div>
      <p className="cs-hint">Значения — в единицах осей: основная ось Y и ось X (число или дата дд.мм.гггг). Строка попадает на график, когда заполнена.</p>
    </fieldset>
  )
}

export function ChartStyleFields({ value: st, set, title }: Setter<ChartStyle> & { title?: ReactNode }) {
  return (
    <>
      <fieldset>
        <legend>Заголовок</legend>
        {title}
        <Text label="Подзаголовок" value={st.subtitle} placeholder="нет" onChange={v => set({ subtitle: v || undefined })} />
        <Choice label="Шрифт" value={st.title_font} options={FONT_OPTIONS} onChange={v => set({ title_font: v })} auto="как у графика" />
        <div className="cs-row">
          <Num label="Размер" value={st.title_size} min={6} max={48} onChange={v => set({ title_size: v })} />
          <Choice label="Начертание" value={st.title_bold === undefined ? undefined : st.title_bold ? 'b' : 'n'} options={BOLD} onChange={v => set({ title_bold: boolOf(v) })} />
        </div>
        <Choice label="Выравнивание" value={st.title_align} options={ALIGNS} onChange={v => set({ title_align: v })} />
        <Color label="Цвет" value={st.title_color} onChange={v => set({ title_color: v })} />
        {st.subtitle && <Num label="Размер подзаголовка" value={st.subtitle_size} min={6} max={48} onChange={v => set({ subtitle_size: v })} />}
      </fieldset>
      <fieldset>
        <legend>Текст графика</legend>
        <Choice label="Шрифт" value={st.font} options={FONT_OPTIONS} onChange={v => set({ font: v })} />
        <Color label="Цвет текста" value={st.text_color} onChange={v => set({ text_color: v })} />
        <p className="cs-hint">Шрифт и цвет действуют на заголовок, оси и легенду, если для них не заданы свои.</p>
      </fieldset>
      <fieldset>
        <legend>Легенда</legend>
        <Choice label="Положение" value={st.legend} options={LEGENDS} onChange={v => set({ legend: v })} auto="авто (снизу)" />
        <Choice label="Шрифт" value={st.legend_font} options={FONT_OPTIONS} onChange={v => set({ legend_font: v })} auto="как у графика" />
        <div className="cs-row">
          <Num label="Размер" value={st.legend_size} min={5} max={30} onChange={v => set({ legend_size: v })} />
          <Num label="Колонок" value={st.legend_columns} min={1} max={12} onChange={v => set({ legend_columns: v })} />
        </div>
        <Flag label="Рамка легенды" value={st.legend_border} onChange={v => set({ legend_border: v || undefined })} />
        <Color label="Фон легенды" value={st.legend_background} onChange={v => set({ legend_background: v })} />
      </fieldset>
      <fieldset>
        <legend>Сетка</legend>
        <Choice label="Сетка" value={st.grid} options={GRIDS} onChange={v => set({ grid: v })} />
        <Color label="Цвет сетки" value={st.grid_color} onChange={v => set({ grid_color: v })} />
        <div className="cs-row">
          <Num label="Толщина" value={st.grid_width} min={0.2} max={4} step={0.1} onChange={v => set({ grid_width: v })} />
          <Choice label="Штрих" value={st.grid_dash} options={LINE_STYLES} onChange={v => set({ grid_dash: v })} />
        </div>
        <Choice label="Дополнительная сетка" value={st.minor_grid} options={[{ value: 'show', label: 'Показать' }, { value: 'hide', label: 'Скрыть' }]} onChange={v => set({ minor_grid: v })} />
        {st.minor_grid === 'show' && <>
          <Color label="Цвет" value={st.minor_grid_color} onChange={v => set({ minor_grid_color: v })} />
          <div className="cs-row">
            <Num label="Толщина" value={st.minor_grid_width} min={0.2} max={4} step={0.1} onChange={v => set({ minor_grid_width: v })} />
            <Choice label="Штрих" value={st.minor_grid_dash} options={LINE_STYLES} onChange={v => set({ minor_grid_dash: v })} />
          </div>
          <p className="cs-hint">Дополнительная сетка идёт по дополнительным делениям оси (шаг задаётся у оси).</p>
        </>}
      </fieldset>
      <fieldset>
        <legend>Фон и рамки</legend>
        <Color label="Фон графика" value={st.background} onChange={v => set({ background: v })} />
        <div className="cs-row">
          <Color label="Рамка графика" value={st.border_color} onChange={v => set({ border_color: v })} />
          <Num label="Толщина" value={st.border_width} min={0.2} max={6} step={0.2} onChange={v => set({ border_width: v })} />
        </div>
        <Color label="Фон области построения" value={st.plot_background} onChange={v => set({ plot_background: v })} />
        <div className="cs-row">
          <Color label="Рамка области" value={st.plot_border_color} onChange={v => set({ plot_border_color: v })} />
          <Num label="Толщина" value={st.plot_border_width} min={0.2} max={6} step={0.2} onChange={v => set({ plot_border_width: v })} />
        </div>
      </fieldset>
      <AnnotationFields value={st.annotations} set={v => set({ annotations: v })} />
    </>
  )
}

/** Оформление оси: линия, деления, подписи, единицы, название. Границы и шаг — у вызывающего (в конструкторе — свои поля). */
export function AxisStyleFields({ value: f, set, time }: Setter<Omit<AxisStyle, 'minor_step' | 'cross'> & { color?: string }> & { time?: boolean }) {
  return (
    <>
      <fieldset>
        <legend>Линия и деления</legend>
        <Color label="Цвет оси и подписей" value={f.color} onChange={v => set({ color: v })} />
        <Flag label="Показывать линию оси" value={f.line} onChange={v => set({ line: v })} />
        <div className="cs-row">
          <Color label="Цвет линии" value={f.line_color} onChange={v => set({ line_color: v })} />
          <Num label="Толщина" value={f.line_width} min={0.2} max={6} step={0.2} onChange={v => set({ line_width: v })} />
        </div>
        <div className="cs-row">
          <Choice label="Основные деления" value={f.ticks} options={TICKS} onChange={v => set({ ticks: v })} />
          <Choice label="Дополнительные" value={f.minor_ticks} options={TICKS} onChange={v => set({ minor_ticks: v })} />
        </div>
      </fieldset>
      <fieldset>
        <legend>Подписи делений</legend>
        {time
          ? <Choice label="Формат даты" value={f.date_format} options={DATE_FORMATS} onChange={v => set({ date_format: v })} />
          : <div className="cs-row">
              <Num label="Знаков после запятой" value={f.decimals} min={0} max={8} onChange={v => set({ decimals: v })} />
              <Choice label="Единицы" value={f.units} options={UNITS} onChange={v => set({ units: v })} auto="как есть" />
            </div>}
        <Choice label="Шрифт" value={f.font} options={FONT_OPTIONS} onChange={v => set({ font: v })} auto="как у графика" />
        <div className="cs-row">
          <Num label="Размер" value={f.tick_size} min={5} max={30} onChange={v => set({ tick_size: v })} />
          <Num label="Поворот, °" value={f.label_rotate} min={-90} max={90} onChange={v => set({ label_rotate: v })} />
        </div>
        <div className="cs-row">
          <Flag label="Жирный" value={f.tick_bold} onChange={v => set({ tick_bold: v || undefined })} />
          <Flag label="Курсив" value={f.tick_italic} onChange={v => set({ tick_italic: v || undefined })} />
        </div>
      </fieldset>
      <fieldset>
        <legend>Название оси</legend>
        <div className="cs-row">
          <Num label="Размер" value={f.title_size} min={5} max={30} onChange={v => set({ title_size: v })} />
          <Choice label="Положение" value={f.title_place} options={PLACES} onChange={v => set({ title_place: v })} />
        </div>
        <div className="cs-row">
          <Flag label="Жирный" value={f.title_bold} onChange={v => set({ title_bold: v || undefined })} />
          <Flag label="Курсив" value={f.title_italic} onChange={v => set({ title_italic: v || undefined })} />
        </div>
      </fieldset>
    </>
  )
}

/** Дополнения к виду ряда (модель v2): граница маркера, полый маркер, подписи данных, имя в легенде. */
const HATCHES: { value: NonNullable<Look['hatch']>; label: string }[] = [
  { value: 'diag', label: 'Диагональная ///' }, { value: 'back', label: 'Обратная \\\\' }, { value: 'cross', label: 'Косая сетка' },
  { value: 'grid', label: 'Клетка' }, { value: 'dots', label: 'Точки' }, { value: 'horizontal', label: 'Горизонтальная' }, { value: 'vertical', label: 'Вертикальная' },
]

const TRENDS: { value: NonNullable<Look['trend']>; label: string }[] = [
  { value: 'linear', label: 'Линейная' }, { value: 'poly', label: 'Полиномиальная' }, { value: 'log', label: 'Логарифмическая' },
  { value: 'power', label: 'Степенная' }, { value: 'exp', label: 'Экспоненциальная' }, { value: 'moving', label: 'Скользящее среднее' },
]

export function SeriesExtraFields({ value: look, set, marker, labels, trend = false, hatch = false }: Setter<Look> & { marker: boolean; labels: boolean; trend?: boolean; hatch?: boolean }) {
  return (
    <>
      {marker && <fieldset>
        <legend>Маркер: граница</legend>
        <Flag label="Полый маркер" value={look.hollow} onChange={v => set({ hollow: v })} />
        <div className="cs-row">
          <Color label="Цвет границы" value={look.marker_border} onChange={v => set({ marker_border: v })} />
          <Num label="Толщина" value={look.marker_border_width} min={0} max={6} step={0.2} onChange={v => set({ marker_border_width: v })} />
        </div>
      </fieldset>}
      {labels && <fieldset>
        <legend>Подписи данных</legend>
        <Flag label="Показывать подписи значений" value={look.valueLabels} onChange={v => set({ valueLabels: v })} />
        {look.valueLabels && <>
          <Choice label="Положение" value={look.label_position} options={LABEL_PLACES} onChange={v => set({ label_position: v })} />
          <div className="cs-row">
            <Num label="Знаков" value={look.label_decimals} min={0} max={8} onChange={v => set({ label_decimals: v })} />
            <Num label="Размер" value={look.label_size} min={5} max={30} onChange={v => set({ label_size: v })} />
          </div>
        </>}
      </fieldset>}
      {hatch && <fieldset>
        <legend>Штриховка</legend>
        <Choice label="Рисунок" value={look.hatch} options={HATCHES} auto="нет" onChange={v => set({ hatch: v })} />
        {look.hatch && <Color label="Цвет штриха" value={look.hatch_color} onChange={v => set({ hatch_color: v })} />}
        <p className="cs-hint">Столбцы различаются рисунком, а не только цветом: график читается на чёрно-белой печати.</p>
      </fieldset>}
      {trend && <fieldset>
        <legend>Погрешность</legend>
        <Choice label="Задание" value={look.err_mode} options={[{ value: 'percent', label: 'В процентах от значения' }, { value: 'abs', label: 'Абсолютное значение' }]}
          auto="в процентах" onChange={v => set({ err_mode: v })} />
        <Num label={look.err_mode === 'abs' ? 'Величина ±' : 'Величина ±, %'} value={look.err_value} min={0} max={1e9} step={look.err_mode === 'abs' ? 1 : 0.5}
          onChange={v => set({ err_value: v })} />
        {!!look.err_value && <Choice label="Вид" value={look.err_style} options={[{ value: 'bars', label: 'Усы у каждой точки' }, { value: 'band', label: 'Две граничные линии' }]}
          auto="усы" onChange={v => set({ err_style: v })} />}
        <p className="cs-hint">Интервал задаёт инженер вручную: от каждой точки откладывается указанная величина вверх и вниз.</p>
      </fieldset>}
      {trend && <fieldset>
        <legend>Линия тренда</legend>
        <Choice label="Вид" value={look.trend} options={TRENDS} auto="нет" onChange={v => set({ trend: v })} />
        {look.trend === 'poly' && <Num label="Степень" value={look.trend_order} min={2} max={6} onChange={v => set({ trend_order: v })} />}
        {look.trend === 'moving' && <Num label="Период, точек" value={look.trend_period} min={2} max={60} onChange={v => set({ trend_period: v })} />}
        {look.trend && <>
          <div className="cs-row">
            <Color label="Цвет" value={look.trend_color} onChange={v => set({ trend_color: v })} />
            <Num label="Толщина" value={look.trend_width} min={0.5} max={12} step={0.5} onChange={v => set({ trend_width: v })} />
          </div>
          <Flag label="Уравнение и R² в подписи" value={look.trend_label} onChange={v => set({ trend_label: v })} />
          <p className="cs-hint">R² считается по самому ряду. Логарифм требует x &gt; 0, степень и экспонента — x и y &gt; 0.</p>
        </>}
      </fieldset>}
      <fieldset>
        <legend>Легенда</legend>
        <Text label="Имя в легенде" value={look.legend_name} placeholder="как у ряда" onChange={v => set({ legend_name: v || undefined })} />
      </fieldset>
    </>
  )
}

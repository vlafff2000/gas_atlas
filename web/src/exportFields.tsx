// Общие поля выгрузки: один набор блоков для вкладок экспорта и для «Любой график» (одинаковый вид и подписи).
// Поля читаются из ``form`` и пишутся через ``set``; пустое значение — «как задал раздел».
import { useEffect, useState, type ReactNode } from 'react'
import type { ExportChoices, Form } from './api_projects'
import { HEIGHT_MM, WIDTH_MM } from './ResizableFrame'

export type Opt = [unknown, string]
export interface FieldProps { form: Form; set: (field: string, value: unknown) => void; choices?: ExportChoices }
// Популярные форматы: ширина × высота, мм. Без высоты — подбирается по ширине и легенде.
export const SIZES: [string, string, number | null][] = [
  ['auto', 'Авто (220 мм по ширине)', null],
  ['a4-width', 'A4: ширина поля 170 × 110', 110],
  ['a4-half', 'A4: пол-листа 170 × 125', 125],
  ['a4-page', 'A4 книжный: весь лист 190 × 270', 270],
  ['a4-land', 'A4 альбомный 270 × 180', 180],
  ['16x9', 'Слайд 16:9, 254 × 143', 143],
  ['4x3', 'Слайд 4:3, 240 × 180', 180],
  ['column', 'Колонка статьи 85 × 65', 65],
  ['square', 'Квадрат 150 × 150', 150],
]
export const SIZE_WIDTH: Record<string, number> = { auto: 220, 'a4-width': 170, 'a4-half': 170, 'a4-page': 190, 'a4-land': 270, '16x9': 254, '4x3': 240, column: 85, square: 150 }

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="param-section" aria-label={title}>
      <span className="param-title" aria-hidden="true">{title}</span>
      <div className="param-fields">{children}</div>
    </fieldset>
  )
}

export function Check({ form, set, field, label, def, disabled }: FieldProps & { field: string; label: string; def: boolean; disabled?: boolean }) {
  const value = (form[field] as boolean | undefined) ?? def
  return (
    <label className="toggle">
      <input type="checkbox" checked={value} disabled={disabled} onChange={e => set(field, e.target.checked)} />
      <span>{label}</span>
    </label>
  )
}

export function Select({ form, set, field, label, def, options }: FieldProps & { field: string; label: string; def: unknown; options: Opt[] }) {
  const value = form[field] === undefined ? def : form[field]
  const index = Math.max(0, options.findIndex(([v]) => JSON.stringify(v) === JSON.stringify(value)))
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select value={index} onChange={e => set(field, options[Number(e.target.value)][0])}>
        {options.map(([, l], i) => <option key={i} value={i}>{l}</option>)}
      </select>
    </label>
  )
}

export function Num({ form, set, field, label, def, min, max, step = 1 }:
  FieldProps & { field: string; label: string; def: number; min: number; max: number; step?: number }) {
  const value = (form[field] as number | undefined) ?? def
  const [text, setText] = useState(String(value))
  useEffect(() => setText(String(value)), [value])
  const n = Number(text)
  const ok = text.trim() !== '' && n >= min && n <= max
  return (
    <label className={'field number' + (ok ? '' : ' invalid')}>
      <span className="field-label">{label}</span>
      <input type="number" min={min} max={max} step={step} value={text}
        onChange={e => { setText(e.target.value); const v = Number(e.target.value); if (e.target.value.trim() !== '' && v >= min && v <= max) set(field, v) }} />
      {!ok && <span className="field-error">от {min} до {max}</span>}
    </label>
  )
}

export function Text({ form, set, field, label, def, wide }: FieldProps & { field: string; label: string; def: string; wide?: boolean }) {
  return (
    <label className={'field' + (wide ? ' wide' : '')}>
      <span className="field-label">{label}</span>
      <input value={(form[field] as string | undefined) ?? def} maxLength={500} onChange={e => set(field, e.target.value)} />
    </label>
  )
}

/** Формат листа: готовые размеры, ширина и высота в мм (пустая высота — подбирается автоматически). */
export function SizePick({ form, set, choices }: FieldProps) {
  const width = (form.width as number | undefined) ?? 220
  const height = form.height as number | undefined
  const preset = SIZES.find(([id, , h]) => (h ?? undefined) === height && SIZE_WIDTH[id] === width)?.[0] ?? 'custom'
  const [text, setText] = useState(height === undefined ? '' : String(height))
  useEffect(() => setText(height === undefined ? '' : String(height)), [height])
  const n = Number(text)
  const bad = text.trim() !== '' && !(n >= HEIGHT_MM[0] && n <= HEIGHT_MM[1])
  return (
    <>
      <label className="field">
        <span className="field-label">Формат графика</span>
        <select value={preset} onChange={e => {
          const [, , h] = SIZES.find(([id]) => id === e.target.value) ?? ['', '', null]
          if (e.target.value === 'custom') return
          set('width', SIZE_WIDTH[e.target.value])
          set('height', h ?? undefined)
        }}>
          {SIZES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          <option value="custom">Свой размер</option>
        </select>
      </label>
      <Num form={form} set={set} choices={choices} field="width" label="Ширина, мм" def={220} min={WIDTH_MM[0]} max={WIDTH_MM[1]} />
      <label className={'field number' + (bad ? ' invalid' : '')} title="Пусто — высота подбирается по ширине и легенде">
        <span className="field-label">Высота, мм</span>
        <input type="number" min={HEIGHT_MM[0]} max={HEIGHT_MM[1]} placeholder="авто" value={text}
          onChange={e => { setText(e.target.value); const v = Number(e.target.value)
            if (e.target.value.trim() === '') set('height', undefined)
            else if (v >= HEIGHT_MM[0] && v <= HEIGHT_MM[1]) set('height', v) }} />
        {bad && <span className="field-error">от {HEIGHT_MM[0]} до {HEIGHT_MM[1]}</span>}
      </label>
    </>
  )
}


import { useEffect, useState } from 'react'
import type { Series } from './api'
import { LINE_STYLES, MARKER_SHAPES, seriesLookKey, type Look, type LineStyleName, type MarkerShape } from './chartStyle'

interface Props {
  title: string
  series: Series[]
  colorOf: (s: Series) => string
  looks: Record<string, Look>
  onChange: (next: Record<string, Look>) => void
  onClose: () => void
}

const KIND: Record<Series['kind'], string> = { line: 'линия', points: 'точки', bar: 'столбцы', box: 'ящики' }
export const HEX = /^#[0-9a-f]{6}$/i


type LookSeries = Pick<Series, 'kind' | 'dash' | 'dashed' | 'width' | 'markers' | 'symbol' | 'opacity'> & { fill?: boolean }

/** Цвет с кнопкой «авто»: пока цвет не задан вручную, он берётся из палитры или модуля. */
function ColorField({ label, value, shown, onChange }: { label: string; value: string | undefined; shown: string; onChange: (c: string | undefined) => void }) {
  return (
    <label>{label}
      <span className="cs-range">
        <input type="color" value={HEX.test(value ?? shown) ? (value ?? shown) : '#2a78d6'} onChange={e => onChange(e.target.value)} />
        <button type="button" className="cs-auto" disabled={value === undefined} onClick={() => onChange(undefined)} title="Вернуть цвет по умолчанию">авто</button>
      </span>
    </label>
  )
}

/** Поля вида ряда: линия (цвет, толщина, стиль), маркеры (форма, размер, цвет), прозрачность. Общие для окна «Настройка» графиков и конструктора. */
export function SeriesLookFields({ s, color, look, onChange }: { s: LookSeries; color: string; look: Look; onChange: (patch: Partial<Look>) => void }) {
  const baseDash: LineStyleName = LINE_STYLES.some(d => d.value === s.dash) ? s.dash as LineStyleName : s.dashed ? 'dash' : 'solid'
  const hasLine = s.kind === 'line'
  const hasMarker = (s.kind === 'line' && !s.fill) || s.kind === 'points'      // у области отметок нет, у столбцов нет ни линии, ни отметок
  const markerColor = look.markerColor ?? color
  const marker = look.marker ?? !!s.markers
  const size = look.size ?? (s.kind === 'points' ? 9 : 7)
  const shape: MarkerShape = look.shape ?? (s.symbol as MarkerShape)
  const opacity = look.opacity ?? (s.fill ? 0.6 : s.opacity ?? 1)
  const setLook = onChange
  return (
    <>
      {hasLine && <fieldset>
        <legend>Линия</legend>
        <label className="cs-check"><input type="checkbox" checked={look.line !== false} onChange={e => setLook({ line: e.target.checked })} /> Показывать линию</label>
        <ColorField label="Цвет" value={look.color} shown={color} onChange={c => setLook({ color: c })} />
        <label>Толщина <span className="cs-range"><input type="range" min={0.5} max={6} step={0.5} value={look.width ?? (s.width || 2)} onChange={e => setLook({ width: Number(e.target.value) })} /><output>{look.width ?? (s.width || 2)} px</output></span></label>
        <label>Стиль
          <select value={look.dash ?? baseDash} onChange={e => setLook({ dash: e.target.value as LineStyleName })}>
            {LINE_STYLES.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </label>
      </fieldset>}
      {!hasLine && !hasMarker && <fieldset>
        <legend>Цвет</legend>
        <ColorField label="Цвет" value={look.color} shown={color} onChange={c => setLook({ color: c })} />
      </fieldset>}
      {hasMarker && <fieldset>
        <legend>Маркеры</legend>
        <label className="cs-check"><input type="checkbox" checked={marker} onChange={e => setLook({ marker: e.target.checked })} /> Показывать маркеры</label>
        <label>Форма
          <select value={shape} onChange={e => setLook({ shape: e.target.value as MarkerShape })}>
            {MARKER_SHAPES.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </label>
        <label>Размер <span className="cs-range"><input type="range" min={2} max={16} step={1} value={size} onChange={e => setLook({ size: Number(e.target.value) })} /><output>{size}</output></span></label>
        <ColorField label="Цвет маркеров" value={s.kind === 'points' ? look.color : look.markerColor} shown={markerColor}
          onChange={c => setLook(s.kind === 'points' ? { color: c } : { markerColor: c })} />
      </fieldset>}
      <fieldset>
        <legend>Прозрачность</legend>
        <label>{s.fill ? 'Непрозрачность заливки' : 'Непрозрачность'} <span className="cs-range"><input type="range" min={0.1} max={1} step={0.05} value={opacity} onChange={e => setLook({ opacity: Number(e.target.value) })} /><output>{Math.round(opacity * 100)} %</output></span></label>
      </fieldset>
    </>
  )
}
/** Окно «Настройка» как «Формат ряда» в Excel: слева ряды, справа их вид. Меняет график сразу; закрывается крестиком или Esc. */
export function ChartSettings({ title, series, colorOf, looks, onChange, onClose }: Props) {
  const [picked, setPicked] = useState(0)
  const index = Math.min(picked, Math.max(0, series.length - 1))
  const s = series[index]

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const setLook = (patch: Partial<Look>) => {
    const k = seriesLookKey(s)
    onChange({ ...looks, [k]: { ...looks[k], ...patch } })
  }
  const resetSeries = () => {
    const next = { ...looks }
    delete next[seriesLookKey(s)]
    onChange(next)
  }

  const look: Look = looks[seriesLookKey(s)] ?? {}

  return (
    <div className="chart-settings" role="dialog" aria-label={`Настройка графика: ${title}`}>
      <header>
        <b>Настройка графика</b>
        <span className="cs-title" title={title}>{title}</span>
        <button type="button" className="cs-close" onClick={onClose} aria-label="Закрыть настройку">×</button>
      </header>
      <div className="cs-body">
        <ul className="cs-list">
          {series.map((item, i) => (
            <li key={i}>
              <button type="button" aria-pressed={i === index} onClick={() => setPicked(i)} title={item.name}>
                <i style={{ background: colorOf(item) }} />
                <span>{item.name}</span>
              </button>
            </li>
          ))}
        </ul>
        {s && <div className="cs-editor">
          <h3>{s.name} <small>{KIND[s.kind]}</small></h3>
          <SeriesLookFields s={s} color={colorOf(s)} look={look} onChange={setLook} />
          <div className="cs-actions">
            <button type="button" onClick={resetSeries} disabled={!looks[seriesLookKey(s)]}>Сбросить ряд</button>
            <button type="button" onClick={() => onChange({})} disabled={Object.keys(looks).length === 0}>Сбросить все</button>
          </div>
        </div>}
      </div>
    </div>
  )
}

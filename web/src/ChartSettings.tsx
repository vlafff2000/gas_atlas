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
const HEX = /^#[0-9a-f]{6}$/i

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
  const color = colorOf(s)
  const baseDash: LineStyleName = LINE_STYLES.some(d => d.value === s.dash) ? s.dash as LineStyleName : s.dashed ? 'dash' : 'solid'
  const hasLine = s.kind === 'line'
  const hasMarker = s.kind === 'line' || s.kind === 'points'
  const markerColor = look.markerColor ?? color
  const marker = look.marker ?? !!s.markers
  const size = look.size ?? (s.kind === 'points' ? 9 : 7)
  const shape: MarkerShape = look.shape ?? (s.symbol as MarkerShape)

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
          {hasLine && <fieldset>
            <legend>Линия</legend>
            <label className="cs-check"><input type="checkbox" checked={look.line !== false} onChange={e => setLook({ line: e.target.checked })} /> Показывать линию</label>
            <label>Цвет <input type="color" value={HEX.test(color) ? color : '#2a78d6'} onChange={e => setLook({ color: e.target.value })} /></label>
            <label>Толщина <span className="cs-range"><input type="range" min={0.5} max={6} step={0.5} value={look.width ?? (s.width || 2)} onChange={e => setLook({ width: Number(e.target.value) })} /><output>{look.width ?? (s.width || 2)} px</output></span></label>
            <label>Стиль
              <select value={look.dash ?? baseDash} onChange={e => setLook({ dash: e.target.value as LineStyleName })}>
                {LINE_STYLES.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </label>
          </fieldset>}
          {!hasLine && !hasMarker && <fieldset>
            <legend>Цвет</legend>
            <label>Цвет <input type="color" value={HEX.test(color) ? color : '#2a78d6'} onChange={e => setLook({ color: e.target.value })} /></label>
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
            <label>Цвет маркеров <input type="color" value={HEX.test(markerColor) ? markerColor : '#2a78d6'}
              onChange={e => setLook(s.kind === 'points' ? { color: e.target.value } : { markerColor: e.target.value })} /></label>
          </fieldset>}
          <div className="cs-actions">
            <button type="button" onClick={resetSeries} disabled={!looks[seriesLookKey(s)]}>Сбросить ряд</button>
            <button type="button" onClick={() => onChange({})} disabled={Object.keys(looks).length === 0}>Сбросить все</button>
          </div>
        </div>}
      </div>
    </div>
  )
}

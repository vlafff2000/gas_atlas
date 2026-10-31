// Поля вида ряда (линия, маркеры, прозрачность): общие для панели «Формат» (FormatPane) и окон конструктора.
import type { Series } from './api'
import { LINE_STYLES, MARKER_SHAPES, type Look, type LineStyleName, type MarkerShape } from './chartStyle'

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
      {s.kind === 'bar' && <fieldset>
        <legend>Подписи</legend>
        <label className="cs-check"><input type="checkbox" checked={!!look.valueLabels} onChange={e => setLook({ valueLabels: e.target.checked })} /> Значения над столбцами</label>
      </fieldset>}
      <fieldset>
        <legend>Прозрачность</legend>
        <label>{s.fill ? 'Непрозрачность заливки' : 'Непрозрачность'} <span className="cs-range"><input type="range" min={0.1} max={1} step={0.05} value={opacity} onChange={e => setLook({ opacity: Number(e.target.value) })} /><output>{Math.round(opacity * 100)} %</output></span></label>
      </fieldset>
    </>
  )
}

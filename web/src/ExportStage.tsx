// Предпросмотр «как в файле»: рисунок, который уйдёт на выгрузку, и его сцена поверх. Щелчок выделяет элемент, двойной щелчок
// открывает его «Формат», заголовок, легенду, названия осей, подписи точек и тексты аннотаций можно перетащить мышью или
// подвинуть стрелками. Сдвиг пишется в оформление графика (ChartFormat.elements) в долях рисунка — файл рисует элемент там же.
// Под рисунком — находки проверки качества (atlas/chart_qc.py): подсказки, что читается плохо; ненужную инженер снимает.
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import type { ChartFormat } from './chartFormat'
import { dragTarget, elementAt, elementTitle, hidable, isShifted, movable, nudgeStep, shifted, unshifted, withFix, withPlace, withSkip, type Finding, type SceneElement } from './exportStage'

interface Props {
  image: string
  scene: SceneElement[]
  alt: string
  doc: ChartFormat
  onDoc: (doc: ChartFormat) => void
  /** Двойной щелчок по элементу: открыть его оформление. */
  onFormat?: (e: SceneElement) => void
  /** Имена из оформления, которых на рисунке нет (сдвиг не применён). */
  missing?: string[]
  /** Находки проверки качества рисунка; снятые инженером приходят с пометкой skipped. */
  checks?: Finding[]
  busy?: boolean
}

type Offset = [number, number]
const HISTORY = 50

const pct = (v: number) => `${v * 100}%`
const boxStyle = (e: SceneElement, [dx, dy]: Offset = [0, 0]): CSSProperties =>
  ({ left: pct(e.box[0] + dx), top: pct(e.box[1] + dy), width: pct(e.box[2] - e.box[0]), height: pct(e.box[3] - e.box[1]) })

/** Кусок рисунка под рамкой элемента: его показывают на новом месте, пока сервер рисует обновлённый файл. */
function ghostStyle(e: SceneElement, image: string, offset: Offset): CSSProperties {
  const w = Math.max(1e-6, e.box[2] - e.box[0]), h = Math.max(1e-6, e.box[3] - e.box[1])
  return { ...boxStyle(e, offset), backgroundImage: `url(${image})`, backgroundSize: `${100 / w}% ${100 / h}%`,
    backgroundPosition: `${w < 1 ? (e.box[0] / (1 - w)) * 100 : 0}% ${h < 1 ? (e.box[1] / (1 - h)) * 100 : 0}%` }
}

export function ExportStage({ image, scene, alt, doc, onDoc, onFormat, missing = [], checks = [], busy }: Props) {
  const frame = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [drag, setDrag] = useState<{ id: string; sx: number; sy: number; dx: number; dy: number } | null>(null)
  const [pending, setPending] = useState<Record<string, Offset>>({})      // сдвиги, которых ещё нет на рисунке
  const [past, setPast] = useState<ChartFormat[]>([])
  const [flagged, setFlagged] = useState<string[]>([])      // элементы находки, на которую навели в списке
  useEffect(() => setPending({}), [image, scene])      // пришёл ответ сервера: всё сдвинутое уже на рисунке

  const byId = new Map(scene.map(e => [e.id, e]))
  const chosen = selected ? byId.get(selected) ?? null : null
  const placed = Object.keys(doc.elements ?? {}).length
  const open = checks.filter(f => !f.skipped), skipped = checks.filter(f => f.skipped)
  const warns = open.filter(f => f.level === 'warn').length

  const change = (next: ChartFormat) => { setPast(p => [...p.slice(-HISTORY + 1), doc]); onDoc(next) }
  const undo = () => { const last = past[past.length - 1]; if (last) { setPast(p => p.slice(0, -1)); setPending({}); onDoc(last) } }
  const move = (id: string, dx: number, dy: number) => {
    change(shifted(doc, id, dx, dy))
    setPending(p => ({ ...p, [id]: [(p[id]?.[0] ?? 0) + dx, (p[id]?.[1] ?? 0) + dy] }))
  }

  const at = (ev: { clientX: number; clientY: number }) => {
    const r = frame.current?.getBoundingClientRect()
    if (!r || !r.width || !r.height) return null
    return { x: (ev.clientX - r.left) / r.width, y: (ev.clientY - r.top) / r.height, w: r.width, h: r.height }
  }
  const under = (ev: { clientX: number; clientY: number }) => {
    const p = at(ev)
    return p ? elementAt(scene, p.x, p.y, [4 / p.w, 4 / p.h]) : null
  }
  /** Сдвиг элемента на экране: перетаскивание + ещё не отрисованное; пункты легенды едут вместе с легендой. */
  const offsetOf = (e: SceneElement): Offset => {
    const id = e.kind === 'legend-item' ? e.id.split(':', 1)[0] : e.id
    const wait = pending[id] ?? [0, 0]
    return drag?.id === id ? [wait[0] + drag.dx, wait[1] + drag.dy] : wait
  }

  const down = (ev: PointerEvent<HTMLDivElement>) => {
    if (ev.button !== 0) return
    const e = under(ev)
    setSelected(e?.id ?? null)
    frame.current?.focus({ preventScroll: true })
    const target = dragTarget(scene, e)
    if (target) {
      ev.currentTarget.setPointerCapture(ev.pointerId)
      setDrag({ id: target.id, sx: ev.clientX, sy: ev.clientY, dx: 0, dy: 0 })
    }
  }
  const moveOver = (ev: PointerEvent<HTMLDivElement>) => {
    const p = at(ev)
    if (drag && p) setDrag({ ...drag, dx: (ev.clientX - drag.sx) / p.w, dy: (ev.clientY - drag.sy) / p.h })
    else setHover(under(ev)?.id ?? null)
  }
  const up = (ev: PointerEvent<HTMLDivElement>) => {
    const p = at(ev)
    if (drag && p && (Math.abs(drag.dx * p.w) > 2 || Math.abs(drag.dy * p.h) > 2)) {      // щелчок без движения — только выделение
      move(drag.id, drag.dx, drag.dy)
      setSelected(drag.id)      // потянули за пункт легенды — выделена легенда, которая уехала
    }
    setDrag(null)
  }
  const key = (ev: KeyboardEvent<HTMLDivElement>) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') { ev.preventDefault(); undo(); return }
    if (ev.key === 'Escape') { setSelected(null); setDrag(null); return }
    if (!chosen) return
    const arrows: Record<string, Offset> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }
    if (arrows[ev.key] && movable(chosen)) {
      ev.preventDefault()
      const step = nudgeStep(ev.shiftKey)
      move(chosen.id, arrows[ev.key][0] * step, arrows[ev.key][1] * step)
    } else if ((ev.key === 'Delete' || ev.key === 'Backspace') && hidable(chosen) && !chosen.hidden) {
      ev.preventDefault()
      change(withPlace(doc, chosen.id, { hide: true }))
    }
  }

  const hovered = hover && hover !== selected ? byId.get(hover) : null
  const ghosts = scene.filter(e => e.kind !== 'legend-item' && movable(e) && (offsetOf(e)[0] || offsetOf(e)[1]))
  const cursor = drag ? 'grabbing' : hover && dragTarget(scene, byId.get(hover)) ? 'grab' : hover && hover !== 'plot' ? 'pointer' : 'default'

  return (
    <div className="stage-wrap">
      <div className="stage-bar" aria-live="polite">
        {chosen
          ? <>
              <b>{elementTitle(chosen)}</b>
              {chosen.hidden && <span className="muted">скрыта</span>}
              {movable(chosen) && <span className="muted">тяните мышью или стрелками (с Shift крупнее)</span>}
              {chosen.kind === 'legend-item' && <span className="muted">потяните, чтобы передвинуть всю легенду</span>}
              {movable(chosen) && <button type="button" disabled={!isShifted(doc, chosen.id)} title="Вернуть элемент на автоматическое место"
                onClick={() => { change(unshifted(doc, chosen.id)); setPending(p => { const { [chosen.id]: _gone, ...rest } = p; return rest }) }}>Сбросить положение</button>}
              {hidable(chosen) && (chosen.hidden
                ? <button type="button" onClick={() => change(withPlace(doc, chosen.id, { hide: false }))}>Показать подпись</button>
                : <button type="button" title="Убрать с рисунка только эту подпись (клавиша Delete)" onClick={() => change(withPlace(doc, chosen.id, { hide: true }))}>Скрыть подпись</button>)}
              {onFormat && <button type="button" onClick={() => onFormat(chosen)}>Формат…</button>}
            </>
          : <span className="muted">Так график выглядит в файле. Щёлкните по элементу, чтобы выделить его; двойной щелчок открывает «Формат». Заголовок, легенду, названия
              осей, подписи точек и аннотаций можно перетащить.</span>}
        <span className="spacer" />
        {busy && <span className="pulse">Обновление…</span>}
        {open.length > 0
          ? <span className={'stage-count ' + (warns ? 'warn' : 'info')} title="Список — под рисунком">Замечаний: {open.length}</span>
          : <span className="stage-count ok" title="Проверка качества: наложений, выхода за край, мелкого шрифта и тесных делений не найдено">Замечаний нет{skipped.length > 0 ? ` (снято: ${skipped.length})` : ''}</span>}
        {placed > 0 && <span className="muted">Своё положение: {placed}</span>}
        <button type="button" className="quiet" disabled={!past.length} title="Отменить последнее изменение положения (Ctrl+Z)" onClick={undo}>Отменить</button>
        <button type="button" className="quiet" disabled={!placed} title="Вернуть все элементы на автоматические места и показать скрытые подписи"
          onClick={() => { const { elements: _all, ...rest } = doc; change(rest); setPending({}) }}>Сбросить все</button>
      </div>
      {missing.length > 0 && (
        <div className="note info">
          Своё положение задано для элементов, которых сейчас нет на графике: {missing.slice(0, 5).join(', ')}{missing.length > 5 ? ` и ещё ${missing.length - 5}` : ''}.{' '}
          <button type="button" className="link" onClick={() => change(missing.reduce((d, id) => withPlace(d, id, null), doc))}>Убрать эти записи</button>
        </div>
      )}
      <div className="stage" ref={frame} tabIndex={0} role="application" aria-label={`Предпросмотр файла: ${alt}`} style={{ cursor }}
        onPointerDown={down} onPointerMove={moveOver} onPointerUp={up} onPointerCancel={() => setDrag(null)} onPointerLeave={() => !drag && setHover(null)}
        onDoubleClick={ev => { const e = under(ev); if (e && onFormat) onFormat(e) }} onKeyDown={key}>
        <img src={image} alt={alt} draggable={false} />
        {ghosts.map(e => <div key={'veil' + e.id} className="stage-veil" style={boxStyle(e)} />)}
        {ghosts.map(e => <div key={'ghost' + e.id} className="stage-ghost" style={ghostStyle(e, image, offsetOf(e))} />)}
        {scene.filter(e => e.hidden).map(e => <div key={'hidden' + e.id} className="stage-box hidden" style={boxStyle(e)} title="Подпись скрыта" />)}
        {hovered && <div className={'stage-box hover' + (movable(hovered) ? ' movable' : '')} style={boxStyle(hovered, offsetOf(hovered))} />}
        {chosen && <div className={'stage-box selected' + (movable(chosen) ? ' movable' : '')} data-element={chosen.id} style={boxStyle(chosen, offsetOf(chosen))} />}
        {flagged.map(id => byId.get(id)).map(e => e && <div key={'flag' + e.id} className="stage-box flag" style={boxStyle(e, offsetOf(e))} />)}
      </div>
      {checks.length > 0 && (
        <div className="stage-checks" data-checks={open.length}>
          <div className="stage-checks-head">
            <b>Проверка качества</b>
            <span className="muted">Это подсказки: файл выгрузится и с ними. Наведите на строку, чтобы увидеть место на рисунке; ненужную подсказку можно снять.</span>
          </div>
          {open.length > 0 && <ul>{open.map(f => {
            const first = f.elements.find(id => byId.has(id))
            return (
              <li key={f.key} className={f.level} onMouseEnter={() => setFlagged(f.elements)} onMouseLeave={() => setFlagged([])}>
                <span className="mark" aria-hidden="true">{f.level === 'warn' ? '!' : 'i'}</span>
                <span className="text">{f.text}</span>
                {f.fix && <button type="button" className="fix" title="Изменить положение элементов; «Отменить» вернёт" onClick={() => { setFlagged([]); setPending({}); change(withFix(doc, f.fix!)) }}>{f.fix.text}</button>}
                {first && <button type="button" className="link" onClick={() => { setSelected(first); frame.current?.focus({ preventScroll: true }) }}>Выделить</button>}
                <button type="button" className="link" title="Убрать подсказку для этого графика; её можно вернуть" onClick={() => { setFlagged([]); change(withSkip(doc, f.key, true)) }}>Не показывать</button>
              </li>
            )
          })}</ul>}
          {skipped.length > 0 && (
            <details>
              <summary>Снято вами: {skipped.length}</summary>
              <ul>{skipped.map(f => (
                <li key={f.key} className="off">
                  <span className="text">{f.text}</span>
                  <button type="button" className="link" onClick={() => change(withSkip(doc, f.key, false))}>Вернуть</button>
                </li>
              ))}</ul>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

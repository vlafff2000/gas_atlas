// Рамка с ручками по краям и углам: график в предпросмотре экспорта растягивается мышью, как рисунок в Excel.
// Размер в миллиметрах — тот, что уйдёт в файл; пока рамку тянут, картинка просто растягивается, новая строится после отпускания.
import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'

export const WIDTH_MM = [80, 300] as const
export const HEIGHT_MM = [40, 400] as const
type Handle = 'e' | 'w' | 's' | 'se' | 'sw'
const HANDLES: Handle[] = ['e', 'w', 's', 'se', 'sw']
const clamp = (v: number, [lo, hi]: readonly [number, number]) => Math.min(hi, Math.max(lo, Math.round(v)))

interface Props {
  widthMm: number
  heightMm: number                       // фактическая высота (для автовысоты — по пропорциям картинки)
  onResize: (width: number, height: number) => void
  children: ReactNode
}

export function ResizableFrame({ widthMm, heightMm, onResize, children }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const [room, setRoom] = useState(900)
  const [draft, setDraft] = useState<{ w: number; h: number } | null>(null)
  useEffect(() => {
    const el = host.current
    if (!el) return
    const measure = () => setRoom(el.clientWidth)
    measure()
    const watch = new ResizeObserver(measure)
    watch.observe(el)
    return () => watch.disconnect()
  }, [])
  const scale = Math.min(4, Math.max(0.5, (room - 24) / WIDTH_MM[1]))      // пикселей на мм: максимальная ширина всегда помещается
  const w = draft?.w ?? widthMm, h = draft?.h ?? heightMm

  const start = (handle: Handle) => (e: PointerEvent<HTMLElement>) => {
    e.preventDefault()
    const target = e.currentTarget
    target.setPointerCapture(e.pointerId)
    const x0 = e.clientX, y0 = e.clientY, ratio = widthMm / heightMm
    const at = (ev: { clientX: number; clientY: number; shiftKey: boolean }) => {
      const dx = (ev.clientX - x0) / scale, dy = (ev.clientY - y0) / scale
      // Рамка по центру, поэтому боковая ручка двигает край вдвое медленнее ширины.
      let nw = handle.includes('e') ? widthMm + 2 * dx : handle.includes('w') ? widthMm - 2 * dx : widthMm
      let nh = handle.includes('s') ? heightMm + dy : heightMm
      if (ev.shiftKey && handle.length === 2) nh = nw / ratio                // Shift на углу — сохранить пропорции
      else if (ev.shiftKey && handle.length === 1) { if ('ew'.includes(handle)) nh = nw / ratio; else nw = nh * ratio }
      return { w: clamp(nw, WIDTH_MM), h: clamp(nh, HEIGHT_MM) }
    }
    const move = (ev: globalThis.PointerEvent) => setDraft(at(ev))
    const finish = (ev: globalThis.PointerEvent) => {
      target.removeEventListener('pointermove', move)
      target.removeEventListener('pointerup', finish)
      target.removeEventListener('pointercancel', finish)
      const next = at(ev)
      setDraft(null)
      if (next.w !== widthMm || next.h !== heightMm) onResize(next.w, next.h)
    }
    target.addEventListener('pointermove', move)
    target.addEventListener('pointerup', finish)
    target.addEventListener('pointercancel', finish)
  }

  return (
    <div className="resize-host" ref={host}>
      <div className={'resize-frame' + (draft ? ' dragging' : '')} style={{ width: w * scale, height: h * scale }}>
        {children}
        {HANDLES.map(handle => <span key={handle} className={'resize-handle ' + handle} onPointerDown={start(handle)} />)}
        <span className="resize-size" aria-live="polite">{w} × {h} мм</span>
      </div>
    </div>
  )
}

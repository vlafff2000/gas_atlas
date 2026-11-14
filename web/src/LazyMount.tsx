import { useEffect, useRef, useState, type ReactNode } from 'react'

/**
 * Отложенная отрисовка тяжёлого блока (график): пока блок далеко за экраном, на его месте пустая рамка той же высоты,
 * как только до него остаётся меньше `margin` пикселей, он монтируется и остаётся. Страница с десятками графиков
 * открывается и прокручивается без рывков. Перед печатью монтируется всё.
 */
export function LazyMount({ height = 520, margin = 900, children }: { height?: number; margin?: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [shown, setShown] = useState(typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    if (shown) return
    const show = () => setShown(true)
    const io = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) show() }, { rootMargin: `${margin}px 0px` })
    if (ref.current) io.observe(ref.current)
    window.addEventListener('beforeprint', show)
    return () => { io.disconnect(); window.removeEventListener('beforeprint', show) }
  }, [shown, margin])
  if (shown) return <>{children}</>
  return <div ref={ref} className="lazy-mount" style={{ minHeight: height }} aria-busy="true">График загрузится при прокрутке</div>
}

import { useEffect, useId, useRef, useState } from 'react'
import type { Chart, FigureData } from './api'
import type { Schematic } from './api_passport'
import { CopyButton, DownloadMenu } from './ChartView'
import { formatNumberUpTo } from './format'
import { GVK_COLOR } from './chartTheme'

/** Масштаб и сдвиг оси глубины: колесо — масштаб около курсора, перетаскивание — сдвиг, двойной щелчок — сброс (как у остальных графиков).
 *  Окно не выходит за полный диапазон ``full``; ``g`` — геометрия поля графика в единицах viewBox. */
function useDepthView(full: [number, number], g: { vbH: number; y0: number; h: number }) {
  const [view, setView] = useState<[number, number] | null>(null)
  const [el, setEl] = useState<SVGSVGElement | null>(null)
  const cur: [number, number] = view ?? full
  const live = useRef({ cur, full, g })
  live.current = { cur, full, g }
  useEffect(() => setView(null), [full[0], full[1]])
  useEffect(() => {
    if (!el) return
    const fit = (lo: number, span: number): [number, number] | null => {
      const [f0, f1] = live.current.full
      if (span >= f1 - f0 - 1e-9) return null
      const a = Math.max(f0, Math.min(lo, f1 - span))
      return [a, a + span]
    }
    const zAt = (clientY: number) => {
      const r = el.getBoundingClientRect(), { cur: c, g: geo } = live.current
      return c[0] + ((clientY - r.top) / r.height * geo.vbH - geo.y0) / geo.h * (c[1] - c[0])
    }
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      const { cur: c, full: f } = live.current
      const z = zAt(e.clientY), span = Math.min(Math.max((c[1] - c[0]) * (e.deltaY > 0 ? 1.25 : 0.8), (f[1] - f[0]) / 200), f[1] - f[0])
      setView(fit(z - (z - c[0]) / (c[1] - c[0]) * span, span))
    }
    let drag: { y: number; lo: number; span: number } | null = null
    const down = (e: PointerEvent) => { drag = { y: e.clientY, lo: live.current.cur[0], span: live.current.cur[1] - live.current.cur[0] }; el.setPointerCapture(e.pointerId) }
    const move = (e: PointerEvent) => {
      if (!drag) return
      const r = el.getBoundingClientRect(), geo = live.current.g
      setView(fit(drag.lo - (e.clientY - drag.y) / r.height * geo.vbH / geo.h * drag.span, drag.span))
    }
    const up = () => { drag = null }
    const reset = () => setView(null)
    el.addEventListener('wheel', wheel, { passive: false })
    el.addEventListener('pointerdown', down); el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up); el.addEventListener('dblclick', reset)
    return () => {
      el.removeEventListener('wheel', wheel); el.removeEventListener('pointerdown', down); el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); el.removeEventListener('dblclick', reset)
    }
  }, [el])
  return { ref: setEl, view: cur, zoomed: view !== null }
}

/** Забойная часть: рисуется по фигурам ядра (те же, что на странице PDF), глубина вниз. */
export function WellSchematic({ s }: { s: Schematic }) {
  const W = 720, H = 500, left = 46, scaleX = 68, cx = left + 3.2 * scaleX
  const zoom = useDepthView([s.top, s.bottom], { vbH: H, y0: 12, h: H - 24 })
  const clip = useId()
  if (!s.shapes || s.items.length === 0) return <p className="muted">{s.notes[0] ?? 'Нет конструкции.'}</p>
  const [v0, v1] = zoom.view
  const y = (m: number) => 12 + (m - v0) / (v1 - v0) * (H - 24)
  const x = (u: number) => cx + u * scaleX
  const step = [1, 2, 5, 10, 20, 50, 100].find(k => (v1 - v0) / k <= 7) ?? 100
  const ticks: number[] = []
  for (let t = Math.ceil(v0 / step) * step; t <= v1; t += step) ticks.push(t)
  return (
    <svg ref={zoom.ref} className="well-schematic zoomable" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Схема забойной части: эксплуатационная колонна, НКТ, фильтр, интервалы расширки, забой">
      <defs>
        <pattern id="pp-slots" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="#14b8a6" /><line x1="0" y1="0" x2="0" y2="6" stroke="#0f766e" strokeWidth="2" />
        </pattern>
        <pattern id="pp-cement" width="6" height="6" patternUnits="userSpaceOnUse">
          <rect width="6" height="6" fill="#d1d5db" /><path d="M0 0L6 6M6 0L0 6" stroke="#6b7280" strokeWidth=".8" />
        </pattern>
        <pattern id="pp-sand" width="5" height="5" patternUnits="userSpaceOnUse">
          <rect width="5" height="5" fill="#e8c987" /><circle cx="1.5" cy="1.5" r=".8" fill="#a8791f" /><circle cx="4" cy="4" r=".8" fill="#a8791f" />
        </pattern>
      </defs>
      <clipPath id={clip}><rect x="0" y="6" width={W} height={H - 12} /></clipPath>
      <rect x="0" y="0" width={W} height={H} rx="8" className="schematic-bg" />
      {ticks.map(t => (
        <g key={t}><line x1={left - 6} x2={left} y1={y(t)} y2={y(t)} className="schematic-tick" />
          <text x={left - 9} y={y(t)} className="schematic-tick-text" textAnchor="end" dominantBaseline="middle">{t}</text></g>))}
      <text x={left - 9} y="10" className="schematic-tick-text" textAnchor="end">м</text>
      <g clipPath={`url(#${clip})`}>
      {s.shapes.map((f, i) => f.t === 'poly'
        ? <polyline key={i} points={f.pts!.map(([u, m]) => `${x(u)},${y(m)}`).join(' ')} fill="none" stroke={f.stroke} strokeWidth={f.width} strokeLinejoin="miter" />
        : f.t === 'rect'
        ? <rect key={i} x={x(f.x0)} y={y(f.y0)} width={(f.x1 - f.x0) * scaleX} height={Math.max(y(f.y1) - y(f.y0), 1)}
                fill={f.pattern === 'slots' ? 'url(#pp-slots)' : f.pattern === 'sand' ? 'url(#pp-sand)' : f.pattern === 'cement' ? 'url(#pp-cement)' : f.fill}>
            <title>{f.name}</title></rect>
        : <line key={i} x1={x(f.x0)} x2={x(f.x1)} y1={y(f.y0)} y2={y(f.y1)} stroke={f.stroke} strokeWidth={f.width} />)}
      {(s.labels ?? []).map((l, i) => (
        <g key={i}>
          <polyline points={`${x(1.15)},${y(l.y)} ${x(2.2)},${y(l.y)} ${x(2.4)},${y(l.at)} ${x(2.6)},${y(l.at)}`}
                    fill="none" stroke={l.color} strokeWidth=".8" />
          <text x={x(2.65)} y={y(l.at)} fill={l.color} className="schematic-label" dominantBaseline="middle">{l.text}</text>
        </g>))}
      </g>
    </svg>
  )
}

const PACK_COLORS = ['#2a6f97', '#3a9d5d', '#7b4fa3', '#e0a100', '#2b9aa0', '#8c5a3c', '#5b6c8f', '#a3a33a']
const GRAY = '#b8bec6'
const ru = (x: number, d = 1) => formatNumberUpTo(x, d)

/** Планшет ГИС по глубине: слева перфорация, дальше трек на сезон — полосы интервалов длиной по Кг (серые — Кг не выше порога),
 *  линия ГВК пачки и подпись hг эф. Глубины — метры от стола, ось вниз. */
export function WellPlanshet({ d }: { d: Extract<FigureData, { kind: 'planshet' }>['data'] }) {
  const AXIS = 50, PERF = 24, TW = 170, PAD = 12, HEAD = 56, H = 520
  const packs = [...new Set(d.tracks.flatMap(t => t.bars.map(b => b.pack)))]
  const color = (p: string) => PACK_COLORS[Math.max(packs.indexOf(p), 0) % PACK_COLORS.length]
  const zoom = useDepthView([d.top, d.bottom], { vbH: HEAD + H + 12, y0: HEAD, h: H })
  const clip = useId()
  const [v0, v1] = zoom.view
  const y = (m: number) => HEAD + (m - v0) / (v1 - v0) * H
  const abs = d.axis === 'abs' && d.alt !== null
  const toV = (m: number) => (abs ? (d.alt as number) - m : m)          // MD → значение на оси (а.о. = альтитуда − MD)
  const toM = (v: number) => (abs ? (d.alt as number) - v : v)
  const vLo = Math.min(toV(v0), toV(v1)), vHi = Math.max(toV(v0), toV(v1))
  const step = [1, 2, 5, 10, 20, 50, 100].find(s => (vHi - vLo) / s <= 14) ?? 100
  const ticks: number[] = []
  for (let t = Math.ceil(vLo / step) * step; t <= vHi; t += step) ticks.push(t)
  const W = AXIS + PERF + 8 + d.tracks.length * (TW + PAD) + 150
  const gx = (ti: number) => AXIS + PERF + 8 + ti * (TW + PAD)
  return (
    <svg ref={zoom.ref} className="well-planshet zoomable" viewBox={`0 0 ${W} ${HEAD + H + 12}`} role="img" aria-label="Планшет ГИС по глубине">
      <defs>
        <pattern id="pl-perf" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="#fecdd3" /><line x1="0" y1="0" x2="0" y2="6" stroke="#e11d48" strokeWidth="2" />
        </pattern>
      </defs>
      <clipPath id={clip}><rect x="0" y={HEAD} width={W} height={H} /></clipPath>
      <rect x="0" y="0" width={W} height={HEAD + H + 12} rx="8" className="schematic-bg" />
      <text x={AXIS - 9} y={HEAD - 8} className="schematic-tick-text" textAnchor="end">{abs ? 'а.о.' : 'MD'}</text>
      {ticks.map(t => (
        <g key={t}><line x1={AXIS - 6} x2={AXIS} y1={y(toM(t))} y2={y(toM(t))} className="schematic-tick" />
          <text x={AXIS - 9} y={y(toM(t))} className="schematic-tick-text" textAnchor="end" dominantBaseline="middle">{t}</text>
          <line x1={AXIS + PERF + 4} x2={W - 150} y1={y(toM(t))} y2={y(toM(t))} className="planshet-grid" /></g>))}
      <text x={AXIS + PERF / 2} y={HEAD - 8} className="planshet-head" textAnchor="middle">Перф.</text>
      <g clipPath={`url(#${clip})`}>
      {d.perf.map((p, i) => (
        <rect key={i} x={AXIS} y={y(p.top)} width={PERF} height={Math.max(y(p.bottom) - y(p.top), 1)} fill="url(#pl-perf)" stroke="#be123c">
          <title>{`Перфорация ${ru(p.top)}–${ru(p.bottom)} м`}</title></rect>))}
      </g>
      {d.tracks.map((t, ti) => {
        const x0 = gx(ti), kx = (kg: number) => x0 + Math.min(Math.max(kg, 0), 1) * TW
        return (
          <g key={ti}>
            <rect x={x0} y={HEAD} width={TW} height={H} className="planshet-track" />
            <text x={x0 + TW / 2} y={HEAD - 28} className="planshet-head" textAnchor="middle">{t.title}</text>
            <text x={x0 + TW / 2} y={HEAD - 10} className="schematic-tick-text" textAnchor="middle">замер {t.date}</text>
            <line x1={kx(d.cutoff)} x2={kx(d.cutoff)} y1={HEAD} y2={HEAD + H} className="planshet-cutoff" />
            {[0, 0.5, 1].map(v => <text key={v} x={kx(v)} y={HEAD + H + 10} className="schematic-tick-text" textAnchor="middle" style={{ fontSize: 13 }}>{v}</text>)}
            <g clipPath={`url(#${clip})`}>
            {t.bars.map((b, i) => (
              <rect key={i} x={x0} y={y(b.top)} width={Math.max(((b.kg ?? 0) * TW), 1)} height={Math.max(y(b.bottom) - y(b.top) - 1, 1)}
                    fill={b.gas ? color(b.pack) : GRAY} opacity={b.kg === null ? .25 : .9}>
                <title>{`${b.pack}: ${ru(b.top)}–${ru(b.bottom)} м, Кг ${b.kg === null ? 'нет' : ru(b.kg, 2)}${b.gas ? '' : ' (не выше порога)'}`}</title></rect>))}
            {t.packs.map((m, i) => m.gvk === null ? null : (
              <g key={i}>
                <line x1={x0} x2={x0 + TW} y1={y(m.gvk)} y2={y(m.gvk)} stroke={GVK_COLOR} strokeWidth="2.4" strokeDasharray="6 3" />
                <text x={x0 + TW - 3} y={y(m.gvk) - 3} textAnchor="end" className="planshet-gvk" stroke="#fff" strokeWidth="3" paintOrder="stroke">
                  {`ГВК ${ru(m.gvk)} м${m.gvk_abs !== null ? ` (${ru(m.gvk_abs)} а.о.)` : ''}`}</text>
              </g>))}
            </g>
            {t.packs.filter(m => m.h_eff !== null).map((m, i) => (
              <text key={i} x={x0 + 4} y={HEAD + H + 24 + i * 13} className="schematic-tick-text" style={{ fontSize: 13 }}>{`${m.pack}: hг эф ${ru(m.h_eff!)} м`}</text>))}
          </g>)
      })}
      {packs.map((p, i) => (
        <g key={p}><rect x={W - 142} y={HEAD + i * 20} width="12" height="12" fill={color(p)} /><text x={W - 124} y={HEAD + i * 20 + 10} className="schematic-tick-text" style={{ fontSize: 14 }}>{p}</text></g>))}
      <g><rect x={W - 142} y={HEAD + packs.length * 20} width="12" height="12" fill={GRAY} />
        <text x={W - 124} y={HEAD + packs.length * 20 + 10} className="schematic-tick-text" style={{ fontSize: 14 }}>{`Кг ≤ ${d.cutoff}`}</text></g>
    </svg>
  )
}

/** Рисунок-график: схема скважины или планшет с теми же кнопками «Копировать» и «Скачать», что у остальных графиков (PNG и SVG делает экран). */
export function FigureView({ chart }: { chart: Chart }) {
  const f = chart.figure as FigureData | null | undefined
  const box = useRef<HTMLDivElement>(null)
  if (!f) return null
  const svgText = () => {
    const svg = box.current?.querySelector('svg')
    if (!svg) throw new Error('Рисунок ещё не готов.')
    const clone = svg.cloneNode(true) as SVGSVGElement
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    const css = 'text{font-family:Arial,sans-serif}.schematic-bg{fill:#fff;stroke:#d1d5db}.schematic-tick{stroke:#6b7280;stroke-width:.8}' +
      '.schematic-tick-text{font-size:14px;fill:#6b7280}.schematic-label{font-size:16px;font-weight:600}.planshet-head{font-size:14px;font-weight:600;fill:#111827}' +
      '.planshet-track{fill:none;stroke:#9ca3af}.planshet-grid{stroke:#e5e7eb;stroke-width:.6}.planshet-cutoff{stroke:#9ca3af;stroke-dasharray:3 3}.planshet-gvk{font-size:12px;font-weight:600;fill:' + GVK_COLOR + '}'
    const style = document.createElementNS('http://www.w3.org/2000/svg', 'style')
    style.textContent = css
    clone.insertBefore(style, clone.firstChild)
    return { text: new XMLSerializer().serializeToString(clone), box: svg.viewBox.baseVal }
  }
  const png = (dpi: number) => new Promise<Blob>((resolve, reject) => {
    const { text, box: vb } = svgText()
    const scale = Math.min(Math.max(dpi, 96) / 96, 6)
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(vb.width * scale); canvas.height = Math.round(vb.height * scale)
      const ctx = canvas.getContext('2d')!
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      canvas.toBlob(b => b ? resolve(b) : reject(new Error('Не удалось получить PNG.')), 'image/png')
    }
    img.onerror = () => reject(new Error('Не удалось нарисовать PNG.'))
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(text)
  })
  const file = async (kind: 'png' | 'svg', dpi: number) => kind === 'png' ? png(dpi) : new Blob([svgText().text], { type: 'image/svg+xml' })
  return (
    <figure className="chart figure-chart">
      <figcaption>
        <span title={chart.title}>{chart.title}</span>
        <span className="chart-actions">
          <CopyButton onCopy={() => png(192)} />
          <DownloadMenu onDownload={async () => {}} screen={{ name: chart.title, file }} screenOnly />
        </span>
      </figcaption>
      <div ref={box} className="figure-body">
        {f.kind === 'construction'
          ? <>
              <WellSchematic s={f.data.scheme as Schematic} />
              {(f.data.scheme as Schematic).shapes && (f.data.scheme as Schematic).notes.map(n => <div key={n} className="note info">{n}</div>)}
            </>
          : <WellPlanshet d={f.data} />}
      </div>
    </figure>
  )
}

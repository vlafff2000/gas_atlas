// Предпросмотр «как в файле»: чистая логика сцены рисунка (atlas/engine/core/export_scene.py) — по чему щёлкнули,
// как записать сдвиг в оформление графика, как назвать элемент инженеру. Сам экран — ExportStage.tsx.
import type { ChartFormat, ElementPlace } from './chartFormat'

/** Элемент сцены: имя, вид и рамка [x0, y0, x1, y1] в долях рисунка, начало слева сверху. */
export interface SceneElement {
  id: string
  kind: string
  box: [number, number, number, number]
  text?: string
  axis?: string
  series?: string
  point?: string
  hidden?: boolean
}

/** Что инженер может сдвинуть рукой и что спрятать по одному (как MOVABLE и HIDABLE на сервере). */
export const MOVABLE = ['title', 'subtitle', 'legend', 'axis-title', 'label', 'annotation-text']
export const HIDABLE = ['label']
export const movable = (e: SceneElement | null | undefined) => !!e && MOVABLE.includes(e.kind) && !e.hidden
export const hidable = (e: SceneElement | null | undefined) => !!e && HIDABLE.includes(e.kind)

/** Что поедет, если потянуть за элемент: пункт легенды тянет всю легенду, остальное — само себя (или ничего). */
export function dragTarget(scene: SceneElement[], e: SceneElement | null | undefined): SceneElement | null {
  if (!e) return null
  const target = e.kind === 'legend-item' ? scene.find(x => x.id === e.id.split(':', 1)[0]) ?? null : e
  return movable(target) ? target : null
}

const area = (e: SceneElement) => Math.max(0, e.box[2] - e.box[0]) * Math.max(0, e.box[3] - e.box[1])

/** Элемент под точкой (доли рисунка): самый маленький из тех, чья рамка её накрывает, — подпись поверх ряда, ряд поверх поля.
 * ``slack`` — запас вокруг рамки в долях ширины и высоты: в тонкую линию и мелкую подпись легче попасть. */
export function elementAt(scene: SceneElement[], x: number, y: number, slack: [number, number] = [0, 0]): SceneElement | null {
  let best: SceneElement | null = null
  for (const e of scene) {
    const [x0, y0, x1, y1] = e.box
    if (x < x0 - slack[0] || x > x1 + slack[0] || y < y0 - slack[1] || y > y1 + slack[1]) continue
    if (e.kind === 'plot' && best) continue
    if (!best || best.kind === 'plot' || area(e) < area(best)) best = e
  }
  return best
}

const round = (v: number) => Math.round(v * 10000) / 10000

/** Оформление с новым положением элемента: ``patch`` добавляется к записи; нулевой сдвиг и пустая запись не хранятся. */
export function withPlace(doc: ChartFormat, id: string, patch: ElementPlace | null): ChartFormat {
  const all = { ...doc.elements }
  const next: ElementPlace = patch ? { ...all[id], ...patch } : {}
  for (const key of ['dx', 'dy'] as const) {
    const v = next[key]
    if (v === undefined || !Number.isFinite(v) || Math.abs(v) < 0.00005) delete next[key]
    else next[key] = Math.max(-1, Math.min(1, round(v)))
  }
  if (!next.hide) delete next.hide
  if (Object.keys(next).length) all[id] = next
  else delete all[id]
  const { elements: _old, ...rest } = doc
  return Object.keys(all).length ? { ...rest, elements: all } : rest
}

/** Сдвинуть элемент ещё на (dx, dy) долей рисунка — к тому, что уже записано. */
export function shifted(doc: ChartFormat, id: string, dx: number, dy: number): ChartFormat {
  const now = doc.elements?.[id] ?? {}
  return withPlace(doc, id, { dx: (now.dx ?? 0) + dx, dy: (now.dy ?? 0) + dy })
}

/** Вернуть элемент на автоматическое место (спрятанная подпись остаётся спрятанной). */
export const unshifted = (doc: ChartFormat, id: string): ChartFormat => withPlace(doc, id, { dx: 0, dy: 0 })

export const isShifted = (doc: ChartFormat, id: string) => !!(doc.elements?.[id]?.dx || doc.elements?.[id]?.dy)

const AXES: Record<string, string> = { x: 'X', y: 'Y', y2: 'Y2', y3: 'Y3', y4: 'Y4', y5: 'Y5' }
const cut = (text: string | undefined, n = 40) => { const t = (text ?? '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n - 1) + '…' : t }

/** Дата точки из ключа «гггг-мм-дд» по-русски; прочие ключи — как есть. */
const pointText = (key: string | undefined) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(key ?? ''); return m ? `${m[3]}.${m[2]}.${m[1]}` : key ?? '' }

/** Название элемента для инженера. */
export function elementTitle(e: SceneElement): string {
  const quoted = e.text ? ` «${cut(e.text)}»` : ''
  switch (e.kind) {
    case 'plot': return 'Область построения'
    case 'title': return 'Заголовок' + quoted
    case 'subtitle': return 'Подзаголовок' + quoted
    case 'legend': return 'Легенда'
    case 'legend-item': return 'Пункт легенды' + quoted
    case 'axis': return `Ось ${AXES[e.axis ?? ''] ?? e.axis ?? ''}`.trim()
    case 'axis-title': return `Название оси ${AXES[e.axis ?? ''] ?? e.axis ?? ''}`.trim() + quoted
    case 'series': return `Ряд «${cut(e.series)}»`
    case 'label': return `Подпись${quoted}: ряд «${cut(e.series)}», ${pointText(e.point)}`
    case 'annotation': return 'Линия или полоса аннотации'
    case 'annotation-text': return 'Текст аннотации' + quoted
    default: return e.id
  }
}

/** Какой раздел панели «Формат» открыть двойным щелчком: 'chart', 'axis:y2' или 'series:3' (номер ряда графика по имени). */
export function formatTarget(e: SceneElement, seriesNames: string[]): string {
  if (e.kind === 'axis' || e.kind === 'axis-title') return 'axis:' + (e.axis ?? 'x')
  const name = e.kind === 'legend-item' ? (e.text ?? '') : e.kind === 'series' || e.kind === 'label' ? (e.series ?? '') : null
  if (name === null) return 'chart'
  const plain = name.replace(/#\d+$/, '')
  const nth = Number(/#(\d+)$/.exec(name)?.[1] ?? 1)
  let seen = 0
  for (let i = 0; i < seriesNames.length; i++) if (seriesNames[i] === plain && ++seen === nth) return 'series:' + i
  return 'chart'
}

/** Шаг стрелки в долях рисунка: мелкий, с Shift — крупный. */
export const nudgeStep = (shift: boolean) => (shift ? 0.01 : 0.0025)

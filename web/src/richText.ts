/**
 * Подписи с верхними и нижними индексами: `<sup>…</sup>` и `<sub>…</sub>`.
 * Тот же набор тегов понимает Plotly (выгрузка PNG/PDF/SVG), поэтому строка хранится одна и та же
 * и на экране, и в файле. Python-зеркало — `atlas/rich_text.py`.
 */

export interface RichSeg { text: string; sup: boolean; sub: boolean }

const TAG = /<(\/?)(sup|sub)>/g

/** Разбирает строку на куски одинакового начертания. Незакрытый тег действует до конца строки. */
export function parseRich(value: string): RichSeg[] {
  const out: RichSeg[] = []
  let sup = false
  let sub = false
  let last = 0
  const push = (text: string) => { if (text) out.push({ text, sup, sub }) }
  for (const m of value.matchAll(TAG)) {
    push(value.slice(last, m.index))
    const on = m[1] === ''
    if (m[2] === 'sup') sup = on
    else sub = on
    last = m.index + m[0].length
  }
  push(value.slice(last))
  return out
}

/** Текст без тегов: для имён файлов, таблиц и мест, где индексы не выводятся. */
export function plainRich(value: string): string {
  return value.replace(TAG, '')
}

/** HTML для подсказок: текст экранируется, индексы выводятся как `<sup>` и `<sub>`. */
export function richHtml(value: string): string {
  return parseRich(value).map(s => {
    const text = s.text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return s.sup ? `<sup>${text}</sup>` : s.sub ? `<sub>${text}</sub>` : text
  }).join('')
}

/** Строка в тегах из кусков: соседние куски одного начертания склеиваются. */
export function richFromSegs(segs: RichSeg[]): string {
  let out = ''
  let sup = false
  let sub = false
  for (const s of segs) {
    if (s.sup !== sup) { out += s.sup ? '<sup>' : '</sup>'; sup = s.sup }
    if (s.sub !== sub) { out += s.sub ? '<sub>' : '</sub>'; sub = s.sub }
    out += s.text
  }
  if (sub) out += '</sub>'
  if (sup) out += '</sup>'
  return out
}

/**
 * Подпись для ECharts: `{sup|2}`-разметка и словарь стилей `rich`.
 * Индекс поднимается и опускается выравниванием строки, размер — 70 % основного.
 */
export function echartsRich(value: string, fontSize: number): { text: string; rich: Record<string, object> } {
  const small = Math.round(fontSize * 0.7 * 10) / 10
  const text = parseRich(value).map(s => {
    const name = s.sup ? 'sup' : s.sub ? 'sub' : ''
    return name ? `{${name}|${s.text}}` : s.text
  }).join('')
  return {
    text,
    rich: {
      sup: { fontSize: small, verticalAlign: 'top' },
      sub: { fontSize: small, verticalAlign: 'bottom' },
    },
  }
}

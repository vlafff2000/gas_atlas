// Раскладка тепловой карты: порядок строк и итоги. Зеркало atlas/heat_layout.py (проверяет tests/atlas/test_heat_scale.py и web/test/heatLayout.test.ts).
export type HeatSort = 'sum' | 'name'
export type HeatTotals = 'rows' | 'cols' | 'both'
export type HeatKind = 'sum' | 'mean'

const natural = (text: string) => text.split(/(\d+)/).map(p => (/^\d+$/.test(p) ? Number(p) : p.toLowerCase()))
function cmpNatural(a: string, b: string): number {
  const x = natural(a), y = natural(b)
  for (let k = 0; k < Math.min(x.length, y.length); k++) {
    if (x[k] === y[k]) continue
    if (typeof x[k] === typeof y[k]) return x[k] < y[k] ? -1 : 1
    return typeof x[k] === 'number' ? -1 : 1
  }
  return x.length - y.length
}

export function rowOrder(rows: string[], values: (number | null)[][], sort?: HeatSort): number[] {
  const idx = rows.map((_, i) => i)
  const sum = (i: number) => values[i].reduce<number>((a, v) => a + (v ?? 0), 0)
  if (sort === 'sum') return idx.sort((a, b) => sum(b) - sum(a) || a - b)
  if (sort === 'name') return idx.sort((a, b) => cmpNatural(rows[a], rows[b]) || a - b)
  return idx
}

export function total(values: (number | null)[], kind?: HeatKind): number | null {
  const got = values.filter((v): v is number => v !== null)
  if (!got.length) return null
  const sum = got.reduce((a, v) => a + v, 0)
  return kind === 'mean' ? sum / got.length : sum
}

/** Подпись итога: до одного знака после запятой, без лишних нулей. */
export const totalText = (v: number | null) => (v === null ? '' : String(Math.round(v * 10) / 10))

export function heatLayout(rows: string[], values: (number | null)[][], style: { heat_sort?: HeatSort; heat_totals?: HeatTotals; heat_total?: HeatKind }) {
  const order = rowOrder(rows, values, style.heat_sort)
  const mode = style.heat_totals
  const rowTotals = mode === 'rows' || mode === 'both' ? order.map(i => total(values[i], style.heat_total)) : null
  const colTotals = mode === 'cols' || mode === 'both' ? (values[0] ?? []).map((_, j) => total(order.map(i => values[i][j]), style.heat_total)) : null
  return { order, rowTotals, colTotals }
}

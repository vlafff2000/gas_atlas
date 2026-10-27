// Сквозные цвета групп — зеркало pxg_core/group_colors.py (палитра «Атлас-N»); совпадение проверяет tests/test_group_colors.py.
// Одна группа — один цвет во всех программах: цвет считается по ПОЛНОМУ списку групп объекта, а не по тем, что на графике.

const PALETTES: Record<number, string[]> = {
  2: ['#7000FF', '#00CF00'],
  3: ['#7000FF', '#00CF00', '#FF1060'],
  4: ['#00BFFF', '#FF0000', '#00CF50', '#7000FF'],
  5: ['#00BFFF', '#FF8000', '#4030FF', '#FF008F', '#00CF70'],
  6: ['#009FFF', '#AFBF00', '#7000FF', '#EF008F', '#FF0000', '#00BF9F'],
  7: ['#00BFFF', '#FF9F00', '#7000FF', '#007040', '#00CF00', '#FF50CF', '#AF2030'],
  8: ['#0040FF', '#00CF00', '#FF8F9F', '#009FEF', '#FF0000', '#00BF9F', '#606000', '#EF00BF'],
  9: ['#00AFFF', '#00CF00', '#CF0020', '#7000FF', '#00BF9F', '#8F309F', '#FF8FAF', '#606010', '#FF9F00'],
  10: ['#009FFF', '#00CF00', '#FF0000', '#FF00DF', '#00BFAF', '#407020', '#0040FF', '#9F3070', '#FF8F80', '#DFAF10'],
  11: ['#00BFFF', '#FF9F00', '#7000FF', '#00CF00', '#8F4080', '#00BF9F', '#607010', '#BF0000', '#FF8F8F', '#0070EF', '#FF10DF'],
  12: ['#0040FF', '#00CF00', '#FF0070', '#00BFFF', '#00BF9F', '#DFAF00', '#FF0000', '#5050AF', '#007010', '#AF7040', '#FF8FDF', '#FF00EF'],
  13: ['#0060CF', '#00CF00', '#FF0000', '#00BFAF', '#BF0060', '#FF10EF', '#DFAF00', '#805000', '#40BFFF', '#4030FF', '#008030', '#FF8F80', '#FF8FDF'],
  14: ['#00AFEF', '#FF8F00', '#4030FF', '#00CF70', '#BF0050', '#606000', '#0070EF', '#9FBF00', '#FF30FF', '#20BFAF', '#9F208F', '#EF8F70', '#EF8FBF', '#CF0000'],
  15: ['#0040FF', '#AFBF00', '#BF0060', '#10BFFF', '#107030', '#00BFAF', '#FF8000', '#FF10FF', '#EF8F80', '#8F309F', '#0080FF', '#EF8FCF', '#00CF60', '#FF1040', '#805000'],
}
const MAX_PALETTE = 15
export const NO_GROUP_COLOR = '#8a9aa0'

/** Ключ сравнения названий групп: «ГСП_4» = «гсп 4» = «ГСП4». */
export const groupKey = (v: string) =>
  v.trim().replace(/(?<=[^\W\d_])(?=\d)/gu, ' ').replace(/[\s_-]+/g, ' ').trim().toLowerCase()

const naturalParts = (v: string) => groupKey(v).split(/(\d+)/).filter(p => p !== '').map(p => (/^\d+$/.test(p) ? [0, Number(p), ''] as const : [1, 0, p] as const))
export const naturalCompare = (a: string, b: string) => {
  const x = naturalParts(a), y = naturalParts(b)
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const [ka, na, sa] = x[i], [kb, nb, sb] = y[i]
    if (ka !== kb) return ka - kb
    if (na !== nb) return na - nb
    if (sa !== sb) return sa < sb ? -1 : 1
  }
  return x.length - y.length
}

/** Палитра ровно на n цветов; свыше 15 — набор на 15 и дополнительные цвета по золотому углу. */
export function paletteFor(n: number): string[] {
  if (n <= 1) return n === 1 ? [PALETTES[2][0]] : []
  if (PALETTES[n]) return [...PALETTES[n]]
  const out = [...PALETTES[MAX_PALETTE]]
  for (let i = 0; i < n - MAX_PALETTE; i++) out.push(hsl(((i * 0.61803398875 + 0.08) % 1) * 360, 0.62, 0.46))
  return out
}
function hsl(h: number, s: number, l: number) {
  const a = s * Math.min(l, 1 - l)
  const f = (n: number) => { const k = (n + h / 30) % 12; return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))) }
  return '#' + [f(0), f(8), f(4)].map(v => v.toString(16).padStart(2, '0')).join('')
}

let overrides: Record<string, string> = {}
let version = 0
const listeners = new Set<() => void>()
/** Подписка на смену цветов (ручной выбор или сброс); возвращает отписку. */
export const onGroupColorsChange = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn) } }
/** Цвета, заданные инженером вручную (ключ — groupKey): имеют приоритет над палитрой. */
export const setGroupColorOverrides = (o: Record<string, string>) => {
  overrides = Object.fromEntries(Object.entries(o).map(([k, v]) => [groupKey(k), v.toLowerCase()]))
  version++
  listeners.forEach(fn => fn())
}
export const hasGroupColorOverride = (group: string) => groupKey(group) in overrides

/** Ручные цвета лежат в ~/.pxg/group_colors.json и общие для всех программ: читаются с сервера программы (/api/group-colors). */
export async function loadGroupColorOverrides(): Promise<void> {
  try { setGroupColorOverrides(((await (await fetch('/api/group-colors')).json()) as { overrides: Record<string, string> }).overrides) } catch { /* без сервера — палитра */ }
}
/** Запомнить цвет группы (null — вернуть цвет палитры); group='*' и null — сбросить все. */
export async function saveGroupColor(group: string, color: string | null): Promise<void> {
  const r = await fetch('/api/group-colors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ group, color }) })
  setGroupColorOverrides(((await r.json()) as { overrides: Record<string, string> }).overrides)
}

/** Цвета всех групп объекта {название: цвет} по номеру группы; «Без группы» пропускается. */
let memo: { key: string; version: number; value: Record<string, string> } | null = null
export function groupColors(all: string[]): Record<string, string> {
  const key = all.join('\u0001')
  if (memo && memo.key === key && memo.version === version) return memo.value
  const value = computeGroupColors(all)
  memo = { key, version, value }
  return value
}
function computeGroupColors(all: string[]): Record<string, string> {
  const seen = new Map<string, string>()
  for (const g of all) { const s = String(g).trim(); if (s && groupKey(s) !== groupKey('Без группы')) if (!seen.has(groupKey(s))) seen.set(groupKey(s), s) }
  const names = [...seen.values()].sort(naturalCompare)
  const pal = paletteFor(names.length)
  return Object.fromEntries(names.map((g, i) => [g, overrides[groupKey(g)] ?? pal[i]]))
}

/** Цвет одной группы по готовой карте (по нормированному имени); неизвестная — нейтральный серый. */
export function colorOfGroup(name: string, colors: Record<string, string>): string {
  const k = groupKey(name)
  for (const [g, c] of Object.entries(colors)) if (groupKey(g) === k) return c
  return NO_GROUP_COLOR
}

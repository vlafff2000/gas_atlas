/** Единицы отображения оси: единица в подписи меняется вместе с числами (тыс. м³ → млн м³), без приписки «×10ⁿ».
 *  Зеркало atlas/unit_scale.py; общие случаи — tests/atlas/unit_scale_cases.json. */
export type UnitsSetting = 'auto' | 'thousands' | 'millions' | 'billions'
const STEPS: Record<string, number> = { thousands: 1, millions: 2, billions: 3 }
const COUNT = ['', 'тыс. ', 'млн ', 'млрд ', 'трлн ']
const SI = ['', 'к', 'М', 'Г']
const TAIL = String.raw`(?<s>\/[^\s,;)\]]+)?(?=[\s,;)\]]*$)`
const BEFORE = String.raw`(?<![\p{L}\d_.])`
const COUNT_RE = new RegExp(BEFORE + String.raw`(?<p>тыс\. |млн |млрд |трлн )?(?<b>ст\. м³|м³|м3|т|кг|руб\.)` + TAIL, 'u')
const SI_RE = new RegExp(BEFORE + String.raw`(?<p>[кМГ])?(?<b>Па|Вт|Дж)` + TAIL, 'u')

function find(text: string) {
  for (const [re, ladder] of [[COUNT_RE, COUNT], [SI_RE, SI]] as const) {
    const m = re.exec(text || '')
    if (m) return { m, ladder }
  }
  return null
}

/** Подпись со сдвигом единицы на `steps` ступеней вверх (числа делятся на 1000^steps); null — единица не масштабируется. */
export function shiftUnit(text: string, steps: number): string | null {
  const f = find(text)
  if (!f) return null
  const index = f.ladder.indexOf(f.m.groups!.p ?? '') + steps
  if (index < 0 || index >= f.ladder.length) return null
  return text.slice(0, f.m.index) + f.ladder[index] + f.m.groups!.b + (f.m.groups!.s ?? '') + text.slice(f.m.index + f.m[0].length)
}

export function autoSteps(text: string, lo: number, hi: number): number {
  const f = find(text)
  const peak = Math.max(Math.abs(lo), Math.abs(hi))
  if (!f || !Number.isFinite(peak) || peak === 0) return 0
  const here = f.ladder.indexOf(f.m.groups!.p ?? '')
  const want = Math.floor(Math.log10(peak) / 3 + 1e-9)
  return Math.max(-here, Math.min(f.ladder.length - 1 - here, want))
}

/** Делитель чисел и подпись для настройки оси; (1, подпись как есть), если масштабировать нельзя. */
export function resolveUnits(text: string, units: string | undefined, lo: number, hi: number): { divisor: number; text: string } {
  const steps = units === 'auto' ? autoSteps(text, lo, hi) : STEPS[units ?? ''] ?? 0
  const shifted = steps ? shiftUnit(text, steps) : null
  return shifted === null ? { divisor: 1, text } : { divisor: 1000 ** steps, text: shifted }
}

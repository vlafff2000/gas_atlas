// Формулы конструктора на экране: проверка на лету и перенумерация букв при удалении и вставке рядов.
// Расчёт и окончательная проверка — на сервере (atlas/modules/builder_calc.py); здесь тот же разбор без вычислений.

export const FUNCTIONS: [string, number, number, string][] = [
  ['abs', 1, 1, 'модуль'], ['sqrt', 1, 1, 'корень'], ['ln', 1, 1, 'натуральный логарифм'], ['log10', 1, 1, 'десятичный логарифм (lg)'],
  ['exp', 1, 1, 'экспонента'], ['min', 2, 20, 'наименьшее'], ['max', 2, 20, 'наибольшее'], ['mean', 2, 20, 'среднее имеющихся'],
]
const ALIASES: Record<string, string> = { lg: 'log10', 'корень': 'sqrt', 'модуль': 'abs' }
const CONSTANTS = ['pi', 'e']
const HOMO: Record<string, string> = { А: 'A', В: 'B', С: 'C', Е: 'E', Н: 'H', К: 'K', М: 'M', О: 'O', Р: 'P', Т: 'T', Х: 'X' }
const TOKEN = /\s*(?:(\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?|[.,]\d+)|([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)|(\*\*|[-+*/^();,×·÷−–—]))/y
const MAX = 500

export const letter = (index: number) => (index <= 26 ? String.fromCharCode(64 + index) : `R${index}`)

/** Номер ряда по имени (A → 1, R12 → 12) или null. */
function refOf(name: string): number | null {
  const n = name.split('').map(c => HOMO[c] ?? c).join('')
  if (/^[A-Z]$/.test(n)) return n.charCodeAt(0) - 64
  const m = /^R(\d{1,3})$/.exec(n)
  return m ? Number(m[1]) : null
}

interface Tok { kind: 'num' | 'name' | 'op'; text: string; at: number }

function tokens(text: string): Tok[] | string {
  const out: Tok[] = []
  let pos = 0
  while (pos < text.length) {
    if (!text.slice(pos).trim()) break
    TOKEN.lastIndex = pos
    const m = TOKEN.exec(text)
    if (!m) {
      const rest = text.slice(pos)
      const bad = rest.trimStart()[0]
      return `недопустимый символ «${bad}»${bad === '.' ? ' — у рядов нет полей через точку' : ''} (знак ${pos + rest.indexOf(bad) + 1})`
    }
    const [kind, value] = m[1] !== undefined ? ['num', m[1]] : m[2] !== undefined ? ['name', m[2]] : ['op', m[3]]
    const op = ({ '×': '*', '·': '*', '÷': '/', '−': '-', '–': '-', '—': '-', '**': '^' } as Record<string, string>)[value] ?? value
    out.push({ kind: kind as Tok['kind'], text: kind === 'op' ? op : value, at: m.index + m[0].length - value.length })
    pos = TOKEN.lastIndex
  }
  return out
}

/** Ошибка формулы ряда ``index`` (с 1) по-русски или пусто; ``refs`` — номера рядов формулы. */
export function checkFormula(text: string, index: number, rows: number): { error: string; refs: number[] } {
  const refs: number[] = []
  if (!text.trim()) return { error: '', refs }
  if (text.length > MAX) return { error: `не длиннее ${MAX} знаков`, refs }
  const toks = tokens(text)
  if (typeof toks === 'string') return { error: toks, refs }
  let i = 0, depth = 0
  const fail = (msg: string, t?: Tok) => { throw new Error(msg + (t ? ` (знак ${t.at + 1})` : '')) }
  const peek = () => toks[i]
  const take = (v?: string) => {
    const t = toks[i]
    if (!t) fail(v ? `не хватает «${v}»` : 'формула обрывается — допишите выражение')
    if (v && t.text !== v) fail(`ожидается «${v}», а стоит «${t.text}»`, t)
    i++; return t
  }
  const nest = () => { if (++depth > 60) fail('слишком глубокая вложенность скобок') }
  const expr = (): void => { nest(); term(); while (peek()?.kind === 'op' && '+-'.includes(peek().text)) { i++; term() } depth-- }
  const term = (): void => { unary(); while (peek()?.kind === 'op' && (peek().text === '*' || peek().text === '/')) { i++; unary() } }
  const unary = (): void => {
    if (peek()?.kind === 'op' && '+-'.includes(peek().text)) { i++; nest(); unary(); depth--; return }
    atom(); if (peek()?.kind === 'op' && peek().text === '^') { i++; nest(); unary(); depth-- }
  }
  const atom = (): void => {
    const t = take()
    if (t.kind === 'num') return
    if (t.kind === 'op' && t.text === '(') { expr(); take(')'); return }
    if (t.kind === 'name') {
      if (peek()?.text === '(') {
        const name = ALIASES[t.text.toLowerCase()] ?? t.text.toLowerCase()
        const f = FUNCTIONS.find(x => x[0] === name)
        if (!f) fail(`неизвестная функция «${t.text}»${name === 'log' ? ' — для логарифма есть ln и log10' : ''}; есть: ${FUNCTIONS.map(x => x[0]).join(', ')}`, t)
        i++
        let n = 0
        if (peek()?.text !== ')') { expr(); n = 1 }
        while (peek() && (peek().text === ';' || peek().text === ',')) { i++; expr(); n++ }
        take(')')
        if (n < f![1] || n > f![2]) fail(`у функции ${name} аргументов: ${f![1] === f![2] ? f![1] : 'от ' + f![1]}, а задано ${n} (аргументы — через «;»)`, t)
        return
      }
      if (CONSTANTS.includes(t.text)) return
      const r = refOf(t.text)
      if (r !== null) { refs.push(r); return }
      fail(`неизвестное имя «${t.text}»: ряды — заглавные буквы A, B, C… (или R1, R2…), функции — ${FUNCTIONS.map(x => x[0]).join(', ')}`, t)
    }
    fail(`ожидается число, ряд или «(», а стоит «${t.text}»`, t)
  }
  try {
    if (!toks.length) fail('пустая формула')
    expr()
    if (peek()) fail(`лишнее «${peek().text}» — не хватает знака операции или скобки`, peek())
    if (!refs.length) fail('нет ни одного ряда — укажите ряды буквами (A — ряд 1, B — ряд 2…)')
    const missing = refs.find(r => r < 1 || r > rows)
    if (missing !== undefined) fail(`ряда ${letter(missing)} (№ ${missing}) нет — в макете рядов: ${rows}`)
    if (refs.includes(index)) fail('формула ссылается на свой же ряд')
  } catch (e) {
    return { error: (e as Error).message, refs }
  }
  return { error: '', refs: [...new Set(refs)] }
}

/** Циклическая ссылка через другие формулы: номера рядов цикла или null. */
export function findCycle(formulas: Map<number, number[]>): number[] | null {
  const state = new Map<number, number>()
  const visit = (i: number, path: number[]): number[] | null => {
    if (state.get(i) === 2 || !formulas.has(i)) return null
    if (state.get(i) === 1) return [...path.slice(path.indexOf(i)), i]
    state.set(i, 1)
    for (const r of formulas.get(i)!) { const c = visit(r, [...path, i]); if (c) return c }
    state.set(i, 2)
    return null
  }
  for (const i of [...formulas.keys()].sort((a, b) => a - b)) { const c = visit(i, []); if (c) return c }
  return null
}

/** Буквы рядов в формуле по новой нумерации: ``map`` — старый номер → новый (null — ряд удалён, буква остаётся). */
export function renumber(text: string, map: (n: number) => number | null): string {
  const toks = tokens(text)
  if (typeof toks === 'string') return text
  let out = '', last = 0
  toks.forEach((t, k) => {
    if (t.kind !== 'name' || toks[k + 1]?.text === '(') return
    const r = refOf(t.text)
    const n = r === null ? null : map(r)
    if (n === null || n === r) return
    out += text.slice(last, t.at) + letter(n)
    last = t.at + t.text.length
  })
  return out + text.slice(last)
}

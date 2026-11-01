// Выбор файлов в проводнике. Галочку ставит либо инженер (пробел, мышь, рамка), либо навигация стрелками (автоматическая).
// Автоматическая идёт за курсором и снимается, как только курсор ушёл на папку или другой файл; ручная живёт, пока инженер сам не снимет.
export interface PickerItem { name: string; dir: boolean }
export interface Carried { dir: string; name: string }
export interface Marks { marked: string[]; auto: string[] }

/** Шаг курсора стрелкой (без Shift и Ctrl) на строку n: прежняя автогалочка уходит, ручные остаются. */
export function marksAfterArrow(items: PickerItem[], n: number, marks: Marks): Marks {
  const it = items[n]
  if (!it) return marks
  const manual = marks.marked.filter(x => !marks.auto.includes(x))
  if (it.dir) return { marked: manual, auto: [] }
  if (manual.includes(it.name)) return { marked: manual, auto: [] }
  return { marked: [...manual, it.name], auto: [it.name] }
}

/** Пробел на файле: автогалочка становится ручной (остаётся), обычная переключается. */
export function marksAfterSpace(name: string, marks: Marks): Marks {
  if (marks.auto.includes(name)) return { marked: marks.marked, auto: marks.auto.filter(x => x !== name) }
  const on = marks.marked.includes(name)
  return { marked: on ? marks.marked.filter(x => x !== name) : [...marks.marked, name], auto: marks.auto }
}

/** Смена папки: автогалочки пропадают, ручные из прежней папки переезжают в «перенесённые» (путь + имя), ручные новой папки возвращаются в список. */
export function marksAfterNavigate(marks: Marks, carried: Carried[], fromPath: string, toPath: string): { marked: string[]; auto: string[]; carried: Carried[] } {
  if (fromPath === toPath) return { ...marks, carried }
  const manual = marks.marked.filter(x => !marks.auto.includes(x))
  const all = [...carried, ...manual.map(name => ({ dir: fromPath, name }))]
  const seen = new Set<string>()
  const uniq = all.filter(c => { const k = c.dir + '\u0000' + c.name; if (seen.has(k)) return false; seen.add(k); return true })
  return { marked: uniq.filter(c => c.dir === toPath).map(c => c.name), auto: [], carried: uniq.filter(c => c.dir !== toPath) }
}

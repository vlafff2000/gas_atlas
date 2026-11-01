// Выбор файлов в проводнике при движении курсора стрелками: галочка идёт за курсором только по файлам.
export interface PickerItem { name: string; dir: boolean }

/** Что станет выбранным после шага курсора на строку n (без Shift и Ctrl). */
export function marksAfterArrow(items: PickerItem[], n: number, marked: string[]): string[] {
  const it = items[n]
  if (!it) return marked
  return it.dir ? [] : [it.name]
}

/** Выбор живёт только в одной папке: при смене папки он сбрасывается. */
export function marksAfterNavigate(marked: string[], fromPath: string, toPath: string): string[] {
  return fromPath === toPath ? marked : []
}

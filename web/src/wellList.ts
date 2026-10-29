// Список скважин из текста (буфер обмена, поле «вставить список»): как atlas/well_sets.py. Порядок сохраняется, повторы убираются.

/** «31.0» и «031» — одна скважина «31»; остальные записи не меняются. */
export function normWell(text: string): string {
  const t = text.trim()
  return /^\d+(\.0*)?$/.test(t) ? String(Number(t)) : t
}

/** Столбец из Excel, через запятую, точку с запятой, табуляцию, вертикальную черту или пробел. */
export function parseWellList(text: string): string[] {
  const out: string[] = []
  for (const part of text.split(/[\r\n\t;,|]+/)) {
    for (const token of part.trim().split(/\s+/)) if (token) out.push(normWell(token))
  }
  return [...new Set(out)]
}

/** Подписи категорий оси X: переименование и перенос по ширине (зеркало atlas/category_labels.py). */
export interface CategoryLabels { category_names?: Record<string, string>; category_wrap?: number }

/** Перенос по словам: строка не длиннее width знаков, слово длиннее ширины остаётся целым, свой «\n» сохраняется. */
export function wrapText(text: string, width: number): string {
  if (!width || width < 1) return text
  return text.split('\n').map(part => {
    const lines: string[] = []
    let line = ''
    for (const word of part.split(/\s+/).filter(Boolean)) {
      if (!line) line = word
      else if (line.length + 1 + word.length <= width) line += ' ' + word
      else { lines.push(line); line = word }
    }
    if (line) lines.push(line)
    return lines.length ? lines.join('\n') : part
  }).join('\n')
}

export function categoryLabel(name: string, spec: CategoryLabels | undefined): string {
  const shown = spec?.category_names?.[name] || name
  return wrapText(shown, spec?.category_wrap ?? 0)
}

/** Соседняя скважина в списке вариантов: step = -1 — предыдущая, +1 — следующая; на краю остаётся крайняя. */
export function stepWell(options: string[], current: string, step: number): string | undefined {
  if (!options.length) return undefined
  const at = options.indexOf(current)
  const next = at < 0 ? (step > 0 ? 0 : options.length - 1) : at + step
  return options[Math.min(options.length - 1, Math.max(0, next))]
}

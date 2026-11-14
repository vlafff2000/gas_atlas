/** Запоминание прокрутки раздела: куда вернуть окно, когда страница отрисована. Без React: проверяется тестом. */
export function scrollRestore(saved: number | null, docHeight: number, viewHeight: number): { y: number; done: boolean } {
  if (saved === null || !Number.isFinite(saved) || saved <= 0) return { y: 0, done: true }
  const max = Math.max(0, docHeight - viewHeight)
  // страница ниже нужной точки: графики ещё дорисовываются, идём до конца и пробуем снова
  return saved <= max ? { y: saved, done: true } : { y: max, done: false }
}

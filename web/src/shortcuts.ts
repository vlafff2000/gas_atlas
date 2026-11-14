/** Единый список сочетаний клавиш: его показывает окно по «?» / F1. Новое сочетание добавлять сюда. */
export interface Shortcut { group: string; keys: string; text: string }

export const SHORTCUTS: Shortcut[] = [
  { group: 'Навигация', keys: 'Ctrl+K', text: 'Найти раздел' },
  { group: 'Навигация', keys: '? или F1', text: 'Это окно со всеми сочетаниями' },
  { group: 'Навигация', keys: 'Esc', text: 'Закрыть окно или снять закрепленные подсказки на графике' },
  { group: 'Правка', keys: 'Ctrl+Z', text: 'Отменить: параметры, фильтры, макет и исключение точек' },
  { group: 'Правка', keys: 'Ctrl+Y или Ctrl+Shift+Z', text: 'Вернуть отмененное' },
  { group: 'Графики', keys: 'Ctrl+колесо', text: 'Масштаб графика и осей (обычное колесо листает страницу)' },
  { group: 'Графики', keys: 'Ctrl+1', text: 'Формат графика под указателем' },
  { group: 'Графики', keys: 'Двойной щелчок по оси', text: 'Задать границы и шаг оси' },
  { group: 'Графики', keys: 'Правая кнопка', text: 'Формат элемента под указателем: ось, ряд или график' },
  { group: 'Графики', keys: 'Перетаскивание', text: 'Сдвиг окна графика по полю или вдоль оси' },
]

/** Открывает ли нажатие шпаргалку: «?» или F1, но не при вводе текста и не с Ctrl/⌘/Alt. */
export function isHelpKey(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; target?: unknown }): boolean {
  if (e.ctrlKey || e.metaKey || e.altKey) return false
  if (e.key === 'F1') return true
  if (e.key !== '?') return false
  const t = e.target as { tagName?: string; isContentEditable?: boolean } | null | undefined
  const tag = t?.tagName?.toUpperCase()
  return !(tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable)
}

// Что делает щелчок по графику. Чистая функция без DOM — чтобы выбор между «исключить точку» и «закрепить подсказку» проверялся тестом.
export type ClickAction = 'none' | 'label' | 'suspect' | 'exclude' | 'not-excludable' | 'pin'

export interface ClickInput {
  moved: boolean                   // указатель сдвинулся между нажатием и отпусканием (перетаскивание, выделение)
  hover: boolean                   // под указателем есть подсказка
  boxActive: boolean               // идёт выделение рамкой для масштаба
  labelPicker: boolean             // включён выбор подписей данных
  excludeMode: boolean             // включено «Исключать точки кликом»
  point: { excludable: boolean; suspect: boolean; valueLabels: boolean } | null   // отметка в радиусе щелчка
}

export function clickAction(i: ClickInput): ClickAction {
  if (i.moved) return 'none'
  const p = i.point
  if (p && i.labelPicker && p.valueLabels) return 'label'
  if (p && i.excludeMode) return p.excludable ? (p.suspect ? 'suspect' : 'exclude') : 'not-excludable'   // расчётную точку не закрепляем: инженер ждал исключения
  if (i.hover && !i.boxActive) return 'pin'
  return 'none'
}

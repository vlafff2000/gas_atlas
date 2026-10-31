// Кнопки «Второе окно» и «Окна связаны»: одна и та же программа на двух мониторах (см. windows.ts).
// Подключение: <WindowButtons page={текущая страница} other="страница для второго окна" />, обычно в боковом меню.
import { usePref } from './pref'
import { linkWindows, openSecondWindow } from './windows'

export function WindowButtons({ page, other }: { page: string; other?: string }) {
  const linked = usePref(linkWindows)
  return (
    <div className="window-buttons">
      <button type="button" className="quiet" onClick={() => openSecondWindow(other ?? page)}
        title="Открыть эту же программу во втором окне (для второго монитора)">Второе окно</button>
      <button type="button" className="quiet" onClick={() => linkWindows.set(!linked)} aria-pressed={linked}
        title="Связь окон: выбранная скважина, сезон, период и настройки совпадают в обоих окнах">{linked ? 'Окна связаны' : 'Окна независимы'}</button>
    </div>
  )
}

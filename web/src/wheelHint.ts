import { wheelHintDue } from './chartAxes'

/** Подсказка «Ctrl+колесо — масштаб»: показывается, когда колесо крутят над графиком без Ctrl. */
export const HINT_TEXT = 'Ctrl+колесо — масштаб'
const SHOW_MS = 1500 // сколько висит надпись

const off = () => { try { return localStorage.getItem('atlas.wheelHint') === 'off' } catch { return false } }

/** Вешает подсказку на область графика; возвращает функцию снятия. */
export function attachWheelHint(host: HTMLElement): () => void {
  let enteredAt = Infinity, lastShown = -Infinity, el: HTMLDivElement | null = null, timer = 0
  const enter = () => { enteredAt = performance.now() }
  const leave = () => { enteredAt = Infinity; hide() }
  const hide = () => { el?.classList.remove('on'); clearTimeout(timer) }
  const wheel = (e: WheelEvent) => {
    const now = performance.now()
    if (off() || !wheelHintDue(e, now, enteredAt, lastShown)) return
    lastShown = now
    if (!el) {
      el = document.createElement('div')
      el.className = 'wheel-hint'; el.textContent = HINT_TEXT; el.setAttribute('role', 'status')
      host.appendChild(el)
    }
    el.classList.add('on')
    clearTimeout(timer); timer = window.setTimeout(hide, SHOW_MS)
  }
  host.addEventListener('pointerenter', enter); host.addEventListener('pointerleave', leave)
  host.addEventListener('wheel', wheel, { passive: true })
  return () => {
    host.removeEventListener('pointerenter', enter); host.removeEventListener('pointerleave', leave)
    host.removeEventListener('wheel', wheel); clearTimeout(timer); el?.remove()
  }
}

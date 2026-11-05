import { stepWell } from './wellStep'

/** Стрелки «предыдущая / следующая скважина» по списку вариантов. Общий компонент: параметр «Скважины» в разделах и паспорт скважины.
 *  Клавиши ← и → тоже листают, пока фокус на кнопке или списке (в полях ввода стрелки двигают курсор). */
export function WellStepper({ options, value, onChange, children }:
  { options: string[]; value: string; onChange: (well: string) => void; children?: React.ReactNode }) {
  const at = options.indexOf(value)
  const go = (step: number) => { const w = stepWell(options, value, step); if (w !== undefined && w !== value) onChange(w) }
  return (
    <span className="well-stepper"
      onKeyDown={e => {
        if (!(e.target instanceof HTMLSelectElement) && !(e.target instanceof HTMLButtonElement)) return
        if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1) } else if (e.key === 'ArrowRight') { e.preventDefault(); go(1) }
      }}>
      <button type="button" className="quiet" disabled={at <= 0} onClick={() => go(-1)}
        title="Предыдущая скважина (←)" aria-label="Предыдущая скважина">←</button>
      {children}
      <button type="button" className="quiet" disabled={at < 0 || at >= options.length - 1} onClick={() => go(1)}
        title="Следующая скважина (→)" aria-label="Следующая скважина">→</button>
    </span>
  )
}

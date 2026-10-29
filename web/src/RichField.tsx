import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ClipboardEvent } from 'react'
import { parseRich, richFromSegs, type RichSeg } from './richText'

/** Символы, которые часто нужны в подписях (как в Excel: вставка символа). */
const SYMBOLS: [string, string[]][] = [
  ['Греческие', 'α β γ δ ε η θ λ μ ν π ρ σ τ φ ω Δ Σ Φ Ω'.split(' ')],
  ['Степени', '² ³ ¹ ⁰ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹ ⁺ ⁻'.split(' ')],
  ['Знаки', '± × ÷ ° · ‰ µ ≈ ≤ ≥ ≠ → ← ↑ ↓ ∞ √'.split(' ')],
]

const ZERO_WIDTH = '​'  // ноль-ширины символ: в пустом индексе держит каретку

/** Текст поля из DOM: индексы — по элементам SUP и SUB, остальное — как есть. */
function serialize(node: Node): string {
  const segs: RichSeg[] = []
  const walk = (n: Node, sup: boolean, sub: boolean) => {
    if (n.nodeType === Node.TEXT_NODE) {
      const text = (n.textContent ?? '').replace(/​/g, '')
      if (text) segs.push({ text, sup, sub })
      return
    }
    if (n.nodeType !== Node.ELEMENT_NODE) return
    const tag = (n as Element).tagName
    if (tag === 'BR') { segs.push({ text: ' ', sup, sub }); return }
    n.childNodes.forEach(c => walk(c, sup || tag === 'SUP', sub || tag === 'SUB'))
  }
  walk(node, false, false)
  return richFromSegs(segs)
}

/** Заполняет поле из строки: элементы строятся через DOM, текст не разбирается как HTML. */
function fill(el: HTMLElement, value: string) {
  const nodes = parseRich(value).map(s => {
    const text = document.createTextNode(s.text)
    if (!s.sup && !s.sub) return text
    const wrap = document.createElement(s.sup ? 'sup' : 'sub')
    wrap.appendChild(text)
    return wrap
  })
  el.replaceChildren(...nodes)
}

/** Вставка текста в позицию каретки (или вместо выделения). */
function insertAtCaret(el: HTMLElement, text: string) {
  el.focus()
  const sel = window.getSelection()
  if (!sel) return
  let range: Range
  if (sel.rangeCount && el.contains(sel.anchorNode)) range = sel.getRangeAt(0)
  else { range = document.createRange(); range.selectNodeContents(el); range.collapse(false) }
  range.deleteContents()
  const node = document.createTextNode(text)
  range.insertNode(node)
  range.setStartAfter(node)
  range.collapse(true)
  sel.removeAllRanges()
  sel.addRange(range)
}

/** Ctrl+«+» и Ctrl+«-»: включает или выключает индекс для выделения либо для текста, который будет введён. */
function toggleScript(el: HTMLElement, tag: 'SUP' | 'SUB') {
  el.focus()
  const sel = window.getSelection()
  if (!sel || !sel.rangeCount || !el.contains(sel.anchorNode)) return
  const range = sel.getRangeAt(0)
  const inside = (node: Node | null) => { let n: Node | null = node; while (n && n !== el) { if ((n as Element).tagName === tag) return n as Element; n = n.parentNode } return null }
  if (range.collapsed) {
    const wrap = inside(range.startContainer)
    if (wrap) {                                 // выйти из индекса: каретка за ним
      const after = document.createTextNode(ZERO_WIDTH)   // не пустой узел: иначе браузер поставит каретку обратно в индекс
      wrap.after(after)
      range.setStart(after, 1); range.collapse(true)
    } else {                                    // войти в индекс: пустой элемент, в него попадёт набор
      const node = document.createElement(tag.toLowerCase())
      node.textContent = ZERO_WIDTH
      range.insertNode(node)
      range.setStart(node.firstChild!, 1); range.collapse(true)
    }
  } else {
    const wrap = inside(range.commonAncestorContainer)
    if (wrap) {                                 // всё выделение уже в индексе — снять
      const parent = wrap.parentNode!
      while (wrap.firstChild) parent.insertBefore(wrap.firstChild, wrap)
      parent.removeChild(wrap)
    } else {
      const frag = range.extractContents()
      const node = document.createElement(tag.toLowerCase())
      node.appendChild(frag)
      range.insertNode(node)
      range.selectNodeContents(node)
    }
  }
  sel.removeAllRanges()
  sel.addRange(range)
}

/** Поле с индексами. Значение — строка с тегами `<sup>` и `<sub>`; Enter не переносит строку. */
export function RichField({ label, value, placeholder, onChange, width }: {
  label: string; value: string | undefined; placeholder: string; onChange: (v: string) => void; width?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)

  // внешнее изменение значения перерисовывает поле; собственный ввод (он совпадает с value) не трогает каретку
  useEffect(() => {
    const el = ref.current
    if (el && serialize(el) !== (value ?? '')) fill(el, value ?? '')
  }, [value])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  const commit = () => { if (ref.current) onChange(serialize(ref.current)) }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const el = ref.current
    if (!el || !(e.ctrlKey || e.metaKey) || e.altKey) {
      if (e.key === 'Enter') { e.preventDefault(); el?.blur() }
      return
    }
    const plus = e.code === 'Equal' || e.code === 'NumpadAdd'
    const minus = e.code === 'Minus' || e.code === 'NumpadSubtract'
    if (!plus && !minus) return
    e.preventDefault()                          // иначе браузер масштабирует страницу
    toggleScript(el, plus ? 'SUP' : 'SUB')
    commit()
  }

  const onPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    e.preventDefault()
    const el = ref.current
    if (!el) return
    insertAtCaret(el, e.clipboardData.getData('text/plain').replace(/[\r\n]+/g, ' '))
    commit()
  }

  const symbol = (ch: string) => {
    const el = ref.current
    if (!el) return
    insertAtCaret(el, ch)
    commit()
  }

  return (
    <div className="field rich-field" ref={wrap} style={width ? { width } : undefined}>
      <span className="field-label">{label}</span>
      <div className="rich-row">
        <div ref={ref} className="rich-input" role="textbox" aria-label={label} aria-multiline="false" data-placeholder={placeholder}
          contentEditable suppressContentEditableWarning spellCheck={false}
          onInput={commit} onKeyDown={onKeyDown} onPaste={onPaste} onBlur={commit} />
        <button type="button" className="rich-symbols" aria-label="Вставить символ" aria-expanded={open} title="Вставить символ"
          onMouseDown={e => e.preventDefault()} onClick={() => setOpen(o => !o)}>Ω</button>
      </div>
      {open && (
        <div className="rich-popup" role="dialog" aria-label="Символы" onMouseDown={e => e.preventDefault()}>
          {SYMBOLS.map(([group, chars]) => (
            <div key={group} className="rich-group">
              <span className="rich-group-title">{group}</span>
              <div className="rich-chars">
                {chars.map(ch => <button key={ch} type="button" onClick={() => symbol(ch)}>{ch}</button>)}
              </div>
            </div>
          ))}
          <p className="rich-hint">Ctrl+«+» — верхний индекс, Ctrl+«-» — нижний</p>
        </div>
      )}
    </div>
  )
}

/** Подпись с индексами для вывода (заголовок графика, подпись оси). */
export function RichText({ value, className, style }: { value: string; className?: string; style?: CSSProperties }) {
  return (
    <span className={'rich-text' + (className ? ' ' + className : '')} style={style}>
      {parseRich(value).map((s, i) => s.sup ? <sup key={i}>{s.text}</sup> : s.sub ? <sub key={i}>{s.text}</sub> : <span key={i}>{s.text}</span>)}
    </span>
  )
}

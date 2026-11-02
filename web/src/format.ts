import type { Cell, Column } from './api'

/** Разряды: неразрывный пробел (U+00A0), как в Python-выгрузке (atlas/engine/core/export_style.py: THOUSANDS_SEP). */
export const THOUSANDS_SEP = ' '

const cache = new Map<string, Intl.NumberFormat>()
function numberFormat(key: string, options: Intl.NumberFormatOptions) {
  if (!cache.has(key)) cache.set(key, new Intl.NumberFormat('ru-RU', { ...options, useGrouping: false }))
  return cache.get(key)!
}

/** Группировка разрядов в целой части: 1000 → «1 000», 1234567,5 → «1 234 567,5» (запятая дроби не трогается). */
function grouped(text: string) {
  return text.replace(/^([-−]?)(\d+)/, (_, sign: string, digits: string) =>
    sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, THOUSANDS_SEP))
}

/** Число для подписей, таблиц и всплывающих подсказок: decimals знаков, null — до 6 значащих цифр. */
export function formatNumber(value: number, decimals: number | null = null) {
  const text = decimals === null
    ? numberFormat('sig', { maximumSignificantDigits: 6 }).format(value)
    : numberFormat(`d${decimals}`, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value)
  return grouped(text)
}

/** Число без лишних нулей, до maxDecimals знаков после запятой (замена toLocaleString('ru-RU', …)). */
export function formatNumberUpTo(value: number, maxDecimals: number) {
  return grouped(numberFormat(`u${maxDecimals}`, { maximumFractionDigits: maxDecimals }).format(value))
}

export function formatDate(iso: string) {
  const [date, time] = iso.split('T')
  const [y, m, d] = date.split('-')
  return d && m && y ? `${d}.${m}.${y}${time ? ' ' + time.slice(0, 5) : ''}` : iso
}

export function formatCell(value: Cell, column: Column) {
  if (value === null || value === '') return ''
  if (column.kind === 'number' && typeof value === 'number') return formatNumber(value, column.decimals)
  if (column.kind === 'date' && typeof value === 'string') return formatDate(value)
  return String(value)
}

export function axisTitle(label: string, unit: string) {
  return unit ? `${label}, ${unit}` : label
}

export function escapeHtml(text: string) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

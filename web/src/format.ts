import type { Cell, Column } from './api'

const cache = new Map<string, Intl.NumberFormat>()
function numberFormat(decimals: number | null) {
  const key = String(decimals)
  if (!cache.has(key)) {
    cache.set(key, new Intl.NumberFormat('ru-RU', decimals === null
      ? { maximumSignificantDigits: 6 }
      : { minimumFractionDigits: decimals, maximumFractionDigits: decimals }))
  }
  return cache.get(key)!
}

export function formatNumber(value: number, decimals: number | null = null) {
  return numberFormat(decimals).format(value)
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

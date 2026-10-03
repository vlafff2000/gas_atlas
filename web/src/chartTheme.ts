// Оформление графиков Атласа 6: одна система для всех разделов.
// Цвета — роли (чернила, сетка, поверхность) из CSS-переменных --chart-*, чтобы тёмная тема меняла их в одном месте.

/** Категориальная палитра: порядок проверен на различимость при всех видах дальтонизма (соседние пары ΔE ≥ 9);
 *  восьмой цвет — коричневый, как в 5.8, а не красный: красный рядом с оранжевым почти не различается. */
export const PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#8a5a14']

/** Палитра 5.8 (app/core/config.py COLORS) → новая по номеру цвета: модули по-прежнему отдают цвета 5.8,
 *  а на экране и в выгрузке они заменяются согласованно (тот же словарь в atlas/render.py). */
export const LEGACY: Record<string, string> = {
  '#dc3545': PALETTE[0], '#2563eb': PALETTE[1], '#169b62': PALETTE[2], '#ed8b23': PALETTE[3],
  '#9955cc': PALETTE[4], '#149ba5': PALETTE[5], '#bd548d': PALETTE[6], '#8c7542': PALETTE[7],
}

/** Та же палитра для тёмного фона: светлее на шаг, порядок и различимость пар сохранены. */
export const DARK_PALETTE = ['#5598ea', '#f2814f', '#2fc48d', '#f2b733', '#ef97b9', '#3aa83a', '#8d80e3', '#b98a4c']
let dark = false
/** Тёмная тема включена — цвета серий берутся из тёмной палитры (вызывает ChartView при смене темы). */
export function setDarkPalette(on: boolean) { dark = on }
export const palette = () => (dark ? DARK_PALETTE : PALETTE)

export function seriesColor(color: string) {
  const c = LEGACY[color.toLowerCase()] ?? color
  if (!dark) return c
  const i = PALETTE.indexOf(c.toLowerCase())
  return i >= 0 ? DARK_PALETTE[i] : c
}

export interface ChartTokens { ink: string; muted: string; faint: string; grid: string; axis: string; surface: string; accent: string }

const FALLBACK: ChartTokens = {
  ink: '#1b2a31', muted: '#5f7178', faint: '#8a9aa0', grid: '#edf1f2', axis: '#c9d4d7',
  surface: '#ffffff', accent: '#0f7d86',
}

export function chartTokens(el: Element): ChartTokens {
  const css = getComputedStyle(el)
  const get = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    ink: get('--chart-ink', FALLBACK.ink), muted: get('--chart-muted', FALLBACK.muted),
    faint: get('--chart-faint', FALLBACK.faint), grid: get('--chart-grid', FALLBACK.grid),
    axis: get('--chart-axis', FALLBACK.axis), surface: get('--chart-surface', FALLBACK.surface),
    accent: get('--chart-accent', FALLBACK.accent),
  }
}

export const FONT = "'PT Sans', 'Segoe UI', system-ui, sans-serif"

/** Цвет с прозрачностью: '#rrggbb' → rgba(). */
export function alpha(hex: string, a: number) {
  const m = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!m) return hex
  const n = parseInt(m[1], 16)
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}

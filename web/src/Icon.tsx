/** Общий набор значков 16×16 (контур задаётся CSS: stroke/fill кнопки). Копия лежит в all_scripts/pxg_core/web-ui. */
const PATHS = {
  'chevron-left': 'M10 3.5 5.5 8 10 12.5',
  'chevron-right': 'M6 3.5 10.5 8 6 12.5',
  'chevron-down': 'M3.5 6 8 10.5 12.5 6',
  menu: 'M2.5 4h11M2.5 8h11M2.5 12h11',
  sun: 'M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1',
  moon: 'M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5Z',
  screen: 'M6 13.5h4',
  search: 'm10.5 10.5 3 3',
} as const
export type IconName = keyof typeof PATHS

export function Icon({ name }: { name: IconName }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      {name === 'search' && <circle cx="7" cy="7" r="4.5" />}
      {name === 'sun' && <circle cx="8" cy="8" r="3" />}
      {name === 'screen' && <rect x="2" y="3" width="12" height="8" rx="1" />}
      <path d={PATHS[name]} />
    </svg>
  )
}

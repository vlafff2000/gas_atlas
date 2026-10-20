import type { Look } from './chartStyle'
// Типы повторяют atlas/contract.py. Интерфейс не знает о конкретных модулях.

export type DatasetKind = string

export interface Option { value: unknown; label: string }
export interface Param {
  name: string
  label: string
  kind: 'number' | 'integer' | 'boolean' | 'choice' | 'multi' | 'date' | 'text' | 'map' | 'file' | 'json'
  default: unknown
  help: string
  formula: string
  example: string
  options: Option[]
  source: { dataset: DatasetKind; column: string } | null
  minimum: number | null
  maximum: number | null
  step: number | null
  unit: string
  setting: string | null
  section: string
  dynamic: boolean
  depends: string[]
  auto: string
  prefix: string
  empty: string
  show_if: Record<string, unknown> | null
  chart_kind: boolean
  extensions: string
}
export interface ModuleSpec {
  id: string
  title: string
  group: string
  description: string
  needs: DatasetKind[]
  optional: DatasetKind[]
  params: Param[]
  auto_run: boolean
  order: number
  panels: number
  save_label: string
}
export interface Project {
  id: string
  name: string
  demo: boolean
  updated: string
  revision: number
  tables: Record<string, number>
  settings: Record<string, unknown>
  excluded: number
}

export interface Column { key: string; label: string; unit: string; decimals: number | null; kind: 'text' | 'number' | 'date'; good?: number | null }
export type Cell = string | number | boolean | null
export interface TableAction {
  kind: 'exclude' | 'assign'; dataset: string | null; id_column: string; label: string; reason: string
  checked_column: string; reason_editable: boolean; ids: string[]; checked: boolean[] | null
  column?: string
  // assign: значения полей по строкам, какие из них правятся, что отправлять, запись журнала
  fields: string[]; editable: string[]; submit: 'changed' | 'all'; journal: string; values: Record<string, Cell[]>
  target: 'groups' | 'object-categories'   // куда уходят назначения: группы скважин или категории объектов кроссплота
}
export type Assignments = Record<string, Record<string, string>>
export interface Table {
  id: string; title: string; columns: Column[]; rows: Cell[][]; count: number
  note: string; collapsed: boolean; action: TableAction | null
  header?: [string, number][][]   // объединённая шапка над подписями колонок: (подпись, пролёт)
  deferred?: boolean   // большая свёрнутая таблица: строки подгружаются при раскрытии (count — сколько их всего)
}
/** Ручное оформление оси; пусто — авто (atlas/chart_style.py). */
export interface AxisStyle { decimals?: number; date_format?: string; font?: string; tick_size?: number; title_size?: number }
/** Ручное оформление графика: заголовок, шрифты, легенда, сетка, фон (atlas/chart_style.py). */
export interface ChartStyle {
  title_font?: string; title_size?: number; title_bold?: boolean; title_color?: string; title_align?: 'left' | 'center' | 'right'
  font?: string; text_color?: string; legend?: 'bottom' | 'top' | 'right' | 'hide'; legend_font?: string; legend_size?: number
  grid?: 'both' | 'h' | 'v' | 'none'; grid_color?: string; background?: string; plot_background?: string
}
export interface Axis {
  color?: string                       // цвет правой шкалы под один ряд; пусто — по умолчанию
  style?: AxisStyle                    // ручное оформление оси (конструктор): знаки, шрифт, размеры
  label: string; unit: string; scale: 'value' | 'log' | 'time' | 'category'; inverse: boolean; from_zero: boolean
  step: number | null; categories: string[] | null; minimum: number | null; maximum: number | null
}
export interface Series {
  name: string; kind: 'points' | 'line' | 'bar' | 'box'; group: string; dashed: boolean; dash: string; width: number
  legend: boolean; tooltip: string
  color: string; symbol: 'circle' | 'square' | 'diamond' | 'triangle'; hollow: boolean; opacity: number
  x: Cell[]; y: Cell[]; ids: string[] | null; labels: string[] | null; dataset: string | null
  markers: boolean; axis: 'y' | 'y2' | 'y3' | 'y4' | 'y5'; stack?: string
  total: number      // точек в серии на самом деле; если больше x.length — линия прорежена (М4: пики и провалы сохранены)
  facets: Record<string, string> | null     // признаки для легенды рядами: {'Скважина': '№ 101', 'Период': '2024'}
  captions?: string[] | null                // текст над каждой точкой (подписи причин отсутствия замеров)
  look?: Look                              // личный вид ряда из окна «Настройка» (только на клиенте)
}
/** Точки серии в видимом окне оси X (ответ /window): `window` — сколько их в окне до прореживания. */
export type WindowSeries = Pick<Series, 'x' | 'y' | 'ids' | 'labels' | 'total'> & { window: number }
export interface WindowReply { chart: string; revision: number; series: Record<string, WindowSeries> }
export interface ChartEvent { x: string | number; label: string; kind: 'gdi' | 'regime' | 'repair' | 'peak' | 'other'; well: string }
export interface Chart {
  id: string; title: string; x: Axis; y: Axis; y2: Axis | null; y3?: Axis | null; y4?: Axis | null; y5?: Axis | null; series: Series[]; crosshair: boolean
  events?: ChartEvent[]
  style?: ChartStyle
}
export interface Stat { label: string; value: string; hint: string }
export interface Note { text: string; level: 'info' | 'warning' }
export interface Result { tables: Table[]; charts: Chart[]; notes: Note[]; elapsed_ms: number; revision: number; summary?: Stat[] }
export interface SavedState { panel: Params | null; history: { date: string; params: Params }[] }
export interface ExclusionChange { added: number; removed: number; excluded: number }

export type Params = Record<string, unknown>

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'Нет связи с ядром. Проверьте, что окно сервера открыто.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.error ?? `Ошибка ${response.status}`)
  }
  return response
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await send(path, init)).json() as Promise<T>
}

const json = (method: string, body: unknown, signal?: AbortSignal): RequestInit =>
  ({ method, signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

async function download(path: string, body: unknown) {
  const response = await send(path, json('POST', body))
  const header = response.headers.get('Content-Disposition') ?? ''
  const match = /filename\*=UTF-8''([^;]+)/.exec(header)
  const name = match ? decodeURIComponent(match[1]) : 'atlas'
  const url = URL.createObjectURL(await response.blob())
  const a = document.createElement('a')
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** PNG графика для буфера обмена: тот же рисунок, что и «Скачать» (цвета, легенда, подписи), без сохранения файла. */
async function chartPng(path: string, body: unknown): Promise<Blob> {
  return (await send(path, json('POST', body))).blob()
}

export const LARGE_DEMO_HINT = 'Синтетика для проверки скорости: отбор и закачка 1 000 000 строк, ГДИ 300 000, '
  + 'реагирование 200 000, кроссплот 500 000 пар. Создание занимает 10–20 секунд.'

export const api = {
  modules: () => request<ModuleSpec[]>('/api/modules'),
  projects: () => request<Project[]>('/api/projects'),
  createDemo: (large = false) => request<{ id: string }>('/api/projects/demo', json('POST', { large })),
  options: (project: string, dataset: string, column: string) =>
    request<string[]>(`/api/projects/${project}/options?dataset=${encodeURIComponent(dataset)}&column=${encodeURIComponent(column)}`),
  projectWells: (project: string) => request<{ wells: string[] }>(`/api/projects/${project}/wells`).then(r => r.wells),
  appLinks: () => request<{ maps_url: string }>('/api/app/links'),
  run: (module: string, project: string, params: Params, signal?: AbortSignal, thin = true) =>
    request<Result>(`/api/modules/${module}/run`, json('POST', { project, params, thin }, signal)),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  saveSettings: (id: string, values: Record<string, unknown>) =>
    request<Project>(`/api/projects/${id}/settings`, json('PATCH', { values })),
  exclude: (id: string, dataset: string, add: string[], remove: string[], reason: string) =>
    request<ExclusionChange>(`/api/projects/${id}/exclusions`, json('POST', { dataset, add, remove, reason })),
  assignGroups: (id: string, changes: Assignments, action: string) =>
    request<Project>(`/api/projects/${id}/groups`, json('POST', { changes, action })),
  assignCategories: (id: string, changes: Assignments) =>
    request<Project>(`/api/projects/${id}/object-categories`, json('POST', { changes })),
  undo: (id: string) => request<ExclusionChange>(`/api/projects/${id}/exclusions/undo`, json('POST', {})),
  savedState: (id: string, module: string, panel = 0) =>
    request<SavedState>(`/api/projects/${id}/state/${module}?panel=${panel}`),
  saveState: (id: string, module: string, params: Params, panel = 0) =>
    request<Project>(`/api/projects/${id}/state/${module}`, json('POST', { params, panel })),
  paramOptions: (module: string, project: string, param: string, params: Params, signal?: AbortSignal) =>
    request<string[]>(`/api/modules/${module}/options`, json('POST', { project, param, params }, signal)),
  catalog: <T,>(module: string, project: string) =>
    request<T>(`/api/modules/${module}/catalog`, json('POST', { project })),
  window: (module: string, project: string, params: Params, chart: string, x0: number, x1: number, raw: boolean, revision: number) =>
    request<WindowReply>(`/api/modules/${module}/window`, json('POST', { project, params, chart, x0, x1, raw, revision })),
  table: (module: string, project: string, params: Params, id: string) =>
    request<Table>(`/api/modules/${module}/table`, json('POST', { project, params, id })),
  exportChart: (module: string, project: string, params: Params, chart: string, format: string, dpi: number) =>
    download(`/api/modules/${module}/export`, { project, params, target: 'chart', id: chart, format, dpi }),
  chartPng: (module: string, project: string, params: Params, chart: string) =>
    chartPng(`/api/modules/${module}/export`, { project, params, target: 'chart', id: chart, format: 'png', dpi: 300 }),
  exportTables: (module: string, project: string, params: Params, table?: string, format: 'xlsx' | 'csv' = 'xlsx') =>
    download(`/api/modules/${module}/export`, { project, params, target: 'tables', id: table, format }),
}

export function defaults(spec: ModuleSpec): Params {
  return Object.fromEntries(spec.params.map(p => [p.name, p.default]))
}

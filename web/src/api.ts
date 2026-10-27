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
  requires_dataset: string
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
  target: 'groups' | 'object-categories' | 'well-categories' | 'gis-comments'   // куда уходят назначения: группы скважин, категории объектов кроссплота или ручные категории скважин фонда
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
  fill?: boolean; step?: boolean            // линия с заливкой (область) и ступенчатая линия (конструктор графиков)
  total: number      // точек в серии на самом деле; если больше x.length — линия прорежена (М4: пики и провалы сохранены)
  facets: Record<string, string> | null     // признаки для легенды рядами: {'Скважина': '№ 101', 'Период': '2024'}
  captions?: string[] | null                // текст над каждой точкой (подписи причин отсутствия замеров)
  values?: (number | null)[] | null         // третье значение точки: по нему красятся точки (шкала цвета справа)
  values_label?: string
  segments?: string[] | null                // подпись внутри каждого сегмента столбца стопки (число скважин)
  look?: Look                              // личный вид ряда из окна «Настройка» (только на клиенте)
}
/** Точки серии в видимом окне оси X (ответ /window): `window` — сколько их в окне до прореживания. */
export type WindowSeries = Pick<Series, 'x' | 'y' | 'ids' | 'labels' | 'values' | 'total'> & { window: number }
export interface WindowReply { chart: string; revision: number; series: Record<string, WindowSeries> }
export interface ChartBand { first: number; last: number; label: string; shaded: boolean }
export interface ChartEvent { x: string | number; label: string; kind: 'gdi' | 'regime' | 'repair' | 'peak' | 'other'; well: string }
export interface ChartTable { rows: string[]; columns: string[]; cells: string[][]; colors: string[]; swatches: boolean; aligned?: boolean }
export interface HeatMap {
  rows: string[]; columns: string[]; values: (number | null)[][]; texts: string[][]
  unit: string; maximum: number | null; missing_text: string
}
export interface WellStrips {
  rows: string[]; groups: string[]; columns: string[]; cells: (number | null)[][]; counts: number[]
  layout: 'matrix' | 'panels'; missing_text: string
}
export interface Chart {
  id: string; title: string; x: Axis; y: Axis; y2: Axis | null; y3?: Axis | null; y4?: Axis | null; y5?: Axis | null; series: Series[]; crosshair: boolean
  events?: ChartEvent[]
  bands?: ChartBand[]                       // годы над категориями оси X: подпись и серая/белая подложка
  callouts?: 'box' | 'dot'                  // узкие сегменты с подписью: выноска в рамке или точка (числа — в table)
  table?: ChartTable | null                 // таблица под графиком
  strips?: WellStrips | null                // скважины × сезоны (матрица или панели по ГСП)
  heat?: HeatMap | null                     // тепловая карта вместо рядов (ГСП × сезоны)
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

/** Скачивает файл; возвращает заметку ядра из заголовка X-Atlas-Notes (например, какие скважины пропущены). */
async function downloadNotes(path: string, body: unknown): Promise<string> {
  const response = await send(path, json('POST', body))
  const header = response.headers.get('Content-Disposition') ?? ''
  const match = /filename\*=UTF-8''([^;]+)/.exec(header)
  const name = match ? decodeURIComponent(match[1]) : 'atlas'
  const url = URL.createObjectURL(await response.blob())
  const a = document.createElement('a')
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return decodeURIComponent(response.headers.get('X-Atlas-Notes') ?? '')
}

async function download(path: string, body: unknown): Promise<void> {
  await downloadNotes(path, body)
}

/** Вид графика на экране для выгрузки: оформление рядов, границы осей, масштаб по времени, скрытые пункты легенды (atlas/chart_view.py). */
export interface ChartExportView {
  looks?: Record<string, unknown>
  ranges?: Partial<Record<'y' | 'y2' | 'y3' | 'y4' | 'y5', [number, number]>>
  x?: [number, number]
  hidden?: string[]
  facets?: string[]
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
  assignWellCategories: (id: string, changes: Assignments) =>
    request<Project>(`/api/projects/${id}/well-categories`, json('POST', { changes })),
  assignGisComments: (id: string, changes: Assignments) =>
    request<Project>(`/api/projects/${id}/gis-comments`, json('POST', { changes })),
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
  exportChart: (module: string, project: string, params: Params, chart: string, format: string, dpi: number, view?: ChartExportView) =>
    download(`/api/modules/${module}/export`, { project, params, target: 'chart', id: chart, format, dpi, view }),
  chartPng: (module: string, project: string, params: Params, chart: string, view?: ChartExportView) =>
    chartPng(`/api/modules/${module}/export`, { project, params, target: 'chart', id: chart, format: 'png', dpi: 300, view }),
  exportCharts: (module: string, project: string, params: Params, layout: 'zip' | 'sheet', cols = 2) =>
    download(`/api/modules/${module}/export`, { project, params, target: 'charts', layout, cols }),
  exportTables: (module: string, project: string, params: Params, table?: string, format: 'xlsx' | 'csv' = 'xlsx') =>
    download(`/api/modules/${module}/export`, { project, params, target: 'tables', id: table, format }),
}

export function defaults(spec: ModuleSpec): Params {
  return Object.fromEntries(spec.params.map(p => [p.name, p.default]))
}

// ---- Конструктор графиков: библиотека макетов проекта и выгрузка (этап 5) ----
export interface LayoutItem { id: string; name: string; created: string; updated: string; series: number; title: string }
export interface OpenedLayout { id?: string; name?: string; layout: unknown; missing: string[] }
const lib = (project: string, tail = '') => `/api/projects/${project}/builder/layouts${tail}`
export interface SeriesWells {
  enabled: boolean; wells: string[]; with_data: string[]; groups: { name: string; wells: string[] }[]; limit: number; formats: Record<string, string>
}
export interface ModelItem { id: string; name: string; folder: string; selected: boolean; indicators: boolean }
export interface ModelList { available: boolean; error: string; folders: string[]; models: ModelItem[]; cubes: boolean; cubes_from: string; cubes_to: string; cells: CellsConfig }
export interface CellsConfig { dates: string[]; k_from: number; k_to: number; max_points: number }
export interface CriterionCfg { logic: string; value: number; fallback: number }
export interface CriterionPreset extends CriterionCfg { id: string; title: string; formula: string }
export interface CriterionView { criterion: CriterionCfg; formula: string; label: string; max_variants: number; presets: CriterionPreset[]; variants: CriterionCfg[] }
export const builderApi = {
  refreshCubes: (project: string) => request<ModelList>(`/api/projects/${project}/builder/models/refresh`, json('POST', {})),
  restarts: (project: string, model: string) =>
    request<{ dates: string[] }>(`/api/projects/${project}/builder/models/restarts?model=${encodeURIComponent(model)}`),
  models: (project: string) => request<ModelList>(`/api/projects/${project}/builder/models`),
  criterion: (project: string) => request<CriterionView>(`/api/projects/${project}/builder/criterion`),
  chooseModels: (project: string, selected: string[], extra: { cubes?: boolean; cubes_from?: string; cubes_to?: string; cells?: CellsConfig; criterion?: CriterionCfg; criterion_variants?: CriterionCfg[] } = {}) =>
    request<ModelList>(`/api/projects/${project}/builder/models`, json('POST', { selected, ...extra })),
  seriesWells: (project: string, layout: unknown) =>
    request<SeriesWells>(`/api/projects/${project}/builder/series/wells`, json('POST', { layout })),
  series: (project: string, body: { layout: unknown; wells: string[]; format: string; orientation: string; title: string }) =>
    downloadNotes(`/api/projects/${project}/builder/series`, body),
  list: (project: string) => request<{ items: LayoutItem[] }>(lib(project)).then(r => r.items),
  save: (project: string, name: string, layout: unknown) =>
    request<{ item: LayoutItem; items: LayoutItem[] }>(lib(project), json('POST', { name, layout })),
  open: (project: string, id: string) => request<Required<OpenedLayout>>(lib(project, '/' + id)),
  update: (project: string, id: string, patch: { name?: string; layout?: unknown }) =>
    request<{ item: LayoutItem; items: LayoutItem[] }>(lib(project, '/' + id), json('PATCH', patch)),
  duplicate: (project: string, id: string) => request<{ item: LayoutItem; items: LayoutItem[] }>(lib(project, `/${id}/duplicate`), json('POST', {})),
  remove: (project: string, id: string) => request<{ items: LayoutItem[] }>(lib(project, '/' + id), { method: 'DELETE' }),
  importFile: (project: string, content: string, fileName: string) =>
    request<{ item: LayoutItem; items: LayoutItem[]; layout: unknown; missing: string[] }>(lib(project, '/import'), json('POST', { content, file_name: fileName })),
  exportFile: (project: string, name: string, layout: unknown) => download(lib(project, '/file'), { name, layout }),
  word: (project: string, body: { layout: unknown; title: string; caption: string; orientation: string }) =>
    download(`/api/projects/${project}/builder/word`, body),
  data: (project: string, layout: unknown, format: 'xlsx' | 'csv') =>
    download('/api/modules/builder/export', { project, params: { layout }, target: 'chart', id: 'builder', format, dpi: 300 }),
}

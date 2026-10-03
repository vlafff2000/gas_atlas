// Типы повторяют atlas/contract.py. Интерфейс не знает о конкретных модулях.

export type DatasetKind = string

export interface Option { value: unknown; label: string }
export interface Param {
  name: string
  label: string
  kind: 'number' | 'integer' | 'boolean' | 'choice' | 'multi' | 'date' | 'text'
  default: unknown
  help: string
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

export interface Column { key: string; label: string; unit: string; decimals: number | null; kind: 'text' | 'number' | 'date' }
export type Cell = string | number | boolean | null
export interface TableAction {
  kind: 'exclude' | 'assign'; dataset: string | null; id_column: string; label: string; reason: string
  checked_column: string; reason_editable: boolean; ids: string[]; checked: boolean[] | null
  // assign: значения полей по строкам, какие из них правятся, что отправлять, запись журнала
  fields: string[]; editable: string[]; submit: 'changed' | 'all'; journal: string; values: Record<string, Cell[]>
}
export type Assignments = Record<string, Record<string, string>>
export interface Table {
  id: string; title: string; columns: Column[]; rows: Cell[][]; count: number
  note: string; collapsed: boolean; action: TableAction | null
}
export interface Axis {
  label: string; unit: string; scale: 'value' | 'log' | 'time' | 'category'; inverse: boolean; from_zero: boolean
  step: number | null; categories: string[] | null
}
export interface Series {
  name: string; kind: 'points' | 'line' | 'bar'; group: string; dashed: boolean; dash: string; width: number
  legend: boolean; tooltip: string
  color: string; symbol: 'circle' | 'square' | 'diamond' | 'triangle'; hollow: boolean
  x: Cell[]; y: Cell[]; ids: string[] | null; labels: string[] | null; dataset: string | null
}
export interface Chart { id: string; title: string; x: Axis; y: Axis; series: Series[]; crosshair: boolean }
export interface Note { text: string; level: 'info' | 'warning' }
export interface Result { tables: Table[]; charts: Chart[]; notes: Note[]; elapsed_ms: number; revision: number }
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

export const api = {
  modules: () => request<ModuleSpec[]>('/api/modules'),
  projects: () => request<Project[]>('/api/projects'),
  createDemo: () => request<{ id: string }>('/api/projects/demo', { method: 'POST' }),
  options: (project: string, dataset: string, column: string) =>
    request<string[]>(`/api/projects/${project}/options?dataset=${encodeURIComponent(dataset)}&column=${encodeURIComponent(column)}`),
  run: (module: string, project: string, params: Params, signal?: AbortSignal) =>
    request<Result>(`/api/modules/${module}/run`, json('POST', { project, params }, signal)),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  saveSettings: (id: string, values: Record<string, unknown>) =>
    request<Project>(`/api/projects/${id}/settings`, json('PATCH', { values })),
  exclude: (id: string, dataset: string, add: string[], remove: string[], reason: string) =>
    request<ExclusionChange>(`/api/projects/${id}/exclusions`, json('POST', { dataset, add, remove, reason })),
  assignGroups: (id: string, changes: Assignments, action: string) =>
    request<Project>(`/api/projects/${id}/groups`, json('POST', { changes, action })),
  undo: (id: string) => request<ExclusionChange>(`/api/projects/${id}/exclusions/undo`, json('POST', {})),
  savedState: (id: string, module: string, panel = 0) =>
    request<SavedState>(`/api/projects/${id}/state/${module}?panel=${panel}`),
  saveState: (id: string, module: string, params: Params, panel = 0) =>
    request<Project>(`/api/projects/${id}/state/${module}`, json('POST', { params, panel })),
  paramOptions: (module: string, project: string, param: string, params: Params, signal?: AbortSignal) =>
    request<string[]>(`/api/modules/${module}/options`, json('POST', { project, param, params }, signal)),
  exportChart: (module: string, project: string, params: Params, chart: string, format: string, dpi: number) =>
    download(`/api/modules/${module}/export`, { project, params, target: 'chart', id: chart, format, dpi }),
  exportTables: (module: string, project: string, params: Params, table?: string, format: 'xlsx' | 'csv' = 'xlsx') =>
    download(`/api/modules/${module}/export`, { project, params, target: 'tables', id: table, format }),
}

export function defaults(spec: ModuleSpec): Params {
  return Object.fromEntries(spec.params.map(p => [p.name, p.default]))
}

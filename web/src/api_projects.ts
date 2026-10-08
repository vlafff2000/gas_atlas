// Клиент API разделов «Проекты», «Настройки» и «Экспорт» (atlas/api_projects.py, atlas/api_export.py).
import { ApiError, type Chart, type Project } from './api'

export type Form = Record<string, unknown>

export interface SavedExport { name: string; bytes: number; modified: string }
export interface ProjectDetails extends Project {
  version: string | null
  menu: string[]
  panels: Record<string, unknown>
  pages: string[]
  default_pages: string[]
  visible_pages: string[]
  exports: SavedExport[]
  log: boolean
}
export interface RestorePreview {
  kind: 'backup' | 'legacy'
  info: Record<string, unknown>
  count: number
  files?: { name: string; bytes: number }[]
  columns?: string[]
  rows?: string[][]
}
export interface DataVersion {
  snapshot: string; date: string; action: string; revision: number | null; rows: Record<string, number>
  current: boolean; before: string | null
}
export interface Caption { section: string; start: number; template: string }
export interface ExportChoices {
  modules: { id: string; label: string }[]
  default_modules: string[]
  wells: Record<string, string[]>
  groups: Record<string, string[]>
  mapping: Record<string, string>
  periods?: Record<'withdrawal' | 'injection', string[]>
  gdi_seasons?: string[]
  gdi_methods?: string[]
  /** «Вынос воды и водный фактор»: сезоны отбора и (если есть) варианты оси X. */
  water_carry?: { periods: string[]; xaxis?: { value: string; label: string }[]; xaxis_default?: string }
  horizons?: string[]
  working?: string[]
  response_dates?: string[]
  dashboard_periods?: Record<'withdrawal' | 'injection', string[]>
  asof?: string
  dashboard_charts?: { id: string; label: string }[]
  two_panels: Record<string, boolean>
  captions: Record<string, Caption>
  presets: Record<string, Form>
  style: Record<string, boolean>
  /** Данные ГГХ проекта: скважины, их горизонты и число замеров (блок «Графики ГГХ для отчёта»). */
  ggh?: { wells: string[]; horizon_of: Record<string, string>; points: Record<string, number> }
}
export interface ExportPlan { modules: string[]; charts: { name: string; module: string }[]; tables: string[]; note: string }
export interface ExportResult {
  files: string[]; planned: number; completed: number; chart_files: number
  errors: { 'График': string; 'Формат': string; 'Ошибка': string }[]
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
const request = async <T,>(path: string, init?: RequestInit): Promise<T> => (await send(path, init)).json() as Promise<T>
const json = (method: string, body: unknown): RequestInit =>
  ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const upload = (file: File): RequestInit =>
  ({ method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file })
const P = (pid: string) => `/api/projects/${pid}`

/** Скачивание через ссылку: большой файл не держится в памяти страницы. */
export function saveLink(url: string) {
  const a = document.createElement('a')
  a.href = url; a.download = ''; document.body.appendChild(a); a.click(); a.remove()
}

export const projectsApi = {
  create: (name: string) => request<Project>('/api/projects', json('POST', { name })),
  details: (pid: string) => request<ProjectDetails>(`${P(pid)}/details`),
  rename: (pid: string, name: string, revision: number) => request<Project>(`${P(pid)}/rename`, json('POST', { name, revision })),
  copy: (pid: string) => request<Project>(`${P(pid)}/copy`, json('POST', {})),
  settings: (pid: string, values: Record<string, unknown>) =>
    request<Project>(`${P(pid)}/settings`, json('PATCH', { values })),
  versions: (pid: string) => request<{ versions: DataVersion[]; keep: number }>(`${P(pid)}/versions`),
  rollback: (pid: string, snapshot: string, revision: number) =>
    request<Project>(`${P(pid)}/rollback`, json('POST', { snapshot, revision })),
  backupUrl: (pid: string, originals: boolean) => `${P(pid)}/backup?originals=${originals ? 1 : 0}`,
  restorePreview: (file: File) =>
    request<RestorePreview>(`/api/projects/restore/preview?name=${encodeURIComponent(file.name)}`, upload(file)),
  restore: (file: File) => request<Project>(`/api/projects/restore?name=${encodeURIComponent(file.name)}`, upload(file)),
  exportUrl: (pid: string, name: string) => `${P(pid)}/exports/${encodeURIComponent(name)}`,
  logUrl: '/api/log',
}

export interface WordPreview {
  documents: { id: string; label: string; charts: number }[]; doc: number; page: number; pages: number; exact: boolean
  page_mm: [number, number]; image_mm: [number, number]; png: string
}

export const exportApi = {
  choices: (pid: string, exclusions: boolean) => request<ExportChoices>(`${P(pid)}/export/form?exclusions=${exclusions ? 1 : 0}`),
  plan: (pid: string, form: Form) => request<ExportPlan>(`${P(pid)}/export/plan`, json('POST', { form })),
  preview: async (pid: string, form: Form, chart: string) =>
    URL.createObjectURL(await (await send(`${P(pid)}/export/preview`, json('POST', { form, chart }))).blob()),
  extras: (pid: string, form: Form) => request<{ charts: { name: string; module: string }[] }>(`${P(pid)}/export/extras`, json('POST', { form })),
  extrasPreview: async (pid: string, form: Form, chart: string) =>
    URL.createObjectURL(await (await send(`${P(pid)}/export/extras-preview`, json('POST', { form, chart }))).blob()),
  chart: (pid: string, form: Form, chart: string) => request<Chart>(`${P(pid)}/export/chart`, json('POST', { form, chart })),
  series: (pid: string, form: Form, chart?: string) => request<{ series: Record<string, string[]>; labels: Record<string, Record<string, string>>; chart: string[] }>(`${P(pid)}/export/series`, json('POST', { form, chart })),
  archive: (pid: string, form: Form) => request<ExportResult>(`${P(pid)}/export/archive`, json('POST', { form })),
  word: (pid: string, form: Form) => request<ExportResult>(`${P(pid)}/export/word`, json('POST', { form })),
  wordPreview: (pid: string, form: Form, doc: number, page: number) =>
    request<WordPreview>(`${P(pid)}/export/word-preview`, json('POST', { form, doc, page })),
  pack: (pid: string, form: Form) => request<ExportResult>(`${P(pid)}/export/pack`, json('POST', { form })),
  ggh: (pid: string, form: Form) => request<ExportResult>(`${P(pid)}/export/ggh`, json('POST', { form })),
  bundle: (pid: string, files: string[]) => request<{ file: string }>(`${P(pid)}/export/bundle`, json('POST', { files })),
  savePreset: (pid: string, name: string, form: Form) => request<Project>(`${P(pid)}/export/presets`, json('POST', { name, form })),
  sync: (pid: string) => request<Form>(`${P(pid)}/export/sync`),
}

/** Разделы 5.8, которым соответствуют модули и страницы 6: скрытые в «Составе меню» не показываются. */
const PAGE_OF: Record<string, string> = {
  production: 'Производительность скважин', histograms: 'Гистограммы по эксплуатации скважин', gdi: 'ГДИ',
  response: 'Графики реагирования', pressure: 'Кроссплот давлений', wells: 'Поскважинный анализ', groups: 'Группы', fund: 'Аналитика фонда',
  '@import': 'Импорт данных', '@export': 'Экспорт', exclusions: 'Исключенные точки', filter_history: 'История фильтра', overview: 'Обзор',
  '@projects': 'Проекты', '@passport': 'Паспорт скважины', '@settings': 'Настройки',
}
export function inMenu(id: string, project: Project | null): boolean {
  const page = PAGE_OF[id]
  const menu = (project as (Project & { menu?: string[] }) | null)?.menu
  return !page || !menu || page === 'Настройки' || menu.includes(page)
}

export const PROJECT_PAGES = [
  { id: '@passport', title: 'Паспорт скважины' },
  { id: '@export', title: 'Экспорт' },
  { id: '@projects', title: 'Проекты' },
  { id: '@settings', title: 'Настройки' },
]

export function bytes(n: number): string {
  return n < 1024 ** 2 ? `${Math.max(1, Math.round(n / 1024))} КБ` : `${(n / 1024 ** 2).toFixed(1).replace('.', ',')} МБ`
}

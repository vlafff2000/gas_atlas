// Клиент раздела «Импорт данных» (atlas/api_import.py).
import { ApiError, type Project, type Table } from './api'

export interface Choice { value: string; label: string }
export interface Upload { token: string; name: string; bytes: number; binary: boolean; format: string; sheets: string[]; error: string }
export interface FileOptions { encoding: string; delimiter: string }
export interface Spec {
  enabled: boolean; module?: string; header: number; mapping: Record<string, number>; wide: boolean
  wellcols: number[]; names: Record<string, string>; fond_pairs: number[][]; fonds?: boolean
}
export interface SheetState {
  empty: boolean; sheet: string; header: number; detected_header: number; max_header: number
  labels: string[]; preview: { columns: string[]; rows: string[][] }
  module: string; suggested?: string; effective: string | null; wide: boolean; wide_allowed: boolean
  fields: string[]; mapping: Record<string, number>; layout_mapping: Record<string, number>
  wellcols: number[]; fond_pairs: number[][]; remembered: boolean
}
export interface SheetRequest {
  token: string; sheet: string; encoding?: string; delimiter?: string; mode?: string
  header?: number | null; module?: string | null; pressure?: boolean; fonds?: boolean
}
export interface ImportOptions {
  types: Choice[]; sheet_types: Choice[]; fields: Choice[]; pressure_fields: Record<string, string>
  roles: string[]; duplicates: Choice[]
}
export interface SheetChoice { use?: boolean; module?: string; spec?: Spec | null }
export interface SimpleRow {
  token: string; file: string; sheet: string; use: boolean; module: string; found: string | null
  fields: string; status: string; book: boolean; custom: boolean; binary: boolean
}
export interface SimpleInspect {
  rows: SimpleRow[]; problems: string[]; errors: string[]; blocked: boolean
  counts: { files: number; sheets: number; use: number; unknown: number }
}
export interface Book { fact: string; models: string[]; fonds: string[]; object: string }
export interface FileInfo { token: string; name: string; binary: boolean; error: string; format?: string; sheets: string[]; book: Book | null }
export interface CheckFile {
  token: string; encoding?: string; delimiter?: string
  choices?: Record<string, SheetChoice>
  sheets?: Record<string, Spec>
  pressure_book?: Book & { duplicate: string; sheets: Record<string, Spec> }
}
export interface CheckBody {
  view: 'simple' | 'detailed'; mode: string; kind: string; production_unit: string; gdi_unit: string
  pressure_unit: string; files: CheckFile[]
}
export interface Pending {
  id: string; counts: { module: string; label: string; rows: number }[]; rejected: number; warnings: number
  issues: Table | null; issues_count: number; previews: Table[]; policies: Choice[]
}
export interface PressureRow {
  'Исп.': boolean; 'Файл': string; 'Лист': string; 'Роль': string; 'Объект': string; 'Сценарий': string
  'Значений': number; 'Скважин': number; 'Период': string; 'Структура': string; 'Статус': string
  token: string; binary: boolean
}
export interface PressureChoice { use?: boolean; role?: string; object?: string; scenario?: string }
export interface PressureInspect {
  bad: string[]; rows: PressureRow[]; errors: string[]; warnings: string[]; duplicates: Choice[]
  counts?: { files: number; sheets: number; use: number; objects: number }
  ready: null | {
    id: string; text: string; summary: Table; notes: Table | null; modes: Choice[]
    existing: null | { objects: number; replaced: string[] }
  }
}
export interface Applied { message: string; project: Project; duplicates?: number }

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
const post = async <T,>(path: string, body: unknown, signal?: AbortSignal): Promise<T> =>
  (await send(path, { method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json()

async function save(response: Response, fallback: string) {
  const header = response.headers.get('Content-Disposition') ?? ''
  const match = /filename\*=UTF-8''([^;]+)/.exec(header)
  const name = match ? decodeURIComponent(match[1]) : fallback
  const url = URL.createObjectURL(await response.blob())
  const a = document.createElement('a')
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const importApi = {
  options: async () => (await send('/api/import/options')).json() as Promise<ImportOptions>,
  upload: async (file: Blob, name: string) =>
    (await send(`/api/import/files?name=${encodeURIComponent(name)}`, { method: 'POST', body: file })).json() as Promise<Upload>,
  inspectSimple: (body: { mode: string; files: CheckFile[] }, signal?: AbortSignal) =>
    post<SimpleInspect>('/api/import/inspect', { view: 'simple', ...body }, signal),
  inspectDetailed: (body: { mode: string; files: CheckFile[] }, signal?: AbortSignal) =>
    post<{ files: FileInfo[] }>('/api/import/inspect', { view: 'detailed', ...body }, signal),
  sheet: (body: SheetRequest, signal?: AbortSignal) => post<SheetState>('/api/import/sheet', body, signal),
  profile: (body: SheetRequest & { spec: Spec; remember: boolean }) =>
    post<{ remembered: boolean; profiles: number }>('/api/import/profile', body),
  templates: async () => (await send('/api/import/templates')).json() as Promise<{ name: string; kind: string }[]>,
  template: async (name: string) => save(await send(`/api/import/templates/${encodeURIComponent(name)}`), name),
  check: (project: string, body: CheckBody) => post<Pending>(`/api/projects/${project}/import/check`, body),
  apply: (project: string, pending: string, policy: string, accept: boolean) =>
    post<Applied>(`/api/projects/${project}/import/apply`, { pending, policy, accept }),
  table: async (project: string, pending: string, table: string, format: 'xlsx' | 'csv') =>
    save(await send(`/api/projects/${project}/import/table`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pending, table, format }),
    }), table + '.' + format),
  pressure: (project: string, body: {
    files: CheckFile[]; choices: Record<string, Record<string, PressureChoice>>
    overrides: Record<string, Record<string, Spec>>; duplicate: string
  }, signal?: AbortSignal) => post<PressureInspect>(`/api/projects/${project}/import/pressure`, body, signal),
  pressureApply: (project: string, pending: string, mode: string) =>
    post<Applied>(`/api/projects/${project}/import/pressure/apply`, { pending, mode }),
  /** «Новый проект»: POST /api/projects (раздел «Проекты»). */
  createProject: (name: string) => post<{ id: string }>('/api/projects', { name }),
}

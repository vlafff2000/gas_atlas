// «Паспорт скважины»: atlas/api_passport.py.
import { ApiError, chartPng, download, type Chart, type ChartExportView, type Project, type Table } from './api'

export interface PassportInfo {
  wells: string[]
  shown: string[]                         // скважины после фильтра вкладки
  groups: Record<string, string>          // скважина → группа
  well: string | null
  sections: { value: string; label: string }[]
  periods: Record<string, { label: string; options: string[]; default: string[] }>
  comment: string
  revision: number
  note?: string
}

export interface Shape { t: 'rect' | 'line' | 'poly'; x0: number; x1: number; y0: number; y1: number; pts?: [number, number][]; fill?: string; pattern?: string; stroke?: string; width?: number; name: string }
export interface Tag { y: number; at: number; text: string; color: string }
export interface Schematic {
  items: { kind: string; label: string; top: number; bottom: number }[]
  notes: string[]; skipped: string[]; top: number; bottom: number; bottom_m: number | null
  shapes?: Shape[]; labels?: Tag[]; covered_m?: number
}
export interface Kpi { label: string; value: number | null; text?: string; unit?: string; digits?: number; hint?: string; extra?: string }
export interface SeasonRow { kind: 'withdrawal' | 'injection'; period: string; volume: number | null; days: number; max_rate: number | null
  max_date: string; mean_rate: number | null; hours: number | null; water: number | null; coverage: number | null; end: string }
export interface GdiRow { date: string; method: string; a: number | null; b: number | null; r2: number | null; q_max: number | null
  q_free: number | null; reliable: boolean; note: string }
export interface GdiDiagram { date: string; method: string; a: number | null; b: number | null; r2: number | null; reliable: boolean; points: number[][] }
export interface DailySeries { date: string[]; volume: (number | null)[]; hours: (number | null)[]; period: string[] }
export interface KrsInfo { works: { year: number | null; type: string; detail: string }[]; loaded: boolean; note: string
  priority: { value: number | null; reason: string; sand: string } | null }
export interface PassportCard {
  well: string; group: string; construction_date: string; kpi: Kpi[]; seasons: SeasonRow[]; season_options: string[]; gdi: GdiRow[]; gdi_diagrams: GdiDiagram[]; daily: Record<'withdrawal' | 'injection', DailySeries>; krs: KrsInfo
  schematic: Schematic; notes: string[]; charts: Chart[]; tables: Table[]
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

const post = (body: unknown): RequestInit =>
  ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const passportApi = {
  /** Выгрузка графика или таблицы паспорта (общий экспорт ядра): файл через наш проводник, PNG — для буфера обмена. */
  exportFile: (project: string, well: string, seasons: string[], target: 'chart' | 'table', id: string, format: string, dpi = 300, view?: ChartExportView) =>
    download(`/api/projects/${project}/passport/export`, { well, seasons, target, id, format, dpi, view }),
  exportBlob: (project: string, well: string, seasons: string[], target: 'chart' | 'table', id: string, format: string, dpi = 300, view?: ChartExportView) =>
    chartPng(`/api/projects/${project}/passport/export`, { well, seasons, target, id, format, dpi, view }),
  info: async (project: string, well?: string, filter?: unknown, signal?: AbortSignal) =>
    (await send(`/api/projects/${project}/passport?well=${encodeURIComponent(well ?? '')}&filter=${encodeURIComponent(JSON.stringify(filter ?? null))}`, { signal }))
      .json() as Promise<PassportInfo>,
  card: async (project: string, well: string, seasons: string[], signal?: AbortSignal) =>
    (await send(`/api/projects/${project}/passport/card?well=${encodeURIComponent(well)}&seasons=${encodeURIComponent(JSON.stringify(seasons))}`, { signal }))
      .json() as Promise<PassportCard>,
  saveComment: async (project: string, well: string, comment: string, revision?: number) =>
    (await send(`/api/projects/${project}/passport/comment`, post({ well, comment, revision })))
      .json() as Promise<Project & { comment: string }>,
  /** Формирует PDF (сохраняется и в выгрузках проекта) и отдаёт его браузеру. */
  pdf: async (project: string, well: string, sections: string[], periods: Record<string, string[]>, comment: string, card = true, wells?: string[], seasons: string[] = []) => {
    const response = await send(`/api/projects/${project}/passport/pdf`, post({ well, wells, sections, periods, comment, card, seasons }))
    const match = /filename\*=UTF-8''([^;]+)/.exec(response.headers.get('Content-Disposition') ?? '')
    const name = match ? decodeURIComponent(match[1]) : (wells && wells.length > 1 ? `Паспорта_скважин_${wells.length}.zip` : `Паспорт_скважины_${well}.pdf`)
    const url = URL.createObjectURL(await response.blob())
    const a = document.createElement('a')
    a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    return name
  },
}

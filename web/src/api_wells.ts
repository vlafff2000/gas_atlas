// Пресеты скважин и фильтр скважин: atlas/api_well_sets.py. Группы, фонды и опорная сетка — из проекта; пользовательские — в ~/.pxg.
import { ApiError } from './api'

export interface WellPreset { id: string; kind: 'group' | 'fund' | 'grid' | 'user'; label: string; wells: string[] }
// legacy — сколько пресетов осталось в прежней общей папке ~/.pxg (их можно перенести в проект)
interface PresetList { presets: WellPreset[]; legacy?: number }

// Фильтр скважин проекта: что выбрано и сколько скважин остаётся (сам фильтр — настройка проекта well_filter).
export interface WellFilterStatus { groups: string[]; wells: string[]; total: number; shown: number; hidden: number }

async function send<T = PresetList>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(path, init) } catch {
    throw new ApiError(0, 'Нет связи с ядром. Проверьте, что окно сервера открыто.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.error ?? `Ошибка ${response.status}`)
  }
  return response.json()
}

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export const wellFilterApi = {
  status: (project: string) => send<WellFilterStatus>(`/api/projects/${project}/well-filter`),
}

export const wellPresetApi = {
  list: (project: string) => send(`/api/projects/${project}/well-presets`),
  save: (project: string, name: string, wells: string[]) =>
    send(`/api/projects/${project}/well-presets`, json('POST', { name, wells })),
  remove: (project: string, id: string) =>
    send(`/api/projects/${project}/well-presets/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  importLegacy: (project: string) => send(`/api/projects/${project}/well-presets/import-legacy`, { method: 'POST' }),
}

// «Фонды скважин»: atlas/api_fund.py.
import { ApiError } from './api'

export interface FundInfo { id: string; label: string }
export interface FundRow {
  well: string; group: string; fund: string; hint: string; reason: string; manual: boolean; sources: string[]
}
export interface FundTable { funds: FundInfo[]; wells: FundRow[]; revision: number }

async function send(path: string, init?: RequestInit): Promise<FundTable> {
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

export const fundApi = {
  get: (project: string) => send(`/api/projects/${project}/well-fund`),
  /** fund = id фонда или 'auto' (вернуть подсказку программы). */
  assign: (project: string, changes: Record<string, string>, revision?: number) =>
    send(`/api/projects/${project}/well-fund`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ changes, revision }),
    }),
}

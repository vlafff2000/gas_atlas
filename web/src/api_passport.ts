// «Паспорт скважины»: atlas/api_passport.py.
import { ApiError, type Project } from './api'

export interface PassportInfo {
  wells: string[]
  well: string | null
  sections: { value: string; label: string }[]
  periods: Record<string, { label: string; options: string[]; default: string[] }>
  comment: string
  revision: number
  note?: string
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
  info: async (project: string, well?: string, signal?: AbortSignal) =>
    (await send(`/api/projects/${project}/passport` + (well ? `?well=${encodeURIComponent(well)}` : ''), { signal }))
      .json() as Promise<PassportInfo>,
  saveComment: async (project: string, well: string, comment: string, revision?: number) =>
    (await send(`/api/projects/${project}/passport/comment`, post({ well, comment, revision })))
      .json() as Promise<Project & { comment: string }>,
  /** Формирует PDF (сохраняется и в выгрузках проекта) и отдаёт его браузеру. */
  pdf: async (project: string, well: string, sections: string[], periods: Record<string, string[]>, comment: string) => {
    const response = await send(`/api/projects/${project}/passport/pdf`, post({ well, sections, periods, comment }))
    const match = /filename\*=UTF-8''([^;]+)/.exec(response.headers.get('Content-Disposition') ?? '')
    const name = match ? decodeURIComponent(match[1]) : `Паспорт_скважины_${well}.pdf`
    const url = URL.createObjectURL(await response.blob())
    const a = document.createElement('a')
    a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    return name
  },
}

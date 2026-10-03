// Кнопки-команды под результатом модуля (atlas/contract.py: Command) — «Восстановить все»,
// «Восстановить выбранное состояние фильтра». Адрес команды — относительно /api/projects/{проект}/.
import { ApiError, type Result } from './api'

export interface Command { label: string; path: string; body: Record<string, unknown>; confirm: string; done: string; primary: boolean }
export interface CommandOutcome { added?: number; removed?: number; excluded?: number; revision?: number }

export const commandsOf = (result: Result): Command[] => (result as Result & { commands?: Command[] }).commands ?? []

export async function runCommand(project: string, command: Command): Promise<CommandOutcome> {
  const path = command.path.replace(/^\/+/, '')
  if (path.includes('..')) throw new ApiError(400, 'Недопустимый адрес команды')
  let response: Response
  try {
    response = await fetch(`/api/projects/${project}/${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command.body),
    })
  } catch {
    throw new ApiError(0, 'Нет связи с ядром. Проверьте, что окно сервера открыто.')
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(response.status, body.error ?? `Ошибка ${response.status}`)
  return body as CommandOutcome
}

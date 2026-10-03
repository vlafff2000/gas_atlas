import { useState } from 'react'
import type { Result } from './api'
import { commandsOf, runCommand, type Command } from './api_exclusions'

interface Props {
  result: Result
  project: string
  onDone: (text: string) => Promise<void> | void
  onError: (text: string) => void
}

/** Кнопки команд модуля (Result.commands): выполнить, сообщить итог, обновить проект (пересчёт). */
export function CommandBar({ result, project, onDone, onError }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const commands = commandsOf(result)
  if (!commands.length) return null

  const execute = async (c: Command) => {
    if (c.confirm && !window.confirm(c.confirm)) return
    setBusy(c.label)
    try {
      const r = await runCommand(project, c)
      await onDone(c.done || (r.removed !== undefined ? `Возвращено: ${r.removed}, исключено: ${r.added ?? 0}.` : 'Готово.'))
    } catch (e) {
      onError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="toolbar commands">
      {commands.map(c => (
        <button key={c.label} type="button" className={c.primary ? 'primary' : 'quiet'} disabled={busy !== null}
          onClick={() => execute(c)}>
          {busy === c.label ? 'Выполняю…' : c.label}
        </button>
      ))}
    </div>
  )
}

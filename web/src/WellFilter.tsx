import { useEffect, useState } from 'react'
import { api, type Project } from './api'
import { MultiSelect } from './MultiSelect'
import { wellFilterApi, wellPresetApi, type WellFilterStatus } from './api_wells'
import './wellfilter.css'

interface Props {
  project: Project
  onProject: (p: Project) => void
}

/** Фильтр скважин проекта: группы и скважины, сквозные для всех модулей. Стоит рядом с «Скважины» в каждом модуле. */
export function WellFilter({ project, onProject }: Props) {
  const saved = (project.settings.well_filter ?? null) as { groups?: string[]; wells?: string[] } | null
  const [open, setOpen] = useState(false)
  const [groups, setGroups] = useState<string[]>([])            // черновик: применяется кнопкой «Применить»
  const [wells, setWells] = useState<string[]>([])
  const [allGroups, setAllGroups] = useState<string[]>([])
  const [allWells, setAllWells] = useState<string[]>([])
  const [status, setStatus] = useState<WellFilterStatus | null>(null)
  const [error, setError] = useState('')
  const [legacy, setLegacy] = useState(0)                       // старые пресеты общей папки, ещё не перенесённые в проект

  useEffect(() => {
    api.projectGroups(project.id).then(setAllGroups).catch(() => setAllGroups([]))
    api.projectWells(project.id).then(setAllWells).catch(() => setAllWells([]))
    wellFilterApi.status(project.id).then(setStatus).catch(() => setStatus(null))
    wellPresetApi.list(project.id).then(r => setLegacy(r.legacy ?? 0)).catch(() => setLegacy(0))
  }, [project.id, project.revision])

  const importLegacy = async () => {
    setError('')
    try {
      const r = await wellPresetApi.importLegacy(project.id)
      setLegacy(r.legacy ?? 0)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const openPanel = () => {
    setGroups(saved?.groups ?? [])
    setWells(saved?.wells ?? [])
    setError('')
    setOpen(o => !o)
  }

  // Новая настройка — новая ревизия проекта: модули пересчитываются, списки скважин обновляются.
  const apply = async (nextGroups: string[], nextWells: string[]) => {
    setError('')
    try {
      onProject(await api.saveSettings(project.id, { well_filter: { groups: nextGroups, wells: nextWells } }))
      setOpen(false)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const active = Boolean(saved && ((saved.groups?.length ?? 0) || (saved.wells?.length ?? 0)))
  const summary = !active ? 'все скважины'
    : status ? `${status.shown} из ${status.total} скв.` : 'загрузка…'
  const hidden = status && status.hidden > 0 ? ` · скрыто фильтром: ${status.hidden} скв.` : ''

  return (
    <div className={'well-filter' + (active ? ' active' : '')}>
      <button type="button" className="well-filter-button" aria-expanded={open} onClick={openPanel}
        title="Группы и скважины пересекаются. Фильтр действует на все модули проекта.">
        <span className="well-filter-label">Фильтр скважин</span>
        <span className="well-filter-value">{summary}{hidden}</span>
      </button>
      {open && (
        <div className="well-filter-panel" role="dialog" aria-label="Фильтр скважин">
          <p className="well-filter-hint">
            Действует на все модули проекта и на списки «Скважины». Остаются скважины выбранных групп, которые есть
            в списке скважин. Пусто — без ограничений.
          </p>
          <div className="well-filter-fields">
            <MultiSelect label="Группы" options={allGroups} value={groups} onChange={setGroups} emptyMeaning="все" />
            <MultiSelect label="Скважины" options={allWells} value={wells} onChange={setWells} emptyMeaning="все"
              picker={project.id} />
          </div>
          {error && <p className="well-filter-error" role="alert">{error}</p>}
          <div className="well-filter-actions">
            <button type="button" className="primary" onClick={() => apply(groups, wells)}>Применить</button>
            <button type="button" onClick={() => apply([], [])} disabled={!active}>Снять фильтр</button>
            <button type="button" className="quiet" onClick={() => setOpen(false)}>Отмена</button>
          </div>
          {legacy > 0 && (
            <div className="well-filter-legacy">
              <span>Старых пресетов из общей папки: {legacy}. Перенести их в этот проект?</span>
              <button type="button" onClick={importLegacy}>Перенести пресеты</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

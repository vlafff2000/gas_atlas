import { useEffect, useState } from 'react'
import { api } from './api'
import { MultiSelect } from './MultiSelect'
import { wellFilterApi, wellPresetApi, wellPresets, type WellFilter as Filter, type WellFilterStatus, type WellPreset } from './api_wells'
import './wellfilter.css'

interface Props {
  project: string
  revision: number
  value: Filter | null | undefined          // фильтр этой вкладки; другие вкладки на него не смотрят
  onChange: (value: Filter | null) => void
}

const isActive = (f: Filter | null | undefined) => Boolean(f && ((f.groups?.length ?? 0) || (f.wells?.length ?? 0)))

/** Короткая подпись фильтра для свёрнутой строки параметров. */
export const filterSummary = (f: Filter | null | undefined) =>
  isActive(f) ? `Фильтр скважин: групп ${f?.groups?.length ?? 0}, скважин ${f?.wells?.length ?? 0}` : ''

/**
 * Фильтр скважин вкладки: группы и скважины пересекаются. Состояние у каждой вкладки своё и лежит в её параметрах;
 * общие у всех вкладок только пресеты скважин проекта. Стоит рядом с «Скважины» в панели параметров.
 */
export function WellFilter({ project, revision, value, onChange }: Props) {
  const saved = isActive(value) ? value! : null
  const [open, setOpen] = useState(false)
  const [groups, setGroups] = useState<string[]>([])            // черновик: применяется кнопкой «Применить»
  const [wells, setWells] = useState<string[]>([])
  const [allGroups, setAllGroups] = useState<string[]>([])
  const [allWells, setAllWells] = useState<string[]>([])
  const [presets, setPresets] = useState<WellPreset[]>([])
  const [status, setStatus] = useState<WellFilterStatus | null>(null)
  const [legacy, setLegacy] = useState(0)                       // старые пресеты общей папки, ещё не перенесённые в проект
  const [error, setError] = useState('')
  const key = JSON.stringify(saved)

  useEffect(() => {
    api.projectGroups(project).then(setAllGroups).catch(() => setAllGroups([]))
    api.projectWells(project).then(setAllWells).catch(() => setAllWells([]))
  }, [project, revision])
  useEffect(() => {
    if (!saved) { setStatus(null); return }
    wellFilterApi.status(project, saved).then(setStatus).catch(() => setStatus(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, revision, key])
  useEffect(() => {
    if (!open) return
    wellPresetApi.list(project).then(r => { setPresets(r.presets); setLegacy(r.legacy ?? 0) }).catch(() => setPresets([]))
  }, [open, project])

  const openPanel = () => {
    setGroups(saved?.groups ?? [])
    setWells(saved?.wells ?? [])
    setError('')
    setOpen(o => !o)
  }
  const apply = (nextGroups: string[], nextWells: string[]) => {
    onChange(nextGroups.length || nextWells.length ? { groups: nextGroups, wells: nextWells } : null)
    setOpen(false)
  }
  const pickPreset = (id: string) => {
    const preset = presets.find(p => p.id === id)
    if (preset) { setGroups([]); setWells(preset.wells.filter(w => allWells.includes(w))) }
  }
  const importLegacy = async () => {
    setError('')
    try {
      const r = await wellPresetApi.importLegacy(project)
      setLegacy(r.legacy ?? 0)
      setPresets(r.presets)
    } catch (e) { setError((e as Error).message) }
  }

  const summary = !saved ? 'все' : status ? `${status.shown} из ${status.total} скв.` : '…'
  const hidden = saved && status && status.hidden > 0 ? ` (скрыто ${status.hidden})` : ''

  return (
    <div className={'multi well-filter' + (saved ? ' active' : '')}>
      <button type="button" className="field-button well-filter-button" aria-expanded={open} onClick={openPanel}
        title="Группы и скважины пересекаются. Фильтр действует только на эту вкладку; пресеты общие у всех вкладок.">
        <span className="field-label">Фильтр скважин</span>
        <span className="field-value">{summary}{hidden}</span>
      </button>
      {open && (
        <div className="popover well-filter-panel" role="dialog" aria-label="Фильтр скважин">
          <p className="well-filter-hint">
            Действует только на эту вкладку. Остаются скважины выбранных групп из выбранных скважин; пусто — без ограничений.
            Пресеты общие: их видно на всех вкладках.
          </p>
          <div className="well-filter-fields">
            <MultiSelect label="Группы" options={allGroups} value={groups} onChange={setGroups} emptyMeaning="все" />
            <MultiSelect label="Скважины" options={allWells} value={wells} onChange={setWells} emptyMeaning="все" presets={wellPresets(project)} />
          </div>
          <label className="field well-filter-preset">
            <span className="field-label">Применить пресет</span>
            <select value="" onChange={e => pickPreset(e.target.value)} disabled={!presets.length}>
              <option value="" />
              {presets.map(p => <option key={p.id} value={p.id}>{p.label} ({p.wells.length})</option>)}
            </select>
          </label>
          {error && <p className="well-filter-error" role="alert">{error}</p>}
          <div className="well-filter-actions">
            <button type="button" className="primary" onClick={() => apply(groups, wells)}>Применить</button>
            <button type="button" onClick={() => apply([], [])} disabled={!saved}>Снять фильтр</button>
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

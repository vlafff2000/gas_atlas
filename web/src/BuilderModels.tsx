import { useEffect, useState } from 'react'
import { builderApi, type ModelList } from './api'

/** Модели tNavigator из общего списка папок ГДМ: отмеченные дают поля «Модель ГДМ» в дереве. Файлы модели в проект не копируются. */
export function BuilderModels({ project, notes, onChange }: { project: string; notes: string[]; onChange: () => void }) {
  const [list, setList] = useState<ModelList | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    builderApi.models(project).then(l => { if (alive) setList(l) }).catch(e => { if (alive) setError((e as Error).message) })
    return () => { alive = false }
  }, [project])

  const choose = (id: string, on: boolean) => {
    if (!list) return
    const selected = list.models.filter(m => m.selected && m.id !== id).map(m => m.id).concat(on ? [id] : [])
    setBusy(true)
    builderApi.chooseModels(project, selected)
      .then(l => { setList(l); setError(''); onChange() })
      .catch(e => setError((e as Error).message))
      .finally(() => setBusy(false))
  }

  const setCubes = (extra: { cubes?: boolean; cubes_from?: string; cubes_to?: string }) => {
    if (!list) return
    setBusy(true)
    builderApi.chooseModels(project, list.models.filter(m => m.selected).map(m => m.id), extra)
      .then(l => { setList(l); setError(''); onChange() })
      .catch(e => setError((e as Error).message))
      .finally(() => setBusy(false))
  }

  const chosen = list?.models.filter(m => m.selected).length ?? 0
  return (
    <details className="builder-models">
      <summary>Модели ГДМ {chosen > 0 && <span className="muted">{chosen}</span>}</summary>
      {error && <div className="note warning">{error}</div>}
      {list && !list.available && <div className="note info">{list.error}</div>}
      {list?.available && !list.models.length && (
        <p className="muted">Моделей нет. Папки с результатами tNavigator добавляются в ГДМ («Модель»), список общий для всех программ.</p>
      )}
      {list?.models.map(m => (
        <label key={m.id} className="check" title={m.folder}>
          <input type="checkbox" checked={m.selected} disabled={busy} onChange={e => choose(m.id, e.target.checked)} /> {m.name}
        </label>
      ))}
      {chosen > 0 && (
        <label className="check" title="Среднее давление и газонасыщенность по поровому объёму, газонасыщенный объём и ГВК по датам рестарта. Нужны EGRID, INIT и UNRST рядом с моделью.">
          <input type="checkbox" checked={list?.cubes ?? false} disabled={busy} onChange={e => setCubes({ cubes: e.target.checked })} /> Кубы свойств (читаются долго)
        </label>
      )}
      {chosen > 0 && list?.cubes && (
        <div className="check" title="Читаются только рестарты в этих датах: чем уже период, тем быстрее. Пусто — без границы.">
          Рестарты с <input type="date" value={list.cubes_from} disabled={busy} onChange={e => setCubes({ cubes_from: e.target.value })} aria-label="Рестарты с" />
          {' '}по <input type="date" value={list.cubes_to} disabled={busy} onChange={e => setCubes({ cubes_to: e.target.value })} aria-label="Рестарты по" />
        </div>
      )}
      {busy && <p className="muted">Читаем модель…</p>}
      {notes.map(n => <div key={n} className="note warning">{n}</div>)}
    </details>
  )
}

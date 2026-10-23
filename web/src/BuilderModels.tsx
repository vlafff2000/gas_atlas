import { useEffect, useState } from 'react'
import { builderApi, type CellsConfig, type ModelList } from './api'
import { MultiSelect } from './MultiSelect'

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

  const setCubes = (extra: { cubes?: boolean; cubes_from?: string; cubes_to?: string; cells?: CellsConfig }) => {
    if (!list) return
    setBusy(true)
    builderApi.chooseModels(project, list.models.filter(m => m.selected).map(m => m.id), extra)
      .then(l => { setList(l); setError(''); onChange() })
      .catch(e => setError((e as Error).message))
      .finally(() => setBusy(false))
  }

  const refresh = () => {
    setBusy(true)
    builderApi.refreshCubes(project)
      .then(l => { setList(l); setError(''); onChange() })
      .catch(e => setError((e as Error).message))
      .finally(() => setBusy(false))
  }

  const first = list?.models.find(m => m.selected)
  const [restarts, setRestarts] = useState<string[]>([])
  useEffect(() => {
    let alive = true
    setRestarts([])
    if (first?.indicators) builderApi.restarts(project, first.id).then(r => { if (alive) setRestarts(r.dates) }).catch(() => undefined)
    return () => { alive = false }
  }, [project, first?.id, first?.indicators])
  const cells = list?.cells
  const setCells = (patch: Partial<CellsConfig>) => cells && setCubes({ cells: { ...cells, ...patch } })

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
          {' '}<button type="button" className="kind" disabled={busy} onClick={refresh}
            title="Сбросить сохранённые шаги и прочитать кубы заново: если модель пересчитали с теми же сеткой и началом рестарта.">Пересчитать заново</button>
        </div>
      )}
      {first?.indicators && cells && (
        <details className="builder-cells" open={cells.dates.length > 0}>
          <summary>Ячейки куба (для кроссплотов)</summary>
          <p className="muted">Точка — ячейка модели на дату рестарта. Выберите даты (до 6) и стройте ряд «Модель ГДМ: ячейки», точками: например давление по X и газонасыщенность по Y. При двух и более датах появляются поля «… на ГГГГ-ММ-ДД» (первая и вторая по времени) и «изменение»: одну и ту же ячейку можно сравнить, отложив состояние на первой дате по X, на второй по Y.</p>
          <MultiSelect label="Даты рестарта" options={restarts} value={cells.dates} emptyMeaning="ничего" onChange={d => setCells({ dates: d })} />
          <label className="field"><span className="field-label">Слои с</span>
            <input type="number" min={1} defaultValue={cells.k_from} key={'f' + cells.k_from} onBlur={e => setCells({ k_from: Number(e.target.value) || 1 })} /></label>
          <label className="field"><span className="field-label">по (0 — до низа)</span>
            <input type="number" min={0} defaultValue={cells.k_to} key={'t' + cells.k_to} onBlur={e => setCells({ k_to: Number(e.target.value) || 0 })} /></label>
          <label className="field"><span className="field-label">Точек на дату</span>
            <input type="number" min={100} max={200000} step={1000} defaultValue={cells.max_points} key={'m' + cells.max_points} onBlur={e => setCells({ max_points: Number(e.target.value) || 20000 })} /></label>
          <p className="muted">Ячеек больше предела — берётся каждая n-я, об этом пишет заметка графика. Список дат — по первой выбранной модели, у остальных берётся ближайший рестарт.</p>
        </details>
      )}
      {busy && <p className="muted">Читаем модель…</p>}
      {notes.map(n => <div key={n} className="note warning">{n}</div>)}
    </details>
  )
}

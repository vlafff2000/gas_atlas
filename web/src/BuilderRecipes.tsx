import { useState } from 'react'
import type { BuilderCatalog, BuilderLayout, BuilderRow } from './ChartBuilder'

// Готовые графики конструктора: один выбор собирает ряды (поле, сводка по объекту, накопленное) из данных проекта.
// Результат — обычные ряды макета: их можно открыть и поправить вручную.

type Mode = 'withdrawal' | 'injection'
const MODE_LABEL: Record<Mode, string> = { withdrawal: 'Отбор', injection: 'Закачка' }
const MODE_WORD: Record<Mode, string> = { withdrawal: 'отбора', injection: 'закачки' }
const MODE_NOUN: Record<Mode, string> = { withdrawal: 'отбор', injection: 'закачка' }

interface Built { title: string; series: BuilderRow[] }
interface Recipe { id: string; label: string; hint: string; build: (c: BuilderCatalog, mode: Mode) => Built | string }

const rid = () => Math.random().toString(36).slice(2, 10)
const row = (patch: Partial<BuilderRow>): BuilderRow => ({
  id: rid(), dataset: 'production', y: 'q', x_dataset: 'production', x: 'date', wells: [], date_from: '', date_to: '',
  kind: '', axis: 'y', view: 'line', key: 'well_date', days: 3, name: '', ...patch,
})

/** Почему рецепт нельзя собрать: нет набора, поля или режима (отбор / закачка). Пусто — можно. */
function missing(c: BuilderCatalog, dataset: string, field: string, mode?: Mode): string {
  const ds = c.datasets.find(d => d.id === dataset)
  if (!ds || !ds.fields.some(f => f.field === field)) {
    return dataset === 'production' ? 'Нет данных «Отбор и закачка». Загрузите суточные расходы по скважинам в разделе импорта.'
      : dataset === 'model' ? 'Нет данных модели ГДМ. Отметьте модель в блоке «Модели ГДМ» над деревом полей.'
      : dataset === 'object_pressure' ? 'Нет данных «Давление объекта». Загрузите давления объекта в разделе импорта.'
      : `Нет данных набора «${dataset}».`
  }
  if (mode && ds.kinds.length && !ds.kinds.some(k => k.value === mode))
    return `В данных нет режима «${MODE_LABEL[mode]}». Выберите другой режим или загрузите ${MODE_WORD[mode]}.`
  return ''
}

const cumulative = (mode: Mode, kind = true): Partial<BuilderRow> => ({
  wells: [], kind: kind ? mode : '', transform: { op: 'group', agg: 'sum', cum: true },
})

const RECIPES: Recipe[] = [
  {
    id: 'cum-object', label: 'Накопленный объём по объекту',
    hint: 'Нарастающий итог суточных расходов всех скважин по датам. Ось X — дата.',
    build: (c, mode) => missing(c, 'production', 'q', mode) || {
      title: `Накопленный ${MODE_NOUN[mode]} газа по объекту`,
      series: [row({ ...cumulative(mode), x: 'date', name: `Накопленный ${MODE_NOUN[mode]}` })],
    },
  },
  {
    id: 'cum-both', label: 'Накопленные отбор и закачка',
    hint: 'Две кривые на одной оси: накопленный отбор и накопленная закачка по объекту.',
    build: c => missing(c, 'production', 'q', 'withdrawal') || missing(c, 'production', 'q', 'injection') || {
      title: 'Накопленные отбор и закачка газа по объекту',
      series: (['withdrawal', 'injection'] as Mode[]).map(m => row({ ...cumulative(m), name: `Накопленный ${MODE_NOUN[m]}` })),
    },
  },
  {
    id: 'q-vs-cum', label: 'Суммарный расход от накопленного объёма',
    hint: 'Ось X — накопленный объём по объекту, ось Y — суммарный суточный расход всех скважин в тот же день.',
    build: (c, mode) => missing(c, 'production', 'q', mode) || {
      title: `Суточный расход от накопленного ${MODE_WORD[mode]}`,
      series: [row({
        wells: [], kind: mode, transform: { op: 'group', agg: 'sum' }, x: 'q', x_scope: 'object', x_transform: { op: 'cumsum' },
        key: 'date', view: 'points', name: `Суммарный расход (${MODE_NOUN[mode]})`,
      })],
    },
  },
  {
    id: 'model-vs-fact', label: 'Расход по объекту: модель и факт',
    hint: 'Сумма по скважинам: факт (отбор и закачка проекта), модель ГДМ (первая выбранная) и их разность «модель − факт». Скважины и модель правятся в карточках рядов.',
    build: (c, mode) => missing(c, 'production', 'q', mode) || missing(c, 'model', mode === 'injection' ? 'wgir' : 'wgpr') || {
      title: `Расход ${MODE_WORD[mode]} по объекту: модель и факт`,
      series: [
        row({ kind: mode, key: 'date', transform: { op: 'group', agg: 'sum' }, name: 'Факт' }),
        row({ dataset: 'model', y: mode === 'injection' ? 'wgir' : 'wgpr', x_dataset: 'model', key: 'date', transform: { op: 'group', agg: 'sum' }, name: 'Модель' }),
        row({ source: 'formula', formula: 'B - A', key: 'date', name: 'Модель − факт', view: 'bar' }),
      ],
    },
  },
  {
    id: 'p-vs-cum', label: 'Давление объекта от накопленного объёма',
    hint: 'Ось X — накопленный объём по объекту, ось Y — давление объекта на ту же дату.',
    build: (c, mode) => missing(c, 'object_pressure', 'pressure') || missing(c, 'production', 'q', mode) || {
      title: `Давление объекта от накопленного ${MODE_WORD[mode]}`,
      series: [row({
        dataset: 'object_pressure', y: 'pressure', x_dataset: 'production', x: 'q', x_scope: 'object', x_transform: { op: 'cumsum' },
        kind: mode, key: 'date', view: 'line_points', name: 'Давление объекта',
      })],
    },
  },
]

export function BuilderRecipes({ catalog, layout, onApply }: {
  catalog: BuilderCatalog | null; layout: BuilderLayout; onApply: (title: string, series: BuilderRow[]) => void
}) {
  const [mode, setMode] = useState<Mode>('withdrawal')
  const [problem, setProblem] = useState('')
  const empty = layout.series.length === 0
  if (!catalog) return null
  const apply = (r: Recipe) => {
    const built = r.build(catalog, mode)
    if (typeof built === 'string') { setProblem(built); return }
    if (!empty && !window.confirm('Текущие ряды графика будут заменены готовым графиком. Продолжить?')) return
    setProblem(''); onApply(built.title, built.series)
  }
  const body = (
    <>
      {empty && (
        <ol className="recipe-steps">
          <li><b>Выберите данные.</b> Готовый график ниже или поле в дереве слева.</li>
          <li><b>Что по осям.</b> В карточке ряда задайте поля X и Y.</li>
          <li><b>Готово.</b> График справа; подписи, оси и вид настраиваются кнопками «Настройка».</li>
        </ol>
      )}
      <div className="kind-group" role="radiogroup" aria-label="Режим">
        <span className="kind-label">Режим</span>
        {(['withdrawal', 'injection'] as Mode[]).map(m => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} className={'kind' + (mode === m ? ' on' : '')}
            onClick={() => { setMode(m); setProblem('') }}>{MODE_LABEL[m]}</button>
        ))}
      </div>
      <div className="recipe-list">
        {RECIPES.map(r => (
          <button key={r.id} type="button" className="recipe" onClick={() => apply(r)} title={r.hint}>
            <b>{r.label}</b><small>{r.hint}</small>
          </button>
        ))}
      </div>
      {problem && <div className="note warning" role="alert">{problem}</div>}
      <p className="muted recipe-note">Ряды можно потом править вручную: откройте карточку ряда.</p>
    </>
  )
  return empty
    ? <section className="builder-recipes" aria-label="Готовые графики"><h2>Готовые графики</h2>{body}</section>
    : <details className="builder-recipes"><summary>Готовые графики</summary>{body}</details>
}

// Раздел «Настройки» (5.8: страница «Настройки» в app/main.py и «Оформление графиков» боковой панели).
import { useCallback, useEffect, useState } from 'react'
import { projectsApi, saveLink } from './api_projects'
import { theme, usePref, type Theme } from './chartPrefs'
import { RestoreBox, Toast, useDetails, type PageProps } from './ProjectPage'

const STYLE = [['points', 'Показывать точки'], ['legend', 'Легенда'], ['grid', 'Сетка']] as const

const SCHEDULE_CODE: Record<string, string> = { injection: 'inj', withdrawal: 'prod', none: 'none' }
const dmy = (d: string) => `${d.slice(8)}.${d.slice(5, 7)}.${d.slice(0, 4)}`
const scheduleText = (value: unknown, peaks: unknown) =>
  [...(Array.isArray(value) ? (value as [string, string][]).map(([d, k]) => `${dmy(d)} ${SCHEDULE_CODE[k] ?? k}`) : []),
   ...(Array.isArray(peaks) ? (peaks as [string, string][]).map(([a, b]) => `${dmy(a)} ${dmy(b)} peak`) : [])].join('\n')

export function SettingsPage({ project, onProject, onOpen }: PageProps) {
  const { details } = useDetails(project.id, project.revision)
  const s = project.settings
  const [start, setStart] = useState(String(s.season_start ?? 11))
  const [end, setEnd] = useState(String(s.season_end ?? 4))
  const [auto, setAuto] = useState(s.auto_seasons === true)
  const [neutral, setNeutral] = useState(s.show_neutral_periods === true)
  const [gap, setGap] = useState(String(s.season_gap_days ?? 3))
  const [share, setShare] = useState(String(s.season_rate_share ?? 10))
  const [peaks, setPeaks] = useState(s.auto_peaks === true)
  const [factor, setFactor] = useState(String(s.peak_factor ?? 2))
  const [schedule, setSchedule] = useState(scheduleText(s.season_schedule, s.peak_windows))
  const [threshold, setThreshold] = useState(String(s.r2_threshold ?? 0.95))
  const [manometers, setManometers] = useState(((s.manometer_wells as string[] | null) ?? []).join(', '))
  const [pages, setPages] = useState<string[] | null>(null)
  const [style, setStyle] = useState<Record<string, boolean>>({})
  const [originals, setOriginals] = useState(true)
  const currentTheme = usePref(theme)
  const [toast, setToast] = useState<string | null>(null)
  const closeToast = useCallback(() => setToast(null), [])

  useEffect(() => {
    setStart(String(s.season_start ?? 11)); setEnd(String(s.season_end ?? 4)); setThreshold(String(s.r2_threshold ?? 0.95))
    setSchedule(scheduleText(s.season_schedule, s.peak_windows))
    setPeaks(s.auto_peaks === true); setFactor(String(s.peak_factor ?? 2))
    setAuto(s.auto_seasons === true); setNeutral(s.show_neutral_periods === true); setGap(String(s.season_gap_days ?? 3)); setShare(String(s.season_rate_share ?? 10))
    setManometers(((s.manometer_wells as string[] | null) ?? []).join(', '))
    const saved = (s.chart_style as Record<string, boolean> | null) ?? {}
    setStyle({ points: true, legend: true, grid: true, ...saved })
  }, [s.season_start, s.season_end, s.r2_threshold, s.auto_seasons, s.show_neutral_periods, s.season_gap_days, s.season_rate_share, s.season_schedule, s.peak_windows, s.auto_peaks, s.peak_factor, s.manometer_wells, s.chart_style])
  useEffect(() => { if (details) setPages(details.visible_pages) }, [details])

  const save = async (values: Record<string, unknown>, done: string) => {
    try { onProject(await projectsApi.settings(project.id, values)); setToast(done) }
    catch (e) { setToast((e as Error).message) }
  }
  const month = (v: string) => Number.isInteger(Number(v)) && Number(v) >= 1 && Number(v) <= 12
  const r2 = Number(threshold)
  const gapDays = Number(gap), rate = Number(share)
  const peakFactor = Number(factor)
  const autoValid = Number.isInteger(gapDays) && gapDays >= 1 && gapDays <= 365 && rate > 0 && rate <= 50 && peakFactor > 1 && peakFactor <= 20
  const rulesValid = month(start) && month(end) && autoValid && threshold.trim() !== '' && r2 >= 0 && r2 <= 1

  return (
    <>
      <header className="module-title">
        <div>
          <h1>Настройки проекта</h1>
          <p className="lede">Правила периодов, разделы меню, резервные копии и восстановление.</p>
        </div>
      </header>

      <section className="form-block">
        <h2>Правила</h2>
        <div className="form-row">
          <label className={'field number' + (month(start) ? '' : ' invalid')}>
            <span className="field-label">Первый месяц сезона отбора</span>
            <input type="number" min={1} max={12} step={1} value={start} onChange={e => setStart(e.target.value)} />
          </label>
          <label className={'field number' + (month(end) ? '' : ' invalid')}>
            <span className="field-label">Последний месяц сезона отбора</span>
            <input type="number" min={1} max={12} step={1} value={end} onChange={e => setEnd(e.target.value)} />
          </label>
          <label className={'field number' + (r2 >= 0 && r2 <= 1 ? '' : ' invalid')}>
            <span className="field-label">Порог R²</span>
            <input type="number" min={0} max={1} step={0.01} value={threshold} onChange={e => setThreshold(e.target.value)} />
          </label>
        </div>
        <label className="check">
          <input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} />
          <span>Определять сезоны по накопленному расходу объекта (если в таблице нет «Сезона» или «Года»)</span>
        </label>
        {auto && (
          <div className="form-row">
            <label className={'field number' + (Number.isInteger(gapDays) && gapDays >= 1 && gapDays <= 365 ? '' : ' invalid')}>
              <span className="field-label">Минимальная пауза, сут (короче — не нейтральный период)</span>
              <input type="number" min={1} max={365} step={1} value={gap} onChange={e => setGap(e.target.value)} />
            </label>
            <label className={'field number' + (rate > 0 && rate <= 50 ? '' : ' invalid')}>
              <span className="field-label">Порог расхода, % от типичного</span>
              <input type="number" min={1} max={50} step={1} value={share} onChange={e => setShare(e.target.value)} />
            </label>
          </div>
        )}
        <label className="check">
          <input type="checkbox" checked={neutral} onChange={e => setNeutral(e.target.checked)} />
          <span>Показывать нейтральные периоды в списках «Сезон» («Нейтральный период …», «Вне сезона …»)</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={peaks} onChange={e => setPeaks(e.target.checked)} />
          <span>Искать пиковые режимы по расходу (для нестабильных объектов): отметки «Пик» на графиках</span>
        </label>
        {peaks && (
          <div className="form-row">
            <label className={'field number' + (peakFactor > 1 && peakFactor <= 20 ? '' : ' invalid')}>
              <span className="field-label">Пик: во сколько раз выше медианы сезона</span>
              <input type="number" min={1.1} max={20} step={0.1} value={factor} onChange={e => setFactor(e.target.value)} />
            </label>
          </div>
        )}
        <label className="field wide">
          <span className="field-label">Скважины с глубинными манометрами (через запятую)</span>
          <input value={manometers} onChange={e => setManometers(e.target.value)} />
        </label>
        <p className="muted small-text">Явный сезон в исходной таблице имеет приоритет над правилом месяцев и над автоопределением. Закачка группируется по году.
          Автоопределение: сезон — отрезок, где накопленный объём растёт; пауза от порога (по умолчанию 3 сут), после которой тот же вид не возобновился устойчиво, — «Нейтральный период Весна/Осень ГГГГ».
          Изменение порога применяется к следующему расчету ГДИ.</p>
        <div className="form-row">
          <button type="button" className="primary" disabled={!rulesValid}
            onClick={() => save({ season_start: Number(start), season_end: Number(end), r2_threshold: r2, manometer_wells: manometers,
              auto_seasons: auto, show_neutral_periods: neutral, auto_peaks: peaks, ...(peaks ? { peak_factor: peakFactor } : {}), ...(auto ? { season_gap_days: gapDays, season_rate_share: rate } : {}) },
              'Правила сохранены. Расчеты обновятся с учетом новых правил.')}>Сохранить правила</button>
        </div>
      </section>

      <section className="form-block">
        <h2>Расписание периодов</h2>
        <p className="muted small-text">Точные даты начала периодов, по одной строке: «28.06.2021 inj» — закачка, «25.10.2021 none» — нейтральный период,
          «01.11.2021 prod» — отбор, «10.01.2022 15.01.2022 peak» — пиковое окно внутри сезона (первый и последний день; периоды не разбивает). Период длится до дня перед следующей строкой, последний — до конца данных. Расписание главнее колонок
          «Сезон»/«Год» и автоопределения; даты до первой строки считаются по обычному правилу.</p>
        <label className="field wide">
          <span className="field-label">Текстовый файл (.txt) или текст</span>
          <input type="file" accept=".txt,.csv,text/plain"
            onChange={async e => { const f = e.target.files?.[0]; if (f) setSchedule(await f.text()); e.target.value = '' }} />
        </label>
        <textarea className="wide" rows={8} value={schedule} placeholder={'28.06.2021 inj\n25.10.2021 none\n01.11.2021 prod'}
          onChange={e => setSchedule(e.target.value)} />
        <div className="form-row">
          <button type="button" className="primary" onClick={() => save({ season_schedule: schedule }, schedule.trim() ? 'Расписание сохранено. Периоды пересчитаны.' : 'Расписание снято.')}>
            {schedule.trim() ? 'Сохранить расписание' : 'Снять расписание'}</button>
        </div>
      </section>

      <section className="form-block">
        <h2>Разделы меню</h2>
        {pages && details ? (
          <>
            <div className="check-grid">
              {details.pages.map(p => (
                <label key={p} className="toggle">
                  <input type="checkbox" checked={p === 'Настройки' || pages.includes(p)} disabled={p === 'Настройки'}
                    onChange={e => setPages(e.target.checked ? details.pages.filter(x => x === p || pages.includes(x)) : pages.filter(x => x !== p))} />
                  <span>{p}</span>
                </label>
              ))}
            </div>
            <p className="muted small-text">Настройки остаются доступными при любом выборе. Скрытые разделы сохраняют данные и параметры.
              Состав меню общий с версией 5.8; разделы, которых еще нет в 6, учитываются, когда появятся.</p>
            <div className="form-row">
              <button type="button" className="quiet" onClick={() => save({ visible_pages: pages }, 'Состав меню сохранен.')}>Сохранить состав меню</button>
              <button type="button" className="quiet" onClick={() => save({ visible_pages: null }, 'Восстановлено меню по умолчанию.')}>Восстановить меню по умолчанию</button>
            </div>
          </>
        ) : <p className="muted">Загрузка…</p>}
      </section>

      <section className="form-block">
        <h2>Тема интерфейса</h2>
        <div className="segmented" role="radiogroup" aria-label="Тема интерфейса">
          {([['light', 'Светлая'], ['dark', 'Тёмная'], ['system', 'Авто']] as [Theme, string][]).map(([t, label]) => (
            <button key={t} type="button" role="radio" aria-checked={currentTheme === t} onClick={() => theme.set(t)}>{label}</button>
          ))}
        </div>
        <p className="muted small-text">«Авто» следует теме системы. Выбор запоминается в этом браузере.</p>
      </section>

      <section className="form-block">
        <h2>Оформление графиков</h2>
        <div className="form-row">
          {STYLE.map(([field, label]) => (
            <label key={field} className="toggle">
              <input type="checkbox" checked={style[field] ?? true} onChange={e => setStyle({ ...style, [field]: e.target.checked })} />
              <span>{label}</span>
            </label>
          ))}
          <button type="button" className="quiet" onClick={() => save({ chart_style: style }, 'Оформление сохранено.')}>Сохранить оформление</button>
        </div>
        <p className="muted small-text">Действует на выгрузки раздела «Экспорт» и на графики версии 5.8.</p>
      </section>

      <section className="form-block">
        <h2>Резервная копия проекта</h2>
        <div className="form-row">
          <label className="toggle">
            <input type="checkbox" checked={originals} onChange={e => setOriginals(e.target.checked)} />
            <span>Включить исходные файлы</span>
          </label>
          <button type="button" className="quiet" onClick={() => saveLink(projectsApi.backupUrl(project.id, originals))}>Скачать резервную копию</button>
        </div>
        <RestoreBox onOpen={onOpen} label="Восстановить копию или перенести старый .gas.json как отдельный проект" />
      </section>

      <div className="toolbar">
        <button type="button" className="quiet" disabled={!details?.log} title={details?.log ? '' : 'Журнал ошибок пока пуст'}
          onClick={() => saveLink(projectsApi.logUrl)}>Скачать журнал ошибок</button>
        <span className="muted">Проекты автоматически сохраняются после импорта и изменения настроек. Для переноса на другой компьютер используйте резервную копию.</span>
      </div>
      <Toast text={toast} onClose={closeToast} />
    </>
  )
}

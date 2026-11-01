// Раздел «Экспорт» (5.8: app/ui/export_panel.py). Поля формы называются как виджеты 5.8 — шаблоны общие.
import { UndoButtons, useUndo, useUndoValue, type Undo } from './useUndo'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { MultiSelect } from './MultiSelect'
import { ChartView } from './ChartView'
import { api, type Chart } from './api'
import { WordViewerPane } from './WordViewer'
import { exportApi, projectsApi, saveLink, type ExportChoices, type ExportPlan, type ExportResult, type Form, type WordPreview } from './api_projects'
import { Toast, type PageProps } from './ProjectPage'
import { wellPresetApi, type WellPreset } from './api_wells'
import { ExportAnyChart } from './ExportAnyChart'
import { ResizableFrame } from './ResizableFrame'
import { Check, Color, GRID_OPTIONS, MINOR_GRID_OPTIONS, Num, Opt, Section, Select, SizePick, Text, type FieldProps as SharedFieldProps } from './exportFields'

/** Поля формы раздела «Экспорт»: общие поля получают ещё и перечень выбора (choices). */
interface FieldProps extends SharedFieldProps { choices: ExportChoices }

const SPLIT: Opt[] = [['well', 'По скважинам'], ['group', 'По группам (отдельные кривые)'], ['subgroup', 'По подгруппам'], ['all', 'Все выбранные вместе']]
const DIRECTION: Opt[] = [['number', 'По номеру'], ['desc', 'Больший дебит слева'], ['asc', 'Больший дебит справа']]
const ORIENTATION: Opt[] = [['standard', 'X = Q, Y = ΔP²'], ['swapped', 'X = ΔP², Y = Q']]
const KINDS = [['withdrawal', 'Отбор'], ['injection', 'Закачка']] as const
const ELPRO_ROWS: [string, string][] = [['hours', 'Часы работы'], ['cru', 'КРУ, %'], ['p', 'Давление, кгс/см²'], ['t', 'Температура, °C']]
/** Вкладки экспорта, которые строят готовые документы, а не перечень графиков: включаются в выгрузку так же, как модули. */
const EXTRAS = ['pack', 'ggh']

/** Фильтр скважин одной вкладки: поля формы, которые читает выгрузка (как у модуля), и ключ в настройках проекта. */
function filterFields(tab: string): { groups?: string; wells: string } | null {
  if (tab === 'pack') return { groups: 'pack_groups', wells: 'pack_wells' }
  if (tab === 'ggh') return { wells: 'ggh_wells' }
  if (tab === 'gis') return { wells: 'gis_wells' }
  if (tab === 'any' || tab === 'custom' || tab === 'waterfactor') return null
  return { groups: tab + '_groups', wells: (tab === 'well_dashboard' ? 'dashboard' : tab) + '_wells' }
}
/** Скважины, которые предлагает вкладка (ГГХ — с учетом выбранных горизонтов). */
function wellsOf(tab: string, choices: ExportChoices, form: Form): string[] {
  if (tab === 'pack') return choices.wells.production ?? []
  if (tab === 'gis') return choices.gis?.wells ?? []
  if (tab === 'ggh') {
    const horizons = (form.ggh_horizons as string[] | undefined) ?? []
    return (choices.ggh?.wells ?? []).filter(w => !horizons.length || horizons.includes(choices.ggh!.horizon_of[w]))
  }
  return choices.wells[tab] ?? []
}
const groupOf = (choices: ExportChoices, well: string) => choices.mapping[well] ?? 'Без группы'
type TabFilter = { groups?: string[]; wells?: string[] }

/** Без локального хранилища черновика: форма живёт, пока открыт раздел; для повтора — шаблоны. */
export function ExportPage({ project, onProject, view = 'export' }: PageProps & { view?: 'export' | 'pack' | 'ggh' }) {
  const [form, setForm] = useState<Form>({})
  const [choices, setChoices] = useState<ExportChoices | null>(null)
  const [tab, setTab] = useState<string | null>(view === 'pack' || view === 'ggh' ? view : null)
  const [plan, setPlan] = useState<ExportPlan | null>(null)
  const [planKey, setPlanKey] = useState('')
  const [showPreview, setShowPreview] = useState(false)
  const [chart, setChart] = useState('')
  const [image, setImage] = useState<string | null>(null)
  const [live, setLive] = useState(false)                    // предпросмотр: картинка файла или интерактивный график
  const [liveChart, setLiveChart] = useState<Chart | null>(null)
  const [excludeMode, setExcludeMode] = useState(false)
  const [archive, setArchive] = useState<{ key: string; result: ExportResult } | null>(null)
  const [word, setWord] = useState<{ key: string; result: ExportResult } | null>(null)
  const [pack, setPack] = useState<{ key: string; result: ExportResult } | null>(null)
  const [ggh, setGgh] = useState<{ key: string; result: ExportResult } | null>(null)
  const [gisFile, setGisFile] = useState<ExportResult | null>(null)
  const [gisBusy, setGisBusy] = useState(false)
  const [hikgFile, setHikgFile] = useState<ExportResult | null>(null)
  const [hikgBusy, setHikgBusy] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [presetName, setPresetName] = useState('')
  const [presetChoice, setPresetChoice] = useState('')
  const [natural, setNatural] = useState<[number, number] | null>(null)    // размеры картинки предпросмотра: для автовысоты
  const closeToast = useCallback(() => setToast(null), [])
  const exclusions = form.exclusions !== false

  useEffect(() => {
    exportApi.choices(project.id, exclusions).then(c => { setChoices(c); setError(null) }).catch(e => setError((e as Error).message))
  }, [project.id, project.revision, exclusions])

  const set = useCallback((field: string, value: unknown) => setForm(f => ({ ...f, [field]: value })), [])
  // Отмена (Ctrl+Z) для параметров выгрузки: любое изменение формы, включая шаблон, фильтры и переключатели модулей.
  const undo = useUndo({ onNotice: setToast })
  useUndoValue(form, setForm, undo, 'изменение параметров выгрузки', project.id + (choices ? ':готово' : ':загрузка'))
  // Фильтры вкладок хранятся в проекте: при открытии раздела берутся оттуда, при изменении сохраняются (с паузой, чтобы не писать на каждый щелчок).
  const savedFilters = (project.settings.export_filters ?? {}) as Record<string, TabFilter>
  const pendingFilters = useRef<Record<string, TabFilter> | null>(null)
  const saveTimer = useRef<number | undefined>(undefined)
  useEffect(() => {
    const saved = (project.settings.export_filters ?? {}) as Record<string, TabFilter>
    setForm(f => {
      const next = { ...f }
      for (const [tab, value] of Object.entries(saved)) {
        const fields = filterFields(tab)
        if (!fields) continue
        if (fields.groups && next[fields.groups] === undefined && value.groups !== undefined) next[fields.groups] = value.groups
        if (next[fields.wells] === undefined && value.wells !== undefined) next[fields.wells] = value.wells
      }
      return next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])
  const setTabFilter = (tab: string, groups: string[] | undefined, wells: string[] | undefined) => {
    const fields = filterFields(tab)
    if (!fields) return
    if (fields.groups) set(fields.groups, groups)
    set(fields.wells, wells)
    const entry: TabFilter = { ...(groups ? { groups } : {}), ...(wells ? { wells } : {}) }
    pendingFilters.current = { ...(pendingFilters.current ?? savedFilters), [tab]: entry }
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      const values = pendingFilters.current
      pendingFilters.current = null
      if (values) api.saveSettings(project.id, { export_filters: values }).then(onProject).catch(e => setError((e as Error).message))
    }, 700)
  }
  const modules = (form.modules as string[] | undefined) ?? choices?.default_modules ?? []
  const key = JSON.stringify([project.revision, form])
  // Перечень графиков от размера не зависит: растягивание в предпросмотре не должно его сбрасывать.
  const planned = useMemo(() => { const { width: _w, height: _h, look: _l, ...rest0 } = form; const rest = Object.fromEntries(Object.entries(rest0).filter(([k]) => !k.startsWith('word_') && !k.startsWith('label_') && !k.startsWith('fmt_'))); return JSON.stringify([project.revision, rest]) }, [form, project.revision])
  const planModules = modules.filter(m => !EXTRAS.includes(m))
  const ready = modules.length > 0                       // что-то включено в выгрузку
  const readyPlan = planModules.length > 0               // есть модули с перечнем графиков (предпросмотр, архив, Word)
  const labelsKey = JSON.stringify(Object.entries(form).filter(([k]) => k.startsWith('label_') || k.startsWith('fmt_')))

  // Перечень графиков: обычные модули и (если включены) графики пакета по фонду и ГГХ.
  const fetchPlan = async (f: Form): Promise<ExportPlan> => {
    const ms = ((f.modules as string[] | undefined) ?? choices?.default_modules ?? [])
    const base: ExportPlan = ms.some(m => !EXTRAS.includes(m)) ? await exportApi.plan(project.id, f) : { modules: [], charts: [], tables: [], note: '' }
    if (!ms.some(m => EXTRAS.includes(m))) return base
    const more = await exportApi.extras(project.id, f)
    return { ...base, charts: [...base.charts, ...more.charts] }
  }
  const prepare = async () => {
    if (planKey === planned && plan) return plan
    const next = await fetchPlan(form)
    setPlan(next); setPlanKey(planned)
    return next
  }
  const run = async (label: string, work: () => Promise<void>) => {
    setBusy(label); setError(null)
    try { await work() } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }
  const preview = () => run('preview', async () => { await prepare(); setShowPreview(true) })
  // Пакет по фонду и ГГХ строятся теми же кнопками «Сформировать архив» и «Создать отчет Word»; повторно с теми же параметрами не создаются.
  const makeExtras = async () => {
    if (modules.includes('pack') && pack?.key !== key) { setBusy('pack'); setPack({ key, result: await exportApi.pack(project.id, form) }) }
    if (modules.includes('ggh') && ggh?.key !== key) { setBusy('ggh'); setGgh({ key, result: await exportApi.ggh(project.id, form) }) }
  }
  const makeArchive = () => run('archive', async () => {
    if (readyPlan) { await prepare(); setArchive({ key, result: await exportApi.archive(project.id, form) }) }
    await makeExtras()
  })
  const makeWord = () => run('word', async () => {
    if (readyPlan) { await prepare(); setWord({ key, result: await exportApi.word(project.id, form) }) }
    await makeExtras()
  })

  const packNoSeasons = modules.includes('pack') && KINDS.some(([k]) => ((form.pack_kinds as string[] | undefined) ?? ['withdrawal', 'injection']).includes(k)
    && Array.isArray(form[`pack_periods_${k}`]) && (form[`pack_periods_${k}`] as string[]).length === 0)

  // Автоматическое обновление предпросмотра (как флажок 5.8).
  useEffect(() => {
    if (!form.auto || !ready) return
    const timer = setTimeout(() => { fetchPlan(form).then(p => { setPlan(p); setPlanKey(planned); setShowPreview(true) }).catch(() => undefined) }, 400)
    return () => clearTimeout(timer)
  }, [form, key, planned, project.id, ready])

  // Картинка выбранного графика (макет файла, 150 DPI при выбранной ширине).
  const shownPlan = plan && planKey === planned ? plan : null
  const extraSel = EXTRAS.includes(shownPlan?.charts.find(c => c.name === chart)?.module ?? '')   // у пакета и ГГХ только картинка файла
  const liveOn = live && !extraSel
  useEffect(() => {
    if (!shownPlan || !showPreview || liveOn || !shownPlan.charts.length) return
    const name = shownPlan.charts.some(c => c.name === chart) ? chart : shownPlan.charts[0].name
    if (name !== chart) { setChart(name); return }
    let alive = true
    const isExtra = EXTRAS.includes(shownPlan.charts.find(c => c.name === name)?.module ?? '')
    ;(isExtra ? exportApi.extrasPreview : exportApi.preview)(project.id, form, name).then(u => { if (alive) setImage(old => { if (old) URL.revokeObjectURL(old); return u }); else URL.revokeObjectURL(u) })
      .catch(e => alive && setError('Не удалось отобразить этот график: ' + (e as Error).message))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownPlan, showPreview, chart, liveOn, form.width, form.height, form.look, form.font, form.font_size, labelsKey])

  // Открытый предпросмотр обновляется сам, когда меняется проект (исключили точку).
  useEffect(() => {
    if (!showPreview || !ready || !plan || planKey === key) return
    let alive = true
    fetchPlan(form).then(p => { if (alive) { setPlan(p); setPlanKey(planned) } }).catch(() => undefined)
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.revision])

  // Интерактивный вид того же графика; после исключения точки меняется ревизия проекта и график строится заново.
  useEffect(() => {
    if (!shownPlan || !showPreview || !liveOn || !shownPlan.charts.length) return
    const name = shownPlan.charts.some(c => c.name === chart) ? chart : shownPlan.charts[0].name
    if (name !== chart) { setChart(name); return }
    let alive = true
    setLiveChart(null)
    exportApi.chart(project.id, form, name).then(c => alive && setLiveChart(c))
      .catch(e => alive && setError('Не удалось отобразить этот график: ' + (e as Error).message))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownPlan, showPreview, chart, liveOn, labelsKey])

  const excludePoint = async (dataset: string, id: string) => {
    try {
      const r = await api.exclude(project.id, dataset, [id], [], 'Исключено кликом на графике (предпросмотр экспорта)')
      if (r.added) { setToast(`Точка исключена. Всего исключено: ${r.excluded}. Выгрузка учтет это изменение.`); onProject(await api.project(project.id)) }
    } catch (e) { setError((e as Error).message) }
  }

  // «Экспортировать обе панели»: берутся сохранённые виды двух панелей раздела. Если их ещё нет,
  // сохраняем то, что сейчас настроено в панелях раздела (последние параметры, их помнит окно).
  const adoptPanels = async (module: string): Promise<boolean> => {
    if (choices?.two_panels[module]) return true
    const read = (panel: number) => {
      try { const v = localStorage.getItem(`atlas:params:${project.id}:${module}` + (panel ? `:${panel}` : '')); return v === null ? null : JSON.parse(v) } catch { return null }
    }
    const [first, second] = [read(0), read(1)]
    if (!second) {
      setError('Вторая панель еще не настроена. Откройте раздел, включите «Две независимые панели», выберите параметры второй панели и вернитесь сюда.')
      return false
    }
    try {
      onProject(await api.saveState(project.id, module, first ?? {}, 0))
      onProject(await api.saveState(project.id, module, second, 1))
      setToast('Виды обеих панелей сохранены в проекте и будут выгружены.')
      return true
    } catch (e) { setError((e as Error).message); return false }
  }
  const loadPreset = () => {
    const values = choices?.presets[presetChoice]
    if (!values) return
    setForm(f => ({ ...f, ...values, modules: (values.modules as string[] | undefined) ?? modules }))
    setToast(`Шаблон «${presetChoice}» загружен.`)
  }
  const savePreset = () => run('preset', async () => {
    onProject(await exportApi.savePreset(project.id, presetName.trim(), { ...form, modules }))
    setToast(`Шаблон «${presetName.trim()}» сохранен в проекте.`)
  })
  const sync = () => run('sync', async () => {
    const values = await exportApi.sync(project.id)
    setForm(f => {
      const next = { ...f }
      for (const [k, v] of Object.entries(values)) { if (v === null) delete next[k]; else next[k] = v }
      return next
    })
    setToast('Параметры просмотра перенесены.')
  })

  // Одна кнопка: архив и Word по включённым модулям, пакет, ГГХ и (если включено в ГИС) Word и Excel — в один ZIP.
  const exportAll = () => run('all', async () => {
    const made: ExportResult[] = []
    if (readyPlan) {
      await prepare()
      const a = await exportApi.archive(project.id, form); setArchive({ key, result: a }); made.push(a)
      const w = await exportApi.word(project.id, form); setWord({ key, result: w }); made.push(w)
    }
    if (modules.includes('pack')) { const p = await exportApi.pack(project.id, form); setPack({ key, result: p }); made.push(p) }
    if (modules.includes('ggh')) { const g = await exportApi.ggh(project.id, form); setGgh({ key, result: g }); made.push(g) }
    if (form.gis_enabled === true && gisAvailable) {
      const g = await exportApi.gis(project.id, form); setGisFile(g); made.push(g)
      const h = await exportApi.gisHikg(project.id, form); setHikgFile(h); made.push(h)
    }
    const names = made.flatMap(r => r.files)
    if (!names.length) throw new Error('Включите в выгрузку хотя бы один модуль, пакет, ГГХ или ГИС.')
    const { file } = await exportApi.bundle(project.id, names)
    saveLink(projectsApi.exportUrl(project.id, file))
  })

  const ready_files = [...(word?.key === key ? word.result.files : []), ...(archive?.key === key ? archive.result.files : []),
    ...(pack?.key === key ? pack.result.files : []), ...(ggh?.key === key ? ggh.result.files : []),
    ...(gisFile ? gisFile.files : []), ...(hikgFile ? hikgFile.files : [])]
  const bundle = () => run('bundle', async () => {
    const { file } = await exportApi.bundle(project.id, ready_files)
    saveLink(projectsApi.exportUrl(project.id, file))
  })

  if (!choices) {
    return (
      <>
        <Title undo={undo} />
        {error ? <div className="note warning" role="alert">{error}</div> : <p className="muted loading-line">Загрузка…</p>}
      </>
    )
  }
  const F = { form, set, choices }
  const allTabs = [...choices.modules.map(m => m.id), ...EXTRAS]
  const setEnabled = (id: string, on: boolean) => set('modules', allTabs.filter(m => m === id ? on : modules.includes(m)))
  const packAvailable = choices.modules.some(m => m.id === 'production')
  const gghAvailable = !!choices.ggh
  const gisAvailable = !!choices.gis
  const extraTabs: [string, string][] = [...(packAvailable ? [['pack', 'Пакет по фонду'] as [string, string]] : []), ...(gghAvailable ? [['ggh', 'ГГХ (Word)'] as [string, string]] : []), ...(gisAvailable ? [['gis', 'ГИС и ГВК (Word)'] as [string, string]] : []), ['any', 'Любой график']]
  const gisPanel = !gisAvailable ? null : (
    <>
      <p className="lede">Word: страница на скважину — рисунок (ГВК, hг эф и Кг ср.взв по пачкам), таблица изменения ГВК и подпись. А4 альбомная. Скважины без замеров ГВК пропускаются.</p>
      <div className="param-bar flat">
        <Section title="Выгрузка">
          <Check {...F} field="gis_enabled" label="Включить ГИС и ГВК (Word и Excel) в «Скачать всё»" def={false} />
        </Section>
        {(choices.gis!.seasons ?? []).length > 0 && (
          <Section title="Сезоны">
            <Multi {...F} field="gis_seasons" label="Сезоны (Σ hi × Кг)" options={choices.gis!.seasons ?? []} empty="все" />
          </Section>
        )}
        <Section title="Подписи и качество">
          <Num {...F} field="gis_start" label="Первый номер рисунка" def={1} min={1} max={100000} />
          <Select {...F} field="gis_dpi" label="Качество графиков" def={200}
            options={[[150, '150 DPI, самый легкий'], [200, '200 DPI, рекомендуется'], [250, '250 DPI'], [300, '300 DPI']]} />
          <label className="toggle"><input type="checkbox" checked={!!form.gis_data} onChange={e => set('gis_data', e.target.checked)} /><span>Данные графиков отдельной книгой (XLSX)</span></label>
        </Section>
      </div>
      <div className="toolbar">
        <button type="button" disabled={gisBusy} onClick={async () => {
          setGisBusy(true)
          try { setGisFile(await exportApi.gis(project.id, form)) } catch (e) { setError((e as Error).message) }
          setGisBusy(false)
        }}>{gisBusy ? 'Создаю Word…' : 'Создать Word ГИС'}</button>
      </div>
      <div className="toolbar">
        <button type="button" disabled={hikgBusy} onClick={async () => {
          setHikgBusy(true)
          try { setHikgFile(await exportApi.gisHikg(project.id, form)) } catch (e) { setError((e as Error).message) }
          setHikgBusy(false)
        }}>{hikgBusy ? 'Создаю Excel…' : 'Создать Excel Σ hi × Кг'}</button>
      </div>
      {hikgFile && <Outcome title="Excel: Σ hi × Кг" result={hikgFile} pid={project.id} ggh />}
      {gisFile && <Outcome title="Word: ГИС и ГВК" result={gisFile} pid={project.id} ggh />}
    </>
  )
  const packPanel = (
    <>
      <p className="lede">Приложения к отчету: график «Производительность» каждой скважины фонда, по 2, 4 или 6 на лист A4. Шрифт, вид графиков, подписи и оформление берутся из общих настроек ниже.</p>
        <section className="table-block">
<p className="muted pad">График «Производительность» каждой скважины фонда по выбранным сезонам, по 2, 4 или 6 на лист A4,
            отдельный файл на отбор и на закачку. Графики легкие: палитровый PNG 200 DPI, легенда в одну строку под осями. Поля подписи: {'{раздел}, {номер}, {скважина}, {режим}, {годы}'}.</p>
          <div className="param-bar flat">
            <Section title="Выгрузка">
              <label className="toggle"><input type="checkbox" checked={modules.includes('pack')} onChange={e => setEnabled('pack', e.target.checked)} /><span>Включить пакет по фонду в выгрузку</span></label>
            </Section>
          </div>
          {!modules.includes('pack') ? <p className="muted pad">Включите, чтобы выбрать параметры. Файлы создаются кнопками «Сформировать архив» и «Создать отчет Word» внизу страницы вместе с остальными модулями.</p> : <>
          <div className="param-bar flat">
            <Section title="Состав">
              {KINDS.map(([k, l]) => {
                const chosen = (form.pack_kinds as string[] | undefined) ?? ['withdrawal', 'injection']
                return (
                  <label key={k} className="toggle">
                    <input type="checkbox" checked={chosen.includes(k)}
                      onChange={e => set('pack_kinds', e.target.checked ? [...chosen, k] : chosen.filter(x => x !== k))} />
                    <span>{l}</span>
                  </label>
                )
              })}
              {([['docx', 'Word'], ['pdf', 'PDF'], ['xlsx', 'Данные графиков (XLSX)']] as const).map(([k, l]) => {
                const chosen = (form.pack_formats as string[] | undefined) ?? ['docx', 'pdf']
                return (
                  <label key={k} className="toggle">
                    <input type="checkbox" checked={chosen.includes(k)}
                      onChange={e => set('pack_formats', e.target.checked ? [...chosen, k] : chosen.filter(x => x !== k))} />
                    <span>{l}</span>
                  </label>
                )
              })}
            </Section>
            <Section title="Сезоны и лист">
              {KINDS.filter(([k]) => ((form.pack_kinds as string[] | undefined) ?? ['withdrawal', 'injection']).includes(k)).map(([k, l]) => (
                <Multi key={k} {...F} field={`pack_periods_${k}`} label={`${l}: сезоны (обязательно)`} options={choices.periods?.[k] ?? []} />
              ))}
              <Select {...F} field="pack_per_page" label="Графиков на листе" def={6} options={[[2, '2'], [4, '4'], [6, '6']]} />
              <Select {...F} field="pack_dpi" label="Качество графиков" def={200}
                options={[[150, '150 DPI, самый легкий'], [200, '200 DPI, рекомендуется'], [250, '250 DPI'], [300, '300 DPI']]} />
            </Section>
            <Section title="Подписи">
              <Text {...F} field="pack_section_withdrawal" label="Раздел: отбор" def="П4" />
              <Text {...F} field="pack_section_injection" label="Раздел: закачка" def="П5" />
              <Text {...F} field="pack_template" label="Шаблон подписи" wide
                def="Рисунок {раздел}.{номер} - Производительность скважины №{скважина} при {режим} газа за {годы} гг." />
            </Section>
          </div>
          {packNoSeasons && <div className="note warning pad-x">Для пакета по фонду выберите хотя бы один сезон.</div>}
          </>}
        </section>
    </>
  )
  const gghPanel = !gghAvailable ? null : (
    <>
      <p className="lede">Word: страница на скважину по образцу отчета (график, таблица значений, подпись). Шрифт, вид «как в Excel», наклон подписей, шапка и правила для наборов данных («ГГХ») берутся из общих настроек ниже.</p>
        <section className="table-block">
<p className="muted pad">Страница на скважину: график (слева содержание, %, справа газонасыщенность, см³/л), под ним таблица значений по датам отбора
            и подпись «Рисунок В.N – Результаты ГГХИ по скважине № … горизонта». А4 альбомная; шрифт по умолчанию Times New Roman, как в образце отчета (меняется в общих настройках).
            Горизонт берется из данных скважины; скважины с одним замером пропускаются.</p>
          <div className="param-bar flat">
            <Section title="Выгрузка">
              <label className="toggle"><input type="checkbox" checked={modules.includes('ggh')} onChange={e => setEnabled('ggh', e.target.checked)} /><span>Включить ГГХ (Word) в выгрузку</span></label>
            </Section>
          </div>
          {!modules.includes('ggh') ? <p className="muted pad">Включите, чтобы выбрать параметры. Файлы создаются кнопками «Сформировать архив» и «Создать отчет Word» внизу страницы вместе с остальными модулями.</p> : <>
          <div className="param-bar flat">
            <Section title="Скважины">
              <Multi {...F} field="ggh_horizons" label="Горизонты" options={[...new Set(Object.values(choices.ggh!.horizon_of).filter(Boolean))].sort()} empty="все" />
            </Section>
            <Section title="Подписи и качество">
              <Text {...F} field="ggh_section" label="Раздел (буква приложения)" def="В" />
              <Num {...F} field="ggh_start" label="Первый номер рисунка" def={1} min={1} max={100000} />
              <Select {...F} field="ggh_dpi" label="Качество графиков" def={200}
                options={[[150, '150 DPI, самый легкий'], [200, '200 DPI, рекомендуется'], [250, '250 DPI'], [300, '300 DPI']]} />
              <label className="toggle"><input type="checkbox" checked={!!form.ggh_data} onChange={e => set('ggh_data', e.target.checked)} /><span>Данные графиков отдельной книгой (XLSX)</span></label>
            </Section>
          </div>
          </>}
        </section>
    </>
  )
  if (!choices.modules.length && !gghAvailable) {
    return <><Title undo={undo} /><div className="note info">В проекте нет данных для выгрузки. Загрузите данные в разделе «Импорт данных».</div></>
  }

  const first = view === 'pack' && packAvailable ? 'pack' : view === 'ggh' && gghAvailable ? 'ggh' : (choices.modules[0]?.id ?? extraTabs[0][0])
  const current = tab && (choices.modules.some(m => m.id === tab) || extraTabs.some(([id]) => id === tab) || (tab === 'custom' && readyPlan)) ? tab : first
  const formats = (form.formats as string[] | undefined) ?? ['svg', 'pdf']
  const style = choices.style
  const tabsRow = (
      <div className="tabs" role="tablist">
        {choices.modules.map(m => (
          <button key={m.id} type="button" role="tab" aria-selected={m.id === current} onClick={() => setTab(m.id)}
            className={modules.includes(m.id) ? 'on' : undefined}>{m.label}</button>
        ))}
        {extraTabs.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={id === current} onClick={() => setTab(id)}
            className={modules.includes(id) ? 'on' : undefined}>{label}</button>
        ))}
        {readyPlan && <button type="button" role="tab" aria-selected={current === 'custom'} onClick={() => setTab('custom')}>Отдельные графики</button>}
      </div>
  )
  if (current === 'any') return <><Title undo={undo} />{tabsRow}<TabWellFilter tab={current} choices={choices} form={form} projectId={project.id} onChange={() => undefined} /><ExportAnyChart project={project} onProject={onProject} /></>

  return (
    <>
      <Title undo={undo} />
      <ReadyFiles files={ready_files} pid={project.id} busy={busy !== null} onBundle={bundle} />

      <details className="table-block">
        <summary className="block-head"><h3>Шаблоны параметров экспорта</h3></summary>
        <div className="form-row pad">
          <label className="field">
            <span className="field-label">Сохраненный шаблон</span>
            <select value={presetChoice} onChange={e => setPresetChoice(e.target.value)}>
              <option value="" />
              {Object.keys(choices.presets).map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <button type="button" className="quiet" disabled={!presetChoice} onClick={loadPreset}>Загрузить шаблон</button>
          <label className="field wide">
            <span className="field-label">Название шаблона</span>
            <input value={presetName} maxLength={120} onChange={e => setPresetName(e.target.value)} />
          </label>
          <button type="button" className="quiet" disabled={!presetName.trim() || busy !== null} onClick={savePreset}>Сохранить шаблон экспорта</button>
        </div>
      </details>

      <div className="toolbar">
        <button type="button" className="quiet" disabled={busy !== null} onClick={sync}
          title="Параметры, сохраненные кнопкой «Сохранить» в разделах просмотра (общие с 5.8)">Взять параметры из вкладок просмотра</button>
      </div>

      <div className="param-bar">
        <Section title="Общие параметры файлов">
          <div className="field inline-checks" role="group" aria-label="Форматы графиков">
            <span className="field-label">Форматы графиков</span>
            <span>
              {['svg', 'pdf', 'png', 'xlsx', 'csv'].map(f => (
                <label key={f}><input type="checkbox" checked={formats.includes(f)} title={f === 'xlsx' || f === 'csv' ? 'Данные графика: ряды, X, Y' : undefined}
                  onChange={e => set('formats', ['svg', 'pdf', 'png', 'xlsx', 'csv'].filter(x => x === f ? e.target.checked : formats.includes(x)))} />{f === 'xlsx' || f === 'csv' ? `${f.toUpperCase()} (данные)` : f.toUpperCase()}</label>
              ))}
            </span>
          </div>
          <Select {...F} field="dpi" label="Разрешение PNG" def={300} options={[[300, '300'], [600, '600'], [1200, '1200']]} />
          <SizePick {...F} />
          <Select {...F} field="font" label="Шрифт" def="default"
            options={[['default', 'Стандартный (DejaVu Sans)'], ['times', 'Times New Roman'], ['arial_narrow', 'Arial Narrow'], ['calibri', 'Calibri (как в Excel)']]} />
          <Select {...F} field="look" label="Вид графиков" def="default" options={[['default', 'Обычный'], ['excel', 'Как диаграммы Excel']]} />
          <Select {...F} field="fmt_angle" label="Подписи оси X" def="auto" options={ANGLE_OPTIONS} />
          <Select {...F} field="fmt_title" label="Шапка графика" def="show" options={[['show', 'Показывать'], ['hide', 'Скрыть']]} />
          <Select {...F} field="fmt_legend" label="Легенда" def="bottom"
            options={[['bottom', 'Снизу'], ['top', 'Сверху'], ['right', 'Справа'], ['hide', 'Скрыть']]} />
          <Select {...F} field="fmt_grid" label="Сетка" def="" options={GRID_OPTIONS} />
          <Num {...F} field="fmt_grid_width" label="Толщина основной сетки, пт" def={0.7} min={0.2} max={4} step={0.1} />
          <Color label="Цвет основной сетки" value={form.fmt_grid_color} onChange={v => set('fmt_grid_color', v)} />
          <Select {...F} field="fmt_minor_grid" label="Доп. линии сетки" def="" options={MINOR_GRID_OPTIONS} />
          <Num {...F} field="fmt_minor_grid_width" label="Толщина доп. линий, пт" def={0.5} min={0.2} max={4} step={0.1} />
          <Color label="Цвет доп. линий" value={form.fmt_minor_grid_color} onChange={v => set('fmt_minor_grid_color', v)} />
          <Check {...F} field="fmt_axis_title_bold" label="Названия осей жирным" def={false} />
          <Check {...F} field="fmt_axis_title_italic" label="Названия осей курсивом" def={false} />
          <Check {...F} field="fmt_tick_bold" label="Деления осей жирным" def={false} />
          <Check {...F} field="fmt_tick_italic" label="Деления осей курсивом" def={false} />
          <Select {...F} field="font_size" label="Размер шрифта, пт" def={null}
            options={[[null, 'Авто (9)'], ...[7, 8, 9, 10, 11, 12, 14].map(n => [n, String(n)] as [number, string])]} />
          <Check {...F} field="exclusions" label="Применять исключения точек проекта" def />
          <Check {...F} field="raw" label="Добавить нормализованные данные" def={false} />
          {(['points', 'legend', 'grid'] as const).map(f => (
            <Check key={f} {...F} field={'style_' + f} def={style[f] ?? true}
              label={{ points: 'Экспорт: точки', legend: 'Экспорт: легенда', grid: 'Экспорт: сетка' }[f]} />
          ))}
        </Section>
      </div>

      {tabsRow}
      <TabWellFilter tab={current} choices={choices} form={form} projectId={project.id}
        onChange={(groups, wells) => setTabFilter(current, groups, wells)} />
      {current === 'custom' ? (
        <CustomCharts {...F} projectId={project.id} loadPlan={prepare} planned={planned} />
      ) : current === 'pack' || current === 'ggh' || current === 'gis' ? (
        <>
          {current === 'pack' ? packPanel : current === 'gis' ? gisPanel : gghPanel}
        </>
      ) : (
        <div className="param-bar">
          <ModuleTab key={current} module={current} label={choices.modules.find(m => m.id === current)!.label}
            enabled={modules.includes(current)} adoptPanels={adoptPanels} {...F}
            onEnable={on => setEnabled(current, on)} />
        </div>
      )}

      <ChartFormat {...F} modules={modules} projectId={project.id} ready={readyPlan} />
      <AxisSettings {...F} modules={modules} />

      <ChartLabels {...F} modules={modules} projectId={project.id} ready={readyPlan} />

      <WordLayout {...F} projectId={project.id} ready={readyPlan} revision={project.revision} />

      <details className="table-block">
        <summary className="block-head"><h3>Word: подписи под графиками</h3></summary>
        <p className="muted pad">Подпись — настоящая подпись Word (поле «Рисунок»): на неё можно сослаться, она попадает в список рисунков. Доступные поля: {'{раздел}, {номер}, {скважина}, {горизонт}, {период}, {модуль}'}.
          Нумерация идет отдельно внутри каждого модуля.</p>
        <div className="param-bar flat">
          {modules.map(m => {
            const d = choices.captions[m]
            if (!d) return null
            return (
              <Section key={m} title={choices.modules.find(x => x.id === m)?.label ?? m}>
                <Text {...F} field={'caption_section_' + m} label="Раздел" def={d.section} />
                <Num {...F} field={'caption_start_' + m} label="Первый номер" def={d.start} min={1} max={10000} />
                <Text {...F} field={'caption_template_' + m} label="Шаблон подписи" def={d.template} wide />
              </Section>
            )
          })}
        </div>
      </details>

      <div className="toolbar">
        <Check {...F} field="auto" label="Автоматически обновлять предпросмотр" def={false} />
        <span className="spacer" />
        {busy && <span className="pulse">{{ all: 'Создание всех файлов выгрузки и общего ZIP…', preview: 'Подготовка перечня графиков и расчетных таблиц…', archive: 'Создание архива…', word: 'Создание Word-отчета…', pack: 'Построение графиков всех скважин, это может занять несколько минут…', ggh: 'Построение графиков и страниц ГГХ…', bundle: 'Объединение созданных файлов…' }[busy] ?? 'Выполняется…'}</span>}
        <button type="button" className="quiet" disabled={!ready || busy !== null} onClick={preview}>Предпросмотр</button>
        <button type="button" className="primary" disabled={busy !== null || packNoSeasons} onClick={exportAll}
          title="Все включённые вкладки (модули, пакет, ГГХ, ГИС при включении) одним ZIP">Скачать всё</button>
        <button type="button" className="quiet" disabled={!ready || busy !== null || packNoSeasons} onClick={makeArchive}>Сформировать архив</button>
        <button type="button" className="quiet" disabled={!ready || busy !== null || packNoSeasons} onClick={makeWord}>Создать отчет Word</button>
      </div>
      {!ready && <div className="note info">Включите хотя бы один модуль в выгрузку.</div>}
      {error && <div className="note warning" role="alert">{error}</div>}

      {shownPlan && (
        <section className="table-block">
          <div className="block-head"><h3>Состав выгрузки</h3></div>
          <p className="muted pad">Графиков: {shownPlan.charts.length}; таблиц: {shownPlan.tables.length}. Предпросмотр строит только выбранный график.
            При массовом экспорте остальные строятся последовательно; каждый модуль сохраняется в один общий архив или документ без разбиения.</p>
          {shownPlan.note && <div className="note info pad-x">{shownPlan.note}</div>}
          {showPreview && shownPlan.charts.length > 0 && (
            <div className="pad">
              <label className="inline-field">График предпросмотра
                <select value={chart} onChange={e => setChart(e.target.value)}>
                  {shownPlan.charts.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                </select>
              </label>
              <div className="toolbar">
                {extraSel && <span className="muted small-text">Пакет по фонду и ГГХ показываются картинкой файла.</span>}
                {!extraSel && <label className="inline-field">Вид
                  <select value={live ? 'live' : 'image'} onChange={e => { setLive(e.target.value === 'live'); setExcludeMode(false) }}>
                    <option value="image">Картинка (макет файла)</option>
                    <option value="live">Интерактивный график</option>
                  </select>
                </label>}
                {liveOn && exclusions && (
                  <label className="toggle"><input type="checkbox" checked={excludeMode} onChange={e => setExcludeMode(e.target.checked)} /><span>Исключать точки кликом</span></label>
                )}
              </div>
              {liveOn ? (
                <>
                  <p className="muted small-text">Интерактивный вид того же графика: масштаб, подсказки{exclusions ? ' и исключение точек кликом (исключения сохраняются в проекте и попадут в выгрузку)' : ''}.
                    {!exclusions && ' Исключения проекта в этой выгрузке отключены, поэтому точки не выбираются.'}</p>
                  {excludeMode && <div className="note info">Щелкните по измеренной точке, чтобы исключить ее. Расчетные кривые и серые исключенные точки не выбираются.</div>}
                  {liveChart
                    ? <ChartView key={liveChart.id + chart} chart={liveChart} module={shownPlan?.charts.find(c => c.name === chart)?.module} excludeMode={excludeMode && exclusions} onExclude={excludePoint}
                        onDownload={async () => { throw new Error('Файлы выгрузки создаются кнопками «Сформировать архив» и «Создать отчет Word».') }} />
                    : <p className="pulse">Построение графика…</p>}
                </>
              ) : (
                <>
                  <p className="muted small-text">Макет статического файла в выбранном размере. Тяните за края и углы рамки, чтобы изменить ширину и высоту (Shift на углу сохраняет пропорции); размер попадёт в выгрузку. Для предпросмотра используется 150 DPI.
                    Чтобы исключать точки, переключите вид на «Интерактивный график».</p>
                  {image ? (() => {
                    const wMm = (form.width as number | undefined) ?? 220
                    const hMm = (form.height as number | undefined) ?? (natural ? Math.round(wMm * natural[1] / natural[0]) : Math.round(wMm * 0.68))
                    return (
                      <ResizableFrame widthMm={wMm} heightMm={hMm} onResize={(w, h) => { set('width', w); set('height', h) }}>
                        <img className="export-preview" src={image} alt={chart} draggable={false}
                          onLoad={e => setNatural([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} />
                      </ResizableFrame>
                    )
                  })() : <p className="pulse">Построение графика…</p>}
                </>
              )}
            </div>
          )}
        </section>
      )}

      {word?.key === key && <Outcome title="Отчет Word" result={word.result} pid={project.id} word />}
      {archive?.key === key && <Outcome title="Архив результатов" result={archive.result} pid={project.id} />}
      {pack?.key === key && <Outcome title="Пакет графиков по фонду" result={pack.result} pid={project.id} pack />}
      {ggh?.key === key && <Outcome title="Графики ГГХ для отчета" result={ggh.result} pid={project.id} ggh />}
      {ready_files.length > 0 && (
        <div className="toolbar">
          <button type="button" className="primary" disabled={busy !== null} onClick={bundle}>Скачать все созданные файлы одним ZIP</button>
          <span className="muted">Файлы также сохранены в разделе «Проекты».</span>
        </div>
      )}
      <Toast text={toast} onClose={closeToast} />
    </>
  )
}

/** Фильтр скважин вкладки: группы, скважины, пресеты проекта. Видим на каждой вкладке; выгрузка вкладки берет именно его. */
function TabWellFilter({ tab, choices, form, projectId, onChange }: { tab: string; choices: ExportChoices; form: Form; projectId: string;
  onChange: (groups: string[] | undefined, wells: string[] | undefined) => void }) {
  const [presets, setPresets] = useState<WellPreset[]>([])
  useEffect(() => { wellPresetApi.list(projectId).then(r => setPresets(r.presets)).catch(() => setPresets([])) }, [projectId])
  const fields = filterFields(tab)
  const wells = fields ? wellsOf(tab, choices, form) : []
  if (!fields || !wells.length) {
    const note = tab === 'custom' ? 'Отдельные графики берутся из уже выбранных вкладок: фильтр задается на них.'
      : tab === 'any' ? 'Любой график строится по параметрам своего раздела: скважины и фильтр скважин задаются в его панели.'
      : fields ? 'Скважин для фильтра на этой вкладке нет: выбор скважин задан в ее панели.'
      : 'На этой вкладке фильтр скважин не применяется.'
    return <p className="muted pad filter-note">{note}</p>
  }
  const groups = [...new Set(wells.map(w => groupOf(choices, w)))]
  const chosenGroups = (((fields.groups && form[fields.groups]) as string[] | undefined) ?? groups).filter(g => groups.includes(g))
  const available = wells.filter(w => chosenGroups.includes(groupOf(choices, w)))
  const chosen = (((form[fields.wells]) as string[] | undefined) ?? available).filter(w => available.includes(w))
  const pickGroups = (next: string[]) => {
    const kept = wells.filter(w => next.includes(groupOf(choices, w)) && chosen.includes(w))
    onChange(fields.groups ? next : undefined, kept)
  }
  const pickPreset = (id: string) => {
    const preset = presets.find(p => p.id === id)
    if (!preset) return
    const picked = wells.filter(w => preset.wells.includes(w))
    onChange(fields.groups ? [...new Set(picked.map(w => groupOf(choices, w)))] : undefined, picked)
  }
  return (
    <section className="table-block tab-filter">
      <div className="block-head"><h3>Фильтр скважин: эта вкладка</h3><span className="muted">выбрано {chosen.length} из {wells.length}</span></div>
      <div className="param-bar flat">
        <Section title="Выбор">
          {fields.groups && <MultiSelect label="Группы" options={groups} value={chosenGroups} emptyMeaning="ничего" onChange={pickGroups} />}
          <MultiSelect label="Скважины" options={available} value={chosen} emptyMeaning="ничего" prefix="№ "
            onChange={v => onChange(fields.groups ? chosenGroups : undefined, v)} />
        </Section>
        <Section title="Пресеты проекта">
          <label className="field">
            <span className="field-label">Применить пресет</span>
            <select value="" onChange={e => pickPreset(e.target.value)} disabled={!presets.length}>
              <option value="" />
              {presets.map(p => <option key={p.id} value={p.id}>{p.label} ({p.wells.length})</option>)}
            </select>
          </label>
          <button type="button" className="quiet" onClick={() => onChange(undefined, undefined)}>Все скважины</button>
        </Section>
      </div>
    </section>
  )
}

function Title({ undo }: { undo: Undo }) {
  return (
    <header className="module-title">
      <div>
        <h1>Экспорт результатов</h1>
        <p className="lede">Параметры выгрузки, предпросмотр каждой диаграммы, архивы и отчет Word.</p>
      </div>
      <UndoButtons undo={undo} />
    </header>
  )
}

/** Готовые файлы вверху страницы: кнопки «Сохранить как…» видны сразу, без прокрутки вниз. */
function ReadyFiles({ files, pid, busy, onBundle }: { files: string[]; pid: string; busy: boolean; onBundle: () => void }) {
  if (!files.length) return null
  return (
    <section className="table-block ready-files" aria-label="Готовые файлы">
      <div className="block-head"><h3>Готовые файлы ({files.length})</h3></div>
      <div className="toolbar">
        {files.map(f => <button key={f} type="button" onClick={() => saveLink(projectsApi.exportUrl(pid, f))}>Сохранить {f}…</button>)}
        {files.length > 1 && <button type="button" className="primary" disabled={busy} onClick={onBundle}>Все файлы одним ZIP…</button>}
      </div>
    </section>
  )
}

function Outcome({ title, result, pid, word, pack, ggh }: { title: string; result: ExportResult; pid: string; word?: boolean; pack?: boolean; ggh?: boolean }) {
  const partial = result.errors.length > 0
  return (
    <section className="table-block">
      <div className="block-head"><h3>{title}</h3></div>
      <div className={'note ' + (partial ? 'warning' : 'info') + ' pad-x'}>
        {ggh
          ? partial ? `Word создан: страниц ${result.completed} из ${result.planned}; пропущено ${result.errors.length}.` : `Word готов: страниц (скважин) ${result.completed}`
          : pack
          ? partial ? `Пакет создан частично: графиков ${result.completed}/${result.planned}; ошибок ${result.errors.length}.`
            : `Пакет готов: графиков ${result.completed}; файлов ${result.files.length}`
          : word
          ? partial ? `Word создан частично. Ошибок: ${result.errors.length}. Причины включены в документ соответствующего модуля.`
            : `Word: сохранено графиков ${result.completed}; документов ${result.files.length}`
          : partial ? `Экспорт завершен частично: графиков ${result.completed}/${result.planned}; ошибок ${result.errors.length}. Готовые файлы сохранены. Журнал export_errors.csv включен в архив соответствующего модуля.`
            : `Готово: ${result.completed} графиков, ${result.chart_files} файлов графиков; единых архивов модулей: ${result.files.length}. Таблицы и журнал включены в каждый архив.`}
      </div>
      {partial && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>График</th><th>Формат</th><th>Ошибка</th></tr></thead>
            <tbody>{result.errors.map((e, i) => <tr key={i}><td>{e['График']}</td><td>{e['Формат']}</td><td>{e['Ошибка']}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      <ul className="file-list pad">
        {result.files.map(f => <li key={f}><button type="button" className="link-button" onClick={() => saveLink(projectsApi.exportUrl(pid, f))}>{f}</button></li>)}
        {result.files.length === 0 && <li className="muted">Нет готовых файлов.</li>}
      </ul>
    </section>
  )
}

// ---------- поля формы ----------


function DateField({ form, set, field, label, def }: FieldProps & { field: string; label: string; def: string }) {
  return (
    <label className="field date">
      <span className="field-label">{label}</span>
      <input type="date" value={((form[field] as string | undefined) ?? def).slice(0, 10)} onChange={e => e.target.value && set(field, e.target.value)} />
    </label>
  )
}

/** Список с флажками. Не задано — значение 5.8 по умолчанию (``def``, обычно «все»). */
function Multi({ form, set, field, label, options, def, empty = 'ничего', prefix }:
  FieldProps & { field: string; label: string; options: string[]; def?: string[]; empty?: string; prefix?: string }) {
  const stored = form[field] as string[] | undefined
  const value = (stored ?? def ?? options).filter(v => options.includes(v))
  return <MultiSelect label={label} options={options} value={value} emptyMeaning={empty} prefix={prefix} onChange={v => set(field, v)} />
}

function ModuleTab({ module, label, enabled, onEnable, adoptPanels, ...F }: FieldProps & {
  module: string; label: string; enabled: boolean; onEnable: (on: boolean) => void; adoptPanels: (module: string) => Promise<boolean>
}) {
  const { form, choices } = F
  const head = (
    <Section title="Выгрузка">
      <label className="toggle"><input type="checkbox" checked={enabled} onChange={e => onEnable(e.target.checked)} /><span>Включить {label} в выгрузку</span></label>
    </Section>
  )
  if (!enabled) return <>{head}<p className="muted pad">Включите модуль для выбора графиков и таблиц.</p></>
  if (module === 'object_pressure') return <>{head}<p className="muted pad">Пластовое давление объекта: один график и таблица замеров.</p></>
  if (module === 'pressure_match') {
    return (
      <>
        {head}
        <Section title="Кроссплот давлений">
          <Select {...F} field="pressure_pm_export_split" label="Построение при экспорте" def="all"
            options={[['all', 'Все выбранные вместе'], ['well', 'Отдельно по скважинам'], ['group', 'Отдельно по группам']]} />
        </Section>
        <p className="muted pad">Объекты, сценарии, скважины, пороги и оформление берутся из сохраненного вида раздела «Кроссплот давлений»
          (кнопка «Сохранить» в разделе).</p>
      </>
    )
  }

  if (module === 'waterfactor') {
    const seasons = choices.water?.periods ?? []
    return (
      <>
        {head}
        <Section title="Вынос воды и водный фактор">
          <Multi {...F} field="waterfactor_periods" label="Сезоны отбора" options={seasons} def={seasons.slice(-5)} />
          <Num {...F} field="waterfactor_start" label="Объём газа в пласте на начало данных, млн м³" def={0} min={0} max={1e9} step={100} />
          <Select {...F} field="waterfactor_metric" label="График" def="all"
            options={[['all', 'Все три'], ['carry', 'Накопленный вынос воды'], ['daily', 'Суточный водный фактор'], ['cumulative', 'Накопленный водный фактор']]} />
          <Select {...F} field="waterfactor_xaxis" label="Ось X" def="volume"
            options={[['volume', 'По объёму газа в пласте'], ['cumulative', 'По накопленному отбору за сезон']]} />
          <Check {...F} field="waterfactor_inverse" label="Ось X справа налево (объём убывает)" def />
        </Section>
        <p className="muted pad">Данные и расчёт — как в разделе «Вынос воды и водный фактор»; цвета, оси и подписи — в общих настройках оформления.</p>
      </>
    )
  }

  const groups = choices.groups[module] ?? []
  const prefix = module === 'well_dashboard' ? 'dashboard' : module
  const chosenGroups = ((form[module + '_groups'] as string[] | undefined) ?? groups).filter(g => groups.includes(g))
  const wells = (choices.wells[module] ?? []).filter(w => chosenGroups.includes(choices.mapping[w] ?? 'Без группы'))
  let body: ReactNode = null
  if (module === 'production' || module === 'histograms') {
    const split = (form[module + '_split'] as string | undefined) ?? 'well'
    const chosenWells = ((form[prefix + '_wells'] as string[] | undefined) ?? wells).filter(w => wells.includes(w))
    body = (
      <>
        <Section title="Периоды">
          {KINDS.map(([kind, name]) => (
            <Multi key={kind} {...F} field={`${module}_periods_${kind}`} label={name + ' — периоды'} options={choices.periods?.[kind] ?? []} />
          ))}
        </Section>
        <Section title="Построение">
          {module === 'production' && <Select {...F} field="production_view" label="Производительность: вид графика" def="curve"
            options={[['curve', 'Q / накопленный объем'], ['time', 'Q / дата']]} />}
          <Select {...F} field={module + '_split'} label={label + ': построение'} def="well"
            options={module === 'production' ? [...SPLIT, ['group_total', 'Сумма по каждой группе + скважины']] : SPLIT} />
          <Select {...F} field={module + '_direction'} label={label + ': порядок'} def="number" options={DIRECTION} />
          <label className="toggle" title="В разделе можно открыть две независимые панели с разными фильтрами. Включите, чтобы выгрузить графики обеих панелей, а не только выбранное здесь.">
            <input type="checkbox" checked={form[module + '_panels'] === true}
              onChange={async e => { const on = e.target.checked; F.set(module + '_panels', on && (await adoptPanels(module))) }} />
            <span>Скачать обе панели · {label}</span>
          </label>
          {split === 'group_total' && <>
            <Select {...F} field="production_metric" label="Суммарный показатель" def="daily"
              options={[['daily', 'Суточный расход'], ['cumulative', 'Накопленный объем'], ['active', 'Работающие скважины']]} />
            <Multi {...F} field="production_overlay" label="Наложение скважин" options={chosenWells} def={[]} prefix="№ " />
          </>}
          {split === 'subgroup' && <>
            <Select {...F} field={module + '_groupmode'} label="Подгруппы" def="manual" options={[['manual', 'manual'], ['auto', 'auto']]} />
            <Num {...F} field={module + '_size'} label="Скважин на график подгруппы" def={8} min={1} max={30} />
          </>}
          {module === 'histograms' && <>
            <Select {...F} field="histograms_histaxis" label="Ось гистограммы" def="well" options={[['well', 'Скважины'], ['period', 'Периоды']]} />
            <Select {...F} field="histograms_hist_size" label="Скважин на одной гистограмме" def="Авто"
              options={['Авто', '10', '20', '50', 'Все'].map(v => [v, v] as Opt)} />
          </>}
        </Section>
        {module === 'production' && choices.has_elpro && (
          <Section title="Ряды ЭЛПРО на суточных графиках">
            {ELPRO_ROWS.map(([key, name]) => (
              <Check key={key} {...F} field={'production_elpro_' + key} label={name} def={false} />
            ))}
            <p className="muted pad">Отдельный график на скважину и режим: суточный расход и выбранные ряды, каждый на своей
              оси справа.</p>
          </Section>
        )}
        {split === 'group_total' && <p className="muted pad">Сумма включает весь состав группы; список наложения меняет только отдельные кривые.</p>}
      </>
    )
  } else if (module === 'gdi') {
    body = (
      <Section title="ГДИ">
        <Select {...F} field="gdi_n" label="ГДИ: последние даты" def={3} options={[[1, '1'], [2, '2'], [3, '3'], [0, 'Все']]} />
        <Select {...F} field="gdi_orientation" label="ГДИ: оси" def="standard" options={ORIENTATION} />
        <Check {...F} field="gdi_curves" label="ГДИ: расчетные кривые" def />
        <Check {...F} field="gdi_db_curves" label="ГДИ: кривые по коэффициентам БД" def />
        <Check {...F} field="gdi_crosshair" label="ГДИ: перекрестная линейка" def />
        <Check {...F} field="gdi_show_excluded" label="ГДИ: показывать исключенные точки" def />
        {(choices.gdi_seasons?.length ?? 0) > 0 &&
          <Multi {...F} field="gdi_seasons" label="ГДИ: сезоны" options={choices.gdi_seasons!} def={[]} empty="все" />}
      </Section>
    )
  } else if (module === 'response') {
    const dates = (form.response_dates as string[] | undefined) ?? choices.response_dates ?? ['', '']
    body = (
      <Section title="Реагирование">
        <Multi {...F} field="response_horizons" label="Горизонты" options={choices.horizons ?? []} />
        <Multi {...F} field="response_working" label="Рабочие горизонты" options={choices.horizons ?? []} def={choices.working ?? []} />
        <DateField {...{ ...F, form: { d0: dates[0] } }} field="d0" label="Реагирование: период с" def={dates[0]}
          set={(_, v) => F.set('response_dates', [v, dates[1]])} />
        <DateField {...{ ...F, form: { d1: dates[1] } }} field="d1" label="по" def={dates[1]}
          set={(_, v) => F.set('response_dates', [dates[0], v])} />
        <Select {...F} field="response_mode" label="Реагирование: выгрузка" def="all"
          options={[['all', 'По настройкам ниже'], ['both', 'Контрольные и рабочие горизонты'], ['control', 'Контрольные: все скважины на одном графике, только уровень'], ['working', 'Рабочие: по скважине, уровень и давление']]} />
        {((form.response_mode as string | undefined) ?? 'all') !== 'all' &&
          <Select {...F} field="response_working_view" label="Рабочие горизонты: вид" def="combined"
            options={[['combined', 'Уровень + давление (две шкалы Y)'], ['separate', 'Уровень и давление отдельно']]} />}
        <Select {...F} field="response_view" label="Реагирование: вид графиков" def="separate"
          options={[['separate', 'Уровень и давление отдельно'], ['combined', 'Уровень + давление'], ['level', 'Только уровень'], ['pressure', 'Только давление']]} />
        <Select {...F} field="response_split" label="Реагирование: построение" def="horizon"
          options={[['horizon', 'По горизонтам'], ['all', 'Все вместе'], ['well', 'По скважинам']]} />
      </Section>
    )
  } else if (module === 'well_dashboard') {
    const kind = ((form.dashboard_kind as string | undefined) ?? 'withdrawal') as 'withdrawal' | 'injection'
    body = (
      <>
        <Section title="Анализ">
          <Select {...F} field="dashboard_kind" label="Анализ: режим" def="withdrawal" options={[['withdrawal', 'Отбор'], ['injection', 'Закачка']]} />
          <Multi {...F} field="dashboard_periods" label="Анализ: периоды" options={choices.dashboard_periods?.[kind] ?? []} def={[]} empty="все" />
          <Select {...F} field="dashboard_method" label="Анализ: метод ГДИ" def={null}
            options={[[null, 'Все методы'], ...(choices.gdi_methods ?? []).map(m => [m, m || 'Без метода'] as Opt)]} />
          <Check {...F} field="dashboard_fixed" label="Анализ: общий ΔP² вручную" def={false} />
          {form.dashboard_fixed === true && <Num {...F} field="dashboard_delta" label="Анализ: общий ΔP²" def={500} min={0.001} max={1e9} step={10} />}
          <DateField {...F} field="dashboard_asof" label="Анализ: дата состояния" def={choices.asof ?? ''} />
          <Num {...F} field="dashboard_threshold" label="Анализ: порог изменения, %" def={10} min={1} max={80} />
          <Select {...F} field="dashboard_alignment" label="Анализ: начало отсчета сезонов" def="well"
            options={[['well', 'Первый замер скважины = 0'], ['object', 'Первый день данных объекта']]} />
        </Section>
        <Section title="График ГДИ">
          <Select {...F} field="dashboard_gdi_n" label="Анализ: последние даты ГДИ" def={0} options={[[0, 'Все'], [1, '1'], [2, '2'], [3, '3']]} />
          <Select {...F} field="dashboard_gdi_orientation" label="Анализ: оси ГДИ" def="standard" options={ORIENTATION} />
          <Check {...F} field="dashboard_gdi_curves" label="Анализ: расчетные кривые" def />
          <Check {...F} field="dashboard_gdi_db" label="Анализ: кривые БД" def />
          <Check {...F} field="dashboard_gdi_crosshair" label="Анализ: линейка" def />
          <Check {...F} field="dashboard_gdi_excluded" label="Анализ: исключенные точки ГДИ" def />
          {(choices.gdi_seasons?.length ?? 0) > 0 &&
            <Multi {...F} field="dashboard_gdi_seasons" label="Анализ: сезоны ГДИ" options={choices.gdi_seasons!} def={[]} empty="все" />}
        </Section>
        <Section title="Графики">
          <ChartsPick {...F} />
        </Section>
      </>
    )
  }
  return <>{head}{body}</>
}

function ChartsPick(F: FieldProps) {
  const labels = useMemo(() => Object.fromEntries((F.choices.dashboard_charts ?? []).map(c => [c.label, c.id])), [F.choices])
  const ids = useRef(F.choices.dashboard_charts ?? []).current
  const chosen = ((F.form.dashboard_charts as string[] | undefined) ?? ids.map(c => c.id))
  return (
    <MultiSelect label="Анализ: графики" options={ids.map(c => c.label)} value={ids.filter(c => chosen.includes(c.id)).map(c => c.label)}
      emptyMeaning="ничего" onChange={v => F.set('dashboard_charts', v.map(l => labels[l]))} />
  )
}

const PAPER: Opt[] = [['A4', 'A4'], ['A3', 'A3'], ['A5', 'A5'], ['Letter', 'Letter']]
const FONT_LIST: Opt[] = ['Times New Roman', 'Arial', 'Calibri', 'Cambria', 'Verdana', 'Tahoma', 'Georgia'].map(f => [f, f] as Opt)

/** «Макет Word»: лист, поля, колонки, размер графиков, подпись и предпросмотр страниц будущего документа. */
function WordLayout({ form, set, choices, projectId, ready, revision }: FieldProps & { projectId: string; ready: boolean; revision: number }) {
  const F = { form, set, choices }
  const [open, setOpen] = useState(false)
  const [doc, setDoc] = useState(0)
  const [page, setPage] = useState(1)
  const [shot, setShot] = useState<WordPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wordKey = JSON.stringify([revision, Object.entries(form).filter(([k]) => k.startsWith('word_') || k.startsWith('label_') || k.startsWith('fmt_') || k.startsWith('caption_') || k.startsWith('gdi_') || k.startsWith('production_') || k.startsWith('response_') || k.startsWith('waterfactor_') || k === 'modules' || k === 'width' || k === 'height' || k === 'font' || k === 'font_size' || k === 'look'), doc, page])
  useEffect(() => {
    if (!open || !ready) return
    let alive = true
    const timer = setTimeout(() => {
      setBusy(true)
      exportApi.wordPreview(projectId, form, doc, page).then(r => { if (alive) { setShot(r); setError(null); if (r.page !== page) setPage(r.page) } })
        .catch(e => alive && setError((e as Error).message)).finally(() => alive && setBusy(false))
    }, 450)
    return () => { alive = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ready, wordKey, projectId])
  const per = (form.word_per_page as number | undefined) ?? 0
  const fill = ((form.word_width_mode as string | undefined) ?? 'fill') === 'fill'
  return (
    <details className="table-block" onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="block-head"><h3>Word: макет листа и предпросмотр</h3></summary>
      <p className="muted pad">График строится сразу под размер места на листе, поэтому не сужается и текст на нём остаётся читаемым.
        Предпросмотр рисует лист так, как его уложит Word.</p>
      <div className="word-layout">
        <div className="param-bar flat">
          <Section title="Лист">
            <Select {...F} field="word_orientation" label="Ориентация" def="portrait" options={[['portrait', 'Книжная'], ['landscape', 'Альбомная']]} />
            <Select {...F} field="word_paper" label="Формат" def="A4" options={PAPER} />
            <Num {...F} field="word_margin_top" label="Поле сверху, мм" def={20} min={0} max={80} />
            <Num {...F} field="word_margin_bottom" label="Поле снизу, мм" def={20} min={0} max={80} />
            <Num {...F} field="word_margin_left" label="Поле слева, мм" def={25} min={0} max={80} />
            <Num {...F} field="word_margin_right" label="Поле справа, мм" def={15} min={0} max={80} />
            <Check {...F} field="word_page_numbers" label="Номера страниц" def={false} />
            {Boolean(form.word_page_numbers) && <>
              <Select {...F} field="word_page_number_pos" label="Положение номера" def="footer-center" options={[['footer-center', 'Внизу по центру'], ['footer-left', 'Внизу слева'], ['footer-right', 'Внизу справа'], ['header-center', 'Вверху по центру'], ['header-left', 'Вверху слева'], ['header-right', 'Вверху справа']]} />
              <Select {...F} field="word_page_number_format" label="Вид номера" def="n" options={[['n', '3'], ['page', 'Страница 3'], ['of', '3 из 12'], ['page_of', 'Страница 3 из 12']]} />
              <Num {...F} field="word_page_start" label="Первый номер страницы" def={1} min={1} max={9999} />
            </>}
          </Section>
          <Section title="Колонтитулы">
            <Text {...F} field="word_header_text" label="Верхний колонтитул" def="" wide />
            <Text {...F} field="word_footer_text" label="Нижний колонтитул" def="" wide />
            <Select {...F} field="word_hf_align" label="Выравнивание текста" def="center" options={[['left', 'Влево'], ['center', 'По центру'], ['right', 'Вправо']]} />
            <Num {...F} field="word_hf_size" label="Размер, пт" def={9} min={6} max={20} />
            <p className="muted small-text">Поля: {'{страница}, {страниц}, {проект}, {дата}'} — страница и число страниц обновляются в самом Word.</p>
          </Section>
          <Section title="Графики на листе">
            <Num {...F} field="word_columns" label="Колонок" def={1} min={1} max={3} />
            <Num {...F} field="word_per_page" label="Графиков на листе (0 — сколько влезет)" def={0} min={0} max={24} />
            <Select {...F} field="word_width_mode" label="Ширина графика" def="fill" options={[['fill', 'На всю ширину колонки'], ['mm', 'Задать в мм']]} />
            {!fill && <Num {...F} field="word_width_mm" label="Ширина, мм" def={160} min={40} max={400} />}
            <Num {...F} field="word_height_mm" label="Высота, мм (0 — по пропорциям)" def={0} min={0} max={400} />
            <Num {...F} field="word_gap" label="Промежуток между колонками, мм" def={4} min={0} max={30} />
            <Num {...F} field="word_row_gap" label="Отступ между рядами, мм" def={6} min={0} max={60} />
            <Select {...F} field="word_borders" label="Линии между графиками" def="none" options={[['none', 'Нет'], ['thin', 'Тонкая сетка']]} />
            <Check {...F} field="word_frame" label="Рамка вокруг графика" def={false} />
            <Select {...F} field="word_dpi" label="Качество (DPI)" def={300} options={[[150, '150'], [200, '200'], [250, '250'], [300, '300'], [600, '600 (тяжелее)']]} />
            <Check {...F} field="word_compress" label="Сжать картинки (легче файл)" def={false} />
          </Section>
          <Section title="Подпись">
            <Check {...F} field="word_caption_show" label="Подписи рисунков" def={true} />
            <Select {...F} field="word_caption_mode" label="Вид подписи" def="field" options={[['field', 'Подпись Word (поле «Рисунок», ссылки)'], ['text', 'Обычный текст']]} />
            <Select {...F} field="word_caption_pos" label="Положение" def="below" options={[['below', 'Под графиком'], ['above', 'Над графиком']]} />
            <Select {...F} field="word_caption_font" label="Шрифт" def="Times New Roman" options={FONT_LIST} />
            <Num {...F} field="word_caption_size" label="Размер, пт" def={12} min={6} max={28} />
            <Select {...F} field="word_caption_align" label="Выравнивание" def="center" options={[['center', 'По центру'], ['left', 'Влево'], ['right', 'Вправо'], ['justify', 'По ширине']]} />
            <Num {...F} field="word_caption_gap" label="Отступ от графика, мм" def={2} min={0} max={30} />
            <Check {...F} field="word_caption_bold" label="Жирная" def={false} />
            <Check {...F} field="word_caption_italic" label="Курсив" def={false} />
          </Section>
          <Section title="Документ">
            <Check {...F} field="word_merge" label="Все модули в одном документе" def={false} />
            <Check {...F} field="word_title" label="Заголовок в начале" def={false} />
            {Boolean(form.word_title) && <Text {...F} field="word_title_text" label="Текст заголовка" def="" wide />}
            <Check {...F} field="word_list_of_figures" label="Список рисунков с гиперссылками" def={false} />
            {Boolean(form.word_title) && <>
              <Num {...F} field="word_title_size" label="Размер заголовка, пт (0 — авто)" def={0} min={0} max={48} />
              <Select {...F} field="word_title_align" label="Выравнивание заголовка" def="left" options={[['left', 'Влево'], ['center', 'По центру'], ['right', 'Вправо']]} />
            </>}
            <Select {...F} field="word_figure_align" label="Выравнивание рисунка" def="center" options={[['center', 'По центру'], ['left', 'Влево'], ['right', 'Вправо']]} />
            <Select {...F} field="word_text_font" label="Шрифт текста и колонтитулов" def="" options={[['', 'Как у подписи'], ...FONT_LIST]} />
            <Num {...F} field="word_text_size" label="Размер текста, пт (0 — как у подписи)" def={0} min={0} max={28} />
            <Text {...F} field="word_doc_title" label="Свойства файла: название" def="" wide />
            <Text {...F} field="word_doc_author" label="Свойства файла: автор" def="" wide />
          </Section>
        </div>
        <div className="word-shot">
          {!ready ? <p className="muted">Включите хотя бы один модуль.</p> : (
            <WordViewerPane shot={shot} busy={busy} error={error} page={page} setPage={f => setPage(f(page))} doc={doc} setDoc={setDoc} per={per} />
          )}
        </div>
      </div>
    </details>
  )
}

/** Свои названия графика, осей и записей легенды для каждого типа выгружаемых графиков (Word, архив, предпросмотр). */
function ChartLabels({ form, set, choices, modules, projectId, ready }: FieldProps & { modules: string[]; projectId: string; ready: boolean }) {
  const rows = styleRows(modules, choices)
  const [defaults, setDefaults] = useState<Record<string, Record<string, string>>>({})
  const [open, setOpen] = useState(false)
  useEffect(() => {      // названия графика и осей, как они сейчас в графиках, — шаблон для полей
    if (!open) return
    let alive = true
    exportApi.series(projectId, form).then(r => alive && setDefaults(r.labels ?? {})).catch(() => undefined)
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ready, JSON.stringify(form.modules), projectId])
  const shown = (m: string): Record<string, string> =>      // у пакета те же названия, что у «Производительности»; у ГГХ свои
    m === 'ggh' ? { title: 'Скважина №{скважина}', x: 'Год', y: 'Содержание, %', y2: 'Газонасыщенность, см³/л' } : defaults[m === 'pack' ? 'production' : m] ?? {}
  return (
    <details className="table-block" onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="block-head"><h3>Подписи осей и легенд по типам графиков</h3></summary>
      <p className="muted pad">Пустое поле — как в графике. Названия графика можно писать с {'{скважина}'}.
        Легенда: по строке «что=на что» — фрагмент названия заменится; «что=» без замены убирает запись из легенды.
        Подписи действуют на предпросмотр, архив и Word.</p>
      <div className="param-bar flat">
        {rows.map(m => {
          const f = (name: string) => 'label_' + m + '_' + name
          return (
            <Section key={m} title={styleLabel(m, choices)}>
              <Text {...{ form, set, choices }} field={f('title')} label="Название графика" def={shown(m).title ?? ''} />
              <Text {...{ form, set, choices }} field={f('x')} label="Ось X" def={shown(m).x ?? ''} />
              <Text {...{ form, set, choices }} field={f('y')} label="Ось Y" def={shown(m).y ?? ''} />
              <Text {...{ form, set, choices }} field={f('y2')} label="Вторая ось Y (если есть)" def={shown(m).y2 ?? ''} />
              {m === 'gdi' && <Text {...{ form, set, choices }} field={f('template')} label="Запись легенды: {дата}, {метод}, {исследование} (пусто — полная)" def="{дата}" wide />}
              <label className="field wide">
                <span className="field-label">Замены в легенде (по строке «что=на что»)</span>
                <textarea rows={3} value={(form[f('legend')] as string | undefined) ?? ''} maxLength={2000}
                  onChange={e => set(f('legend'), e.target.value)} />
              </label>
            </Section>
          )
        })}
      </div>
    </details>
  )
}

interface SeriesRule { match: string; color?: string; width?: number | string; marker?: number | string; hide?: boolean }

const ANGLE_OPTIONS: Opt[] = [['auto', 'Как есть'], ['0', 'Горизонтально'], ['30', '30°'], ['45', '45°'], ['60', '60°'], ['90', 'Вертикально']]

interface AxisSpec { min?: string; max?: string; major?: string; minor?: string; dates?: boolean; majorUnit?: string; minorUnit?: string }
type AxesSpec = Partial<Record<'x' | 'y' | 'y2', AxisSpec>>
const UNIT_OPTIONS: [string, string][] = [['year', 'год'], ['month', 'месяц'], ['day', 'день']]

/** Поле формы ``fmt_<модуль>_axes`` (JSON, см. atlas/chart_format.py): пустые поля не передаются. */
function axesPayload(spec: AxesSpec): string {
  const out: Record<string, unknown> = {}
  for (const [key, a] of Object.entries(spec)) {
    if (!a) continue
    const item: Record<string, unknown> = { dates: !!a.dates }
    if (a.min) item.min = a.min
    if (a.max) item.max = a.max
    for (const part of ['major', 'minor'] as const) {
      if (!a[part]) continue
      item[part] = a.dates ? { unit: a[part === 'major' ? 'majorUnit' : 'minorUnit'] || 'year', n: a[part] } : a[part]
    }
    if (Object.keys(item).length > 1) out[key] = item
  }
  return Object.keys(out).length ? JSON.stringify(out) : ''
}

/** Поля границ и делений трёх осей: общие для типа графиков и для отдельного графика. */
function AxesEditor({ spec, onEdit }: { spec: AxesSpec; onEdit: (axis: 'x' | 'y' | 'y2', patch: AxisSpec) => void }) {
  const edit = onEdit
  return (
  <div className="field wide">
    {(['y', 'y2', 'x'] as const).map(axis => {
      const a = spec[axis] ?? {}
      const dates = axis === 'x' && !!a.dates
      const input = (key: 'min' | 'max' | 'major' | 'minor', placeholder: string) => (
        <input value={a[key] ?? ''} placeholder={placeholder} aria-label={placeholder} size={dates && (key === 'min' || key === 'max') ? 11 : 7}
          inputMode={dates && (key === 'min' || key === 'max') ? 'text' : 'decimal'} onChange={e => edit(axis, { [key]: e.target.value })} />
      )
      const unit = (key: 'majorUnit' | 'minorUnit') => (
        <select value={a[key] ?? 'year'} aria-label="Единица деления" onChange={e => edit(axis, { [key]: e.target.value })}>
          {UNIT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      )
      return (
        <div key={axis} className="series-rule">
          <strong>{axis === 'x' ? 'Ось X' : axis === 'y' ? 'Ось Y' : 'Доп. ось Y'}</strong>
          {axis === 'x' && <label className="toggle"><input type="checkbox" checked={dates} onChange={e => edit(axis, { dates: e.target.checked, min: '', max: '', major: '', minor: '' })} /><span>Даты</span></label>}
          {input('min', dates ? 'с (дд.мм.гггг)' : 'минимум')}
          {input('max', dates ? 'по (дд.мм.гггг)' : 'максимум')}
          {dates && unit('majorUnit')}{input('major', dates ? 'осн. — кол-во' : 'основное')}
          {dates && unit('minorUnit')}{input('minor', dates ? 'доп. — кол-во' : 'дополнительное')}
        </div>
      )
    })}
  </div>
  )
}

/** Ручные границы и деления осей X, Y и дополнительной Y — отдельно по типам графиков. Состояние — в ``fmt_<модуль>_ui`` (черновик полей). */
/** Типы графиков для настроек оформления: обычные модули, а также пакет по фонду и ГГХ, если они включены (ГГХ — если есть данные). */
function styleRows(modules: string[], choices: ExportChoices): string[] {
  return [...modules.filter(m => choices.modules.some(x => x.id === m)), ...(modules.includes('pack') ? ['pack'] : []), ...(choices.ggh && modules.includes('ggh') ? ['ggh'] : [])]
}
function styleLabel(m: string, choices: ExportChoices): string {
  return m === 'ggh' ? 'ГГХ (Word)' : m === 'pack' ? 'Пакет по фонду' : choices.modules.find(x => x.id === m)?.label ?? m
}

function AxisSettings({ form, set, choices, modules }: FieldProps & { modules: string[] }) {
  const rows = styleRows(modules, choices)
  const label = (m: string) => styleLabel(m, choices)
  return (
    <details className="table-block">
      <summary className="block-head"><h3>Оси: границы и деления</h3></summary>
      <p className="muted pad">Для каждого типа графиков можно задать минимум, максимум, основное и дополнительное деление осей X, Y и дополнительной Y (справа).
        Пустое поле — автоматически. Сетка делений начинается с минимума. Для оси X с датами включите «Даты»: границы вводятся датами (дд.мм.гггг),
        деления — единицей (год, месяц, день) и количеством. Работает в предпросмотре, архиве, Word и пакете по фонду; сохраняется в шаблоне.</p>
      <div className="param-bar flat">
        {rows.map(m => {
          const f = 'fmt_' + m + '_axes', ui = f + '_ui'
          let spec: AxesSpec = {}
          try { spec = JSON.parse((form[ui] as string | undefined) || '{}') } catch { spec = {} }
          const edit = (axis: 'x' | 'y' | 'y2', patch: AxisSpec) => {
            const next = { ...spec, [axis]: { ...spec[axis], ...patch } }
            set(ui, JSON.stringify(next)); set(f, axesPayload(next))
          }
          return (
            <Section key={m} title={label(m)}>
              <AxesEditor spec={spec} onEdit={edit} />
            </Section>
          )
        })}
      </div>
    </details>
  )
}

/** Вкладка «Отдельные графики»: у одного графика из семейства свои цвета и наборы данных, пределы и деления осей (поле ``fmt_overrides``,
 *  черновик — ``fmt_overrides_ui``). Типовое оформление остаётся у остальных графиков. */
interface OwnFormat { series?: SeriesRule[]; axes?: AxesSpec }
function CustomCharts({ form, set, choices, projectId, loadPlan, planned }: FieldProps & { projectId: string; loadPlan: () => Promise<ExportPlan>; planned: string }) {
  const [charts, setCharts] = useState<{ name: string; module: string }[] | null>(null)
  const [name, setName] = useState('')
  const [names, setNames] = useState<string[]>([])
  const [image, setImage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const label = (m: string) => choices.modules.find(x => x.id === m)?.label ?? m
  let all: Record<string, OwnFormat> = {}
  try { all = JSON.parse((form.fmt_overrides_ui as string | undefined) || '{}') } catch { all = {} }
  const own = all[name] ?? {}
  const changed = Object.keys(all).filter(k => (all[k].series?.length ?? 0) > 0 || Object.keys(all[k].axes ?? {}).length > 0)
  const write = (next: Record<string, OwnFormat>) => {
    const payload: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(next)) {
      const series = (v.series ?? []).filter(r => r.match)
      const axes = v.axes ? axesPayload(v.axes) : ''
      if (series.length || axes) payload[k] = { ...(series.length ? { series } : {}), ...(axes ? { axes: JSON.parse(axes) } : {}) }
    }
    set('fmt_overrides_ui', JSON.stringify(next)); set('fmt_overrides', Object.keys(payload).length ? JSON.stringify(payload) : '')
  }
  const update = (patch: OwnFormat) => write({ ...all, [name]: { ...own, ...patch } })
  const reset = (k: string) => { const { [k]: _gone, ...rest } = all; write(rest) }
  useEffect(() => {
    let alive = true
    setError(null)
    loadPlan().then(p => {
      if (!alive) return
      const list = p.charts.filter(c => !EXTRAS.includes(c.module))
      setCharts(list); setName(old => list.some(c => c.name === old) ? old : (list[0]?.name ?? ''))
    }).catch(e => alive && setError((e as Error).message))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planned, projectId])
  useEffect(() => {      // названия наборов данных выбранного графика — для списка правил
    if (!name) { setNames([]); return }
    let alive = true
    exportApi.series(projectId, form, name).then(r => alive && setNames(r.chart)).catch(() => undefined)
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, projectId])
  const fmtKey = JSON.stringify(Object.entries(form).filter(([k]) => k.startsWith('fmt_') && !k.endsWith('_ui') || k.startsWith('label_') || k === 'look' || k === 'font' || k === 'font_size'))
  useEffect(() => {      // картинка графика с учётом его настроек
    if (!name || !charts?.some(c => c.name === name)) return
    let alive = true
    const timer = setTimeout(() => {
      exportApi.preview(projectId, form, name).then(u => { if (alive) { setError(null); setImage(old => { if (old) URL.revokeObjectURL(old); return u }) } else URL.revokeObjectURL(u) })
        .catch(e => alive && setError((e as Error).message))
    }, 400)
    return () => { alive = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, charts, fmtKey])
  const groups = Array.from(new Set((charts ?? []).map(c => c.module)))
  return (
    <div className="param-bar">
      <p className="muted pad">Выберите график из семейства и поменяйте у него цвета наборов данных или пределы и деления осей: у остальных графиков останется общее оформление
        (вкладки модулей и блоки ниже). «Сбросить» возвращает график к общему оформлению. Работает в предпросмотре, архиве и Word; сохраняется в шаблоне.</p>
      {error && <p className="error">{error}</p>}
      {charts && !charts.length && <p className="muted pad">Нет графиков: включите на вкладках модулей нужные и выберите скважины.</p>}
      {!charts && !error && <p className="muted pad">Загрузка перечня графиков…</p>}
      {!!charts?.length && <>
        <Section title="График">
          <label className="field wide">
            <span className="field-label">График</span>
            <select value={name} onChange={e => setName(e.target.value)}>
              {groups.map(g => (
                <optgroup key={g} label={label(g)}>
                  {charts.filter(c => c.module === g).map(c => <option key={c.name} value={c.name}>{c.name}{changed.includes(c.name) ? ' ●' : ''}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <button type="button" disabled={!changed.includes(name)} onClick={() => reset(name)}>Сбросить этот график к общему оформлению</button>
          {!!changed.length && <p className="muted">Графиков со своими настройками: {changed.length}. <button type="button" onClick={() => write({})}>Сбросить все</button></p>}
        </Section>
        <Section title="Наборы данных">
          <div className="field wide">
            <RulesEditor rules={own.series ?? []} names={names} save={next => update({ series: next })} />
          </div>
        </Section>
        <Section title="Оси">
          <AxesEditor spec={own.axes ?? {}} onEdit={(axis, patch) => update({ axes: { ...own.axes, [axis]: { ...own.axes?.[axis], ...patch } } })} />
        </Section>
        {image && <div className="field wide"><img src={image} alt={name} style={{ maxWidth: '100%' }} /></div>}
      </>}
    </div>
  )
}

/** Правила наборов данных: набор из списка, цвет, линия, маркер, «скрыть». */
function RulesEditor({ rules, names, save }: { rules: SeriesRule[]; names: string[]; save: (next: SeriesRule[]) => void }) {
  const edit = (i: number, patch: Partial<SeriesRule>) => save(rules.map((r, j) => j === i ? { ...r, ...patch } : r))
  return (
    <>
                {rules.map((r, i) => (
                  <div key={i} className="series-rule">
                    <select value={r.match} aria-label="Набор данных" onChange={e => edit(i, { match: e.target.value })}>
                      <option value="">— набор данных —</option>
                      {[...(names), ...(r.match && !(names).includes(r.match) ? [r.match] : [])].map(n => <option key={n} value={n}>{n}</option>)}
                    </select>
                    <input type="color" value={r.color || '#2563eb'} aria-label="Цвет" onChange={e => edit(i, { color: e.target.value })} />
                    <button type="button" title="Цвет как в графике" onClick={() => edit(i, { color: '' })} disabled={!r.color}>цвет ✕</button>
                    <input value={r.width ?? ''} placeholder="линия, пт" aria-label="Толщина линии, пт (0 — без линии, только маркеры)" title="0 — линии отключены, остаются только маркеры" size={8} inputMode="decimal"
                      onChange={e => edit(i, { width: e.target.value })} />
                    <input value={r.marker ?? ''} placeholder="маркер, пт" aria-label="Размер маркеров, пт (0 — без маркеров)" size={8} inputMode="decimal"
                      onChange={e => edit(i, { marker: e.target.value })} />
                    <label className="toggle"><input type="checkbox" checked={!!r.hide} onChange={e => edit(i, { hide: e.target.checked })} /><span>скрыть</span></label>
                    <button type="button" aria-label="Удалить правило" onClick={() => save(rules.filter((_, j) => j !== i))}>✕</button>
                  </div>
                ))}
                <button type="button" disabled={rules.length >= 50} onClick={() => save([...rules, { match: '' }])}>+ набор данных</button>
    </>
  )
}

/** Толщина линии, размер маркеров, цвет и скрытие для каждого набора данных (кривой) — отдельно по типам графиков. */
function ChartFormat({ form, set, choices, modules, projectId, ready }: FieldProps & { modules: string[]; projectId: string; ready: boolean }) {
  const [names, setNames] = useState<Record<string, string[]>>({})
  const [open, setOpen] = useState(false)
  const rows = styleRows(modules, choices)
  const label = (m: string) => styleLabel(m, choices)
  useEffect(() => {      // подсказки: названия наборов данных в первых графиках каждого типа
    if (!open) return
    let alive = true
    exportApi.series(projectId, form).then(r => alive && setNames(r.series)).catch(() => undefined)
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ready, JSON.stringify(form.modules), projectId])
  return (
    <details className="table-block" onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="block-head"><h3>Наборы данных: линии, маркеры и цвета</h3></summary>
      <p className="muted pad">Для каждого типа графиков можно настроить отдельные кривые: выберите набор данных из списка (названия считываются из графиков),
        затем цвет, толщину линии (0 — без линии, остаются только маркеры), размер маркеров в пунктах (0 — без маркеров) или «скрыть». Пустое поле — как в графике.
        Правило действует на все кривые, в названии которых есть эта часть. Работает в предпросмотре, архиве, Word, пакете по фонду и ГГХ; сохраняется в шаблоне.</p>
      <div className="param-bar flat">
        {rows.map(m => {
          const f = 'fmt_' + m + '_series'
          let rules: SeriesRule[] = []
          try { rules = JSON.parse((form[f] as string | undefined) || '[]') } catch { rules = [] }
          const save = (next: SeriesRule[]) => set(f, next.length ? JSON.stringify(next) : '')
          return (
            <Section key={m} title={label(m)}>
              <div className="field wide">
                <RulesEditor rules={rules} names={names[m === 'pack' ? 'production' : m] ?? []} save={save} />
              </div>
            </Section>
          )
        })}
      </div>
    </details>
  )
}

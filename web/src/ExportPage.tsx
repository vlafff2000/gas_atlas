// Раздел «Экспорт» (5.8: app/ui/export_panel.py). Поля формы называются как виджеты 5.8 — шаблоны общие.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { MultiSelect } from './MultiSelect'
import { ChartView } from './ChartView'
import { api, type Chart } from './api'
import { exportApi, projectsApi, saveLink, type ExportChoices, type ExportPlan, type ExportResult, type Form } from './api_projects'
import { Toast, type PageProps } from './ProjectPage'
import { ResizableFrame, HEIGHT_MM, WIDTH_MM } from './ResizableFrame'

type Opt = [unknown, string]
const SPLIT: Opt[] = [['well', 'По скважинам'], ['group', 'По группам (отдельные кривые)'], ['subgroup', 'По подгруппам'], ['all', 'Все выбранные вместе']]
const DIRECTION: Opt[] = [['number', 'По номеру'], ['desc', 'Больший дебит слева'], ['asc', 'Больший дебит справа']]
const ORIENTATION: Opt[] = [['standard', 'X = Q, Y = ΔP²'], ['swapped', 'X = ΔP², Y = Q']]
// Популярные форматы: ширина × высота, мм. Без высоты — подбирается по ширине и легенде.
const SIZES: [string, string, number | null][] = [
  ['auto', 'Авто (220 мм по ширине)', null],
  ['a4-width', 'A4: ширина поля 170 × 110', 110],
  ['a4-half', 'A4: пол-листа 170 × 125', 125],
  ['a4-page', 'A4 книжный: весь лист 190 × 270', 270],
  ['a4-land', 'A4 альбомный 270 × 180', 180],
  ['16x9', 'Слайд 16:9, 254 × 143', 143],
  ['4x3', 'Слайд 4:3, 240 × 180', 180],
  ['column', 'Колонка статьи 85 × 65', 65],
  ['square', 'Квадрат 150 × 150', 150],
]
const SIZE_WIDTH: Record<string, number> = { auto: 220, 'a4-width': 170, 'a4-half': 170, 'a4-page': 190, 'a4-land': 270, '16x9': 254, '4x3': 240, column: 85, square: 150 }
const KINDS = [['withdrawal', 'Отбор'], ['injection', 'Закачка']] as const

/** Без локального хранилища черновика: форма живёт, пока открыт раздел; для повтора — шаблоны. */
export function ExportPage({ project, onProject }: PageProps) {
  const [form, setForm] = useState<Form>({})
  const [choices, setChoices] = useState<ExportChoices | null>(null)
  const [tab, setTab] = useState<string | null>(null)
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
  const modules = (form.modules as string[] | undefined) ?? choices?.default_modules ?? []
  const key = JSON.stringify([project.revision, form])
  // Перечень графиков от размера не зависит: растягивание в предпросмотре не должно его сбрасывать.
  const planned = useMemo(() => { const { width: _w, height: _h, ...rest } = form; return JSON.stringify([project.revision, rest]) }, [form, project.revision])
  const ready = modules.length > 0

  const prepare = async () => {
    if (planKey === planned && plan) return plan
    const next = await exportApi.plan(project.id, form)
    setPlan(next); setPlanKey(planned)
    return next
  }
  const run = async (label: string, work: () => Promise<void>) => {
    setBusy(label); setError(null)
    try { await work() } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }
  const preview = () => run('preview', async () => { await prepare(); setShowPreview(true) })
  const makeArchive = () => run('archive', async () => {
    await prepare()
    setArchive({ key, result: await exportApi.archive(project.id, form) })
  })
  const makeWord = () => run('word', async () => {
    await prepare()
    setWord({ key, result: await exportApi.word(project.id, form) })
  })

  const packNoSeasons = KINDS.some(([k]) => ((form.pack_kinds as string[] | undefined) ?? ['withdrawal', 'injection']).includes(k)
    && Array.isArray(form[`pack_periods_${k}`]) && (form[`pack_periods_${k}`] as string[]).length === 0)

  const makePack = () => run('pack', async () => {
    setPack({ key, result: await exportApi.pack(project.id, form) })
  })

  // Автоматическое обновление предпросмотра (как флажок 5.8).
  useEffect(() => {
    if (!form.auto || !ready) return
    const timer = setTimeout(() => { exportApi.plan(project.id, form).then(p => { setPlan(p); setPlanKey(planned); setShowPreview(true) }).catch(() => undefined) }, 400)
    return () => clearTimeout(timer)
  }, [form, key, planned, project.id, ready])

  // Картинка выбранного графика (макет файла, 150 DPI при выбранной ширине).
  const shownPlan = plan && planKey === planned ? plan : null
  useEffect(() => {
    if (!shownPlan || !showPreview || live || !shownPlan.charts.length) return
    const name = shownPlan.charts.some(c => c.name === chart) ? chart : shownPlan.charts[0].name
    if (name !== chart) { setChart(name); return }
    let alive = true
    exportApi.preview(project.id, form, name).then(u => { if (alive) setImage(old => { if (old) URL.revokeObjectURL(old); return u }); else URL.revokeObjectURL(u) })
      .catch(e => alive && setError('Не удалось отобразить этот график: ' + (e as Error).message))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownPlan, showPreview, chart, live, form.width, form.height])

  // Открытый предпросмотр обновляется сам, когда меняется проект (исключили точку).
  useEffect(() => {
    if (!showPreview || !ready || !plan || planKey === key) return
    let alive = true
    exportApi.plan(project.id, form).then(p => { if (alive) { setPlan(p); setPlanKey(planned) } }).catch(() => undefined)
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.revision])

  // Интерактивный вид того же графика; после исключения точки меняется ревизия проекта и график строится заново.
  useEffect(() => {
    if (!shownPlan || !showPreview || !live || !shownPlan.charts.length) return
    const name = shownPlan.charts.some(c => c.name === chart) ? chart : shownPlan.charts[0].name
    if (name !== chart) { setChart(name); return }
    let alive = true
    setLiveChart(null)
    exportApi.chart(project.id, form, name).then(c => alive && setLiveChart(c))
      .catch(e => alive && setError('Не удалось отобразить этот график: ' + (e as Error).message))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownPlan, showPreview, chart, live])

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

  const ready_files = [...(pack?.key === key ? pack.result.files : []), ...(word?.key === key ? word.result.files : []), ...(archive?.key === key ? archive.result.files : [])]
  const bundle = () => run('bundle', async () => {
    const { file } = await exportApi.bundle(project.id, ready_files)
    saveLink(projectsApi.exportUrl(project.id, file))
  })

  if (!choices) {
    return (
      <>
        <Title />
        {error ? <div className="note warning" role="alert">{error}</div> : <p className="muted loading-line">Загрузка…</p>}
      </>
    )
  }
  if (!choices.modules.length) {
    return <><Title /><div className="note info">В проекте нет данных для выгрузки. Загрузите данные в разделе «Импорт данных».</div></>
  }

  const current = tab && choices.modules.some(m => m.id === tab) ? tab : choices.modules[0].id
  const F = { form, set, choices }
  const formats = (form.formats as string[] | undefined) ?? ['svg', 'pdf']
  const style = choices.style

  return (
    <>
      <Title />

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
              {['svg', 'pdf', 'png'].map(f => (
                <label key={f}><input type="checkbox" checked={formats.includes(f)}
                  onChange={e => set('formats', ['svg', 'pdf', 'png'].filter(x => x === f ? e.target.checked : formats.includes(x)))} />{f.toUpperCase()}</label>
              ))}
            </span>
          </div>
          <Select {...F} field="dpi" label="Разрешение PNG" def={300} options={[[300, '300'], [600, '600'], [1200, '1200']]} />
          <SizePick {...F} />
          <Select {...F} field="font" label="Шрифт" def="default"
            options={[['default', 'Стандартный (DejaVu Sans)'], ['times', 'Times New Roman'], ['arial_narrow', 'Arial Narrow']]} />
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

      <div className="tabs" role="tablist">
        {choices.modules.map(m => (
          <button key={m.id} type="button" role="tab" aria-selected={m.id === current} onClick={() => setTab(m.id)}
            className={modules.includes(m.id) ? 'on' : undefined}>{m.label}</button>
        ))}
      </div>
      <div className="param-bar">
        <ModuleTab key={current} module={current} label={choices.modules.find(m => m.id === current)!.label}
          enabled={modules.includes(current)} adoptPanels={adoptPanels} {...F}
          onEnable={on => set('modules', choices.modules.map(m => m.id).filter(m => m === current ? on : modules.includes(m)))} />
      </div>

      <details className="table-block">
        <summary className="block-head"><h3>Word: подписи под графиками</h3></summary>
        <p className="muted pad">Таблица в две колонки. Доступные поля: {'{раздел}, {номер}, {скважина}, {горизонт}, {период}, {модуль}'}.
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

      {choices.modules.some(m => m.id === 'production') && (
        <details className="block" open>
          <summary className="block-head"><h3>Пакет графиков по фонду (приложения к отчету)</h3></summary>
          <p className="muted pad">Одним нажатием: график «Производительность» каждой скважины фонда по выбранным сезонам, по 2, 4 или 6 на лист A4,
            отдельный файл на отбор и на закачку. Графики легкие: палитровый PNG 200 DPI, легенда в одну строку под осями. Поля подписи: {'{раздел}, {номер}, {скважина}, {режим}, {годы}'}.</p>
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
              {([['docx', 'Word'], ['pdf', 'PDF']] as const).map(([k, l]) => {
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
          <div className="toolbar">
            <button type="button" className="primary" disabled={busy !== null || packNoSeasons} onClick={makePack}>Создать пакет по всем скважинам</button>
            {packNoSeasons && <span className="muted">Выберите хотя бы один сезон.</span>}
          </div>
        </details>
      )}

      <div className="toolbar">
        <Check {...F} field="auto" label="Автоматически обновлять предпросмотр" def={false} />
        <span className="spacer" />
        {busy && <span className="pulse">{{ preview: 'Подготовка перечня графиков и расчетных таблиц…', archive: 'Создание архива…', word: 'Создание Word-отчета…', pack: 'Построение графиков всех скважин, это может занять несколько минут…', bundle: 'Объединение созданных файлов…' }[busy] ?? 'Выполняется…'}</span>}
        <button type="button" className="quiet" disabled={!ready || busy !== null} onClick={preview}>Предпросмотр</button>
        <button type="button" className="primary" disabled={!ready || busy !== null} onClick={makeArchive}>Сформировать архив</button>
        <button type="button" className="quiet" disabled={!ready || busy !== null} onClick={makeWord}>Создать отчет Word</button>
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
                <label className="inline-field">Вид
                  <select value={live ? 'live' : 'image'} onChange={e => { setLive(e.target.value === 'live'); setExcludeMode(false) }}>
                    <option value="image">Картинка (макет файла)</option>
                    <option value="live">Интерактивный график</option>
                  </select>
                </label>
                {live && exclusions && (
                  <label className="toggle"><input type="checkbox" checked={excludeMode} onChange={e => setExcludeMode(e.target.checked)} /><span>Исключать точки кликом</span></label>
                )}
              </div>
              {live ? (
                <>
                  <p className="muted small-text">Интерактивный вид того же графика: масштаб, подсказки{exclusions ? ' и исключение точек кликом (исключения сохраняются в проекте и попадут в выгрузку)' : ''}.
                    {!exclusions && ' Исключения проекта в этой выгрузке отключены, поэтому точки не выбираются.'}</p>
                  {excludeMode && <div className="note info">Щелкните по измеренной точке, чтобы исключить ее. Расчетные кривые и серые исключенные точки не выбираются.</div>}
                  {liveChart
                    ? <ChartView key={liveChart.id + chart} chart={liveChart} excludeMode={excludeMode && exclusions} onExclude={excludePoint}
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

      {pack?.key === key && <Outcome title="Пакет графиков по фонду" result={pack.result} pid={project.id} pack />}
      {word?.key === key && <Outcome title="Отчет Word" result={word.result} pid={project.id} word />}
      {archive?.key === key && <Outcome title="Архив результатов" result={archive.result} pid={project.id} />}
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

/** Формат листа: готовые размеры, ширина и высота в мм (пустая высота — подбирается автоматически). */
function SizePick({ form, set, choices }: FieldProps) {
  const width = (form.width as number | undefined) ?? 220
  const height = form.height as number | undefined
  const preset = SIZES.find(([id, , h]) => (h ?? undefined) === height && SIZE_WIDTH[id] === width)?.[0] ?? 'custom'
  const [text, setText] = useState(height === undefined ? '' : String(height))
  useEffect(() => setText(height === undefined ? '' : String(height)), [height])
  const n = Number(text)
  const bad = text.trim() !== '' && !(n >= HEIGHT_MM[0] && n <= HEIGHT_MM[1])
  return (
    <>
      <label className="field">
        <span className="field-label">Формат графика</span>
        <select value={preset} onChange={e => {
          const [, , h] = SIZES.find(([id]) => id === e.target.value) ?? ['', '', null]
          if (e.target.value === 'custom') return
          set('width', SIZE_WIDTH[e.target.value])
          set('height', h ?? undefined)
        }}>
          {SIZES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          <option value="custom">Свой размер</option>
        </select>
      </label>
      <Num form={form} set={set} choices={choices} field="width" label="Ширина, мм" def={220} min={WIDTH_MM[0]} max={WIDTH_MM[1]} />
      <label className={'field number' + (bad ? ' invalid' : '')} title="Пусто — высота подбирается по ширине и легенде">
        <span className="field-label">Высота, мм</span>
        <input type="number" min={HEIGHT_MM[0]} max={HEIGHT_MM[1]} placeholder="авто" value={text}
          onChange={e => { setText(e.target.value); const v = Number(e.target.value)
            if (e.target.value.trim() === '') set('height', undefined)
            else if (v >= HEIGHT_MM[0] && v <= HEIGHT_MM[1]) set('height', v) }} />
        {bad && <span className="field-error">от {HEIGHT_MM[0]} до {HEIGHT_MM[1]}</span>}
      </label>
    </>
  )
}

function Title() {
  return (
    <header className="module-title">
      <div>
        <h1>Экспорт результатов</h1>
        <p className="lede">Параметры выгрузки, предпросмотр каждой диаграммы, архивы и отчет Word.</p>
      </div>
    </header>
  )
}

function Outcome({ title, result, pid, word, pack }: { title: string; result: ExportResult; pid: string; word?: boolean; pack?: boolean }) {
  const partial = result.errors.length > 0
  return (
    <section className="table-block">
      <div className="block-head"><h3>{title}</h3></div>
      <div className={'note ' + (partial ? 'warning' : 'info') + ' pad-x'}>
        {pack
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
        {result.files.map(f => <li key={f}><a href={projectsApi.exportUrl(pid, f)} download>{f}</a></li>)}
        {result.files.length === 0 && <li className="muted">Нет готовых файлов.</li>}
      </ul>
    </section>
  )
}

// ---------- поля формы ----------

interface FieldProps { form: Form; set: (field: string, value: unknown) => void; choices: ExportChoices }

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="param-section" aria-label={title}>
      <span className="param-title" aria-hidden="true">{title}</span>
      <div className="param-fields">{children}</div>
    </fieldset>
  )
}

function Check({ form, set, field, label, def, disabled }: FieldProps & { field: string; label: string; def: boolean; disabled?: boolean }) {
  const value = (form[field] as boolean | undefined) ?? def
  return (
    <label className="toggle">
      <input type="checkbox" checked={value} disabled={disabled} onChange={e => set(field, e.target.checked)} />
      <span>{label}</span>
    </label>
  )
}

function Select({ form, set, field, label, def, options }: FieldProps & { field: string; label: string; def: unknown; options: Opt[] }) {
  const value = form[field] === undefined ? def : form[field]
  const index = Math.max(0, options.findIndex(([v]) => JSON.stringify(v) === JSON.stringify(value)))
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select value={index} onChange={e => set(field, options[Number(e.target.value)][0])}>
        {options.map(([, l], i) => <option key={i} value={i}>{l}</option>)}
      </select>
    </label>
  )
}

function Num({ form, set, field, label, def, min, max, step = 1 }:
  FieldProps & { field: string; label: string; def: number; min: number; max: number; step?: number }) {
  const value = (form[field] as number | undefined) ?? def
  const [text, setText] = useState(String(value))
  useEffect(() => setText(String(value)), [value])
  const n = Number(text)
  const ok = text.trim() !== '' && n >= min && n <= max
  return (
    <label className={'field number' + (ok ? '' : ' invalid')}>
      <span className="field-label">{label}</span>
      <input type="number" min={min} max={max} step={step} value={text}
        onChange={e => { setText(e.target.value); const v = Number(e.target.value); if (e.target.value.trim() !== '' && v >= min && v <= max) set(field, v) }} />
      {!ok && <span className="field-error">от {min} до {max}</span>}
    </label>
  )
}

function Text({ form, set, field, label, def, wide }: FieldProps & { field: string; label: string; def: string; wide?: boolean }) {
  return (
    <label className={'field' + (wide ? ' wide' : '')}>
      <span className="field-label">{label}</span>
      <input value={(form[field] as string | undefined) ?? def} maxLength={500} onChange={e => set(field, e.target.value)} />
    </label>
  )
}

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

  const groups = choices.groups[module] ?? []
  const prefix = module === 'well_dashboard' ? 'dashboard' : module
  const chosenGroups = ((form[module + '_groups'] as string[] | undefined) ?? groups).filter(g => groups.includes(g))
  const wells = (choices.wells[module] ?? []).filter(w => chosenGroups.includes(choices.mapping[w] ?? 'Без группы'))
  const selection = (
    <Section title="Скважины">
      <Multi {...F} field={module + '_groups'} label={label + ': группы'} options={groups} />
      <Multi {...F} field={prefix + '_wells'} label={label + ': скважины'} options={wells} prefix="№ " />
    </Section>
  )
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
            <span>Экспортировать обе панели · {label}</span>
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
  return <>{head}{selection}{body}</>
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

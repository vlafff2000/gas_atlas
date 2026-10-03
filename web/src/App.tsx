import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, defaults, type ModuleSpec, type Params, type Project, type Result, type SavedState } from './api'
import { ChartView } from './ChartView'
import { CommandBar } from './CommandBar'
import { ParamBar } from './ParamBar'
import { PassportPage } from './PassportPage'
import { TableView } from './TableView'
import { formatDate } from './format'
import { inMenu, PROJECT_PAGES } from './api_projects'
import { ProjectPages, RestoreBox } from './ProjectPage'
import { ImportPage } from './ImportPage'

const remembered = {
  get: <T,>(key: string, fallback: T): T => {
    try { const v = localStorage.getItem('atlas:' + key); return v === null ? fallback : JSON.parse(v) } catch { return fallback }
  },
  has: (key: string) => { try { return localStorage.getItem('atlas:' + key) !== null } catch { return false } },
  set: (key: string, value: unknown) => { try { localStorage.setItem('atlas:' + key, JSON.stringify(value)) } catch { /* без памяти */ } },
}

type Status = { kind: 'idle' } | { kind: 'running' } | { kind: 'error'; message: string; missing: boolean } | { kind: 'done' }

export function App() {
  const [modules, setModules] = useState<ModuleSpec[] | null>(null)
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)
  const [projectId, setProjectId] = useState<string | null>(remembered.get('project', null))
  const [moduleId, setModuleId] = useState<string | null>(location.hash.slice(2) || remembered.get('module', null))

  const loadProjects = useCallback(() => api.projects().then(setProjects), [])
  useEffect(() => {
    Promise.all([api.modules().then(setModules), loadProjects()]).catch(e => setFatal((e as Error).message))
  }, [loadProjects])

  const project = projects?.find(p => p.id === projectId) ?? projects?.[0] ?? null
  const spec = modules?.find(m => m.id === moduleId) ?? modules?.[0] ?? null
  const page = moduleId?.startsWith('@') ? moduleId : null      // служебные страницы: «Импорт», «Экспорт», «Проекты», «Настройки», «Паспорт»
  const updateProject = useCallback((next: Project) =>
    setProjects(list => list?.map(p => (p.id === next.id ? next : p)) ?? list), [])

  useEffect(() => { if (project) remembered.set('project', project.id) }, [project])
  useEffect(() => {
    if (!spec || page) return
    remembered.set('module', spec.id)
    if (location.hash !== '#/' + spec.id) history.replaceState(null, '', '#/' + spec.id)
  }, [spec, page])
  useEffect(() => {
    const onHash = () => setModuleId(location.hash.slice(2))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const groups = useMemo(() => {
    const out = new Map<string, ModuleSpec[]>()
    for (const m of modules ?? []) out.set(m.group, [...(out.get(m.group) ?? []), m])
    return [...out.entries()]
  }, [modules])

  const openProject = (id: string) => { loadProjects().then(() => setProjectId(id)) }
  const createDemo = async () => {
    const { id } = await api.createDemo()
    await loadProjects()
    setProjectId(id)
  }

  if (fatal) return <div className="fatal"><h1>Газовый атлас</h1><p>{fatal}</p></div>

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span>Газовый атлас</span>
        </div>
        <label className="project-picker">
          <span>Объект</span>
          <select value={project?.id ?? ''} disabled={!projects?.length} onChange={e => setProjectId(e.target.value)}>
            {!projects?.length && <option value="">нет проектов</option>}
            {projects?.map(p => <option key={p.id} value={p.id}>{p.name}{p.demo ? ' (демо)' : ''}</option>)}
          </select>
        </label>
        <nav aria-label="Разделы">
          <section><h2>Данные</h2><ul><li><a href="#/@import" aria-current={page === '@import' ? 'page' : undefined}>Импорт данных</a></li></ul></section>
          {groups.filter(([, items]) => items.some(m => inMenu(m.id, project))).map(([group, items]) => (
            <section key={group}>
              <h2>{group}</h2>
              <ul>
                {items.filter(m => inMenu(m.id, project)).map(m => {
                  const missing = project ? m.needs.filter(n => !project.tables[n]) : []
                  return (
                    <li key={m.id}>
                      <a href={'#/' + m.id} aria-current={!page && m.id === spec?.id ? 'page' : undefined}
                         className={missing.length ? 'no-data' : undefined}
                         title={missing.length ? 'В проекте нет нужных данных' : m.description}>
                        {m.title}
                      </a>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
          {project && (
            <section>
              <h2>Документы и настройки</h2>
              <ul>{PROJECT_PAGES.filter(p => inMenu(p.id, project)).map(p => (
                <li key={p.id}><a href={'#/' + p.id} aria-current={page === p.id ? 'page' : undefined}>{p.title}</a></li>
              ))}</ul>
            </section>
          )}
        </nav>
      </aside>

      <main className="workspace">
        {page === '@import' ? (
          <ImportPage project={project} onProject={updateProject}
                      onCreated={async id => { await loadProjects(); setProjectId(id) }} />
        ) : projects && projects.length === 0 ? (
          <Empty onDemo={createDemo} onOpen={openProject} />
        ) : page === '@passport' && project ? (
          <PassportPage key={project.id} project={project} onProject={updateProject} />
        ) : page && project && projects ? (
          <ProjectPages page={page} project={project} projects={projects} onProject={updateProject} onOpen={openProject} />
        ) : spec && project ? (
          <ModuleView key={spec.id + project.id} spec={spec} project={project} onProject={updateProject} />
        ) : (
          <p className="muted loading-line">Загрузка…</p>
        )}
      </main>
    </div>
  )
}

function Empty({ onDemo, onOpen }: { onDemo: () => void; onOpen: (id: string) => void }) {
  return (
    <div className="empty">
      <h1>Проектов пока нет</h1>
      <p>Создайте проект и загрузите свои файлы в разделе <a href="#/@import">«Импорт данных»</a>. Проекты общие с версией 5.8.</p>
      <p>Чтобы посмотреть, как работает новый интерфейс, откройте демонстрационный объект с синтетическими данными.</p>
      <button type="button" className="primary" onClick={onDemo}>Открыть демонстрационный объект</button>
      <RestoreBox onOpen={onOpen} />
    </div>
  )
}

/** Значения общих настроек проекта (Param.setting) поверх параметров. */
function withSettings(spec: ModuleSpec, params: Params, project: Project): Params {
  const out = { ...params }
  for (const p of spec.params) if (p.setting && project.settings[p.setting] != null) out[p.name] = project.settings[p.setting]
  return out
}

const PAGE_SIZES = [1, 2, 4, 6, 10, 20]

function ModuleView({ spec, project, onProject }: { spec: ModuleSpec; project: Project; onProject: (p: Project) => void }) {
  const [two, setTwo] = useState<boolean>(spec.panels > 1 && remembered.get(`two:${spec.id}`, false))
  const toggleTwo = (on: boolean) => { setTwo(on); remembered.set(`two:${spec.id}`, on) }
  return (
    <>
      <header className="module-title">
        <div>
          <h1>{spec.title}</h1>
          {spec.description && <p className="lede">{spec.description}</p>}
        </div>
        {spec.panels > 1 && (
          <label className="toggle" title="Две независимые панели с собственными фильтрами рядом">
            <input type="checkbox" checked={two} onChange={e => toggleTwo(e.target.checked)} />
            <span>Две независимые панели</span>
          </label>
        )}
      </header>
      <div className={'panels' + (two ? ' two' : '')}>
        {Array.from({ length: two ? 2 : 1 }, (_, i) => (
          <ModulePanel key={i} panel={i} labelled={two} spec={spec} project={project} onProject={onProject} />
        ))}
      </div>
    </>
  )
}

function ModulePanel({ spec, project, onProject, panel, labelled }:
  { spec: ModuleSpec; project: Project; onProject: (p: Project) => void; panel: number; labelled: boolean }) {
  const storeKey = `params:${project.id}:${spec.id}` + (panel ? `:${panel}` : '')
  const [params, setParams] = useState<Params | null>(null)
  const [saved, setSaved] = useState<SavedState | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [excludeMode, setExcludeMode] = useState(false)
  const [toast, setToast] = useState<{ text: string; undo: boolean } | null>(null)
  const [pageSize, setPageSize] = useState<number>(remembered.get('chartPage', 6))
  const [page, setPage] = useState(1)
  const [resets, setResets] = useState(0)
  const controller = useRef<AbortController | null>(null)
  const hasAuto = spec.params.some(p => p.auto)

  // Начальные параметры: последние в 6 → сохранённый вид проекта (общий с 5.8) → умолчания.
  useEffect(() => {
    let alive = true
    api.savedState(project.id, spec.id, panel).catch(() => ({ panel: null, history: [] }) as SavedState).then(state => {
      if (!alive) return
      setSaved(state)
      const base = { ...defaults(spec), ...(state.panel ?? {}) }
      const local = remembered.has(storeKey) ? remembered.get<Params>(storeKey, {}) : {}
      setParams(withSettings(spec, { ...base, ...local }, project))
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, project.id, storeKey])

  const run = useCallback((values: Params) => {
    controller.current?.abort()
    const ctrl = new AbortController(); controller.current = ctrl
    setStatus({ kind: 'running' })
    api.run(spec.id, project.id, values, ctrl.signal)
      .then(r => { setResult(r); setStatus({ kind: 'done' }) })
      .catch(e => {
        if ((e as Error).name === 'AbortError') return
        const err = e as ApiError
        if (err.status === 400) remembered.set(storeKey, {})     // сохранённые параметры устарели
        setStatus({ kind: 'error', message: err.message, missing: err.status === 409 })
        if (err.status === 409) setResult(null)
      })
  }, [spec.id, project.id, storeKey])

  // Пересчёт при изменении параметров или ревизии проекта (исключения, настройки — в т. ч. из 5.8).
  useEffect(() => {
    if (!params) return
    remembered.set(storeKey, Object.fromEntries(Object.entries(params).filter(([k]) => !spec.params.find(p => p.name === k)?.setting)))
    if (!spec.auto_run) return
    const timer = setTimeout(() => run(params), 200)
    return () => clearTimeout(timer)
  }, [params, project.revision, spec, run, storeKey])
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => { setPage(1) }, [params])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 9000)
    return () => clearTimeout(timer)
  }, [toast])

  const refreshProject = useCallback(() => api.project(project.id).then(onProject), [project.id, onProject])

  const changeParams = async (next: Params) => {
    for (const p of spec.params) {
      if (p.setting && next[p.name] !== params?.[p.name]) {
        try { onProject(await api.saveSettings(project.id, { [p.setting]: next[p.name] })) }
        catch (e) { setToast({ text: (e as Error).message, undo: false }); return }
      }
    }
    setParams(next)
  }

  const exclusionDone = async (text: string, undo = true) => {
    setToast({ text, undo })
    await refreshProject()          // новая ревизия → пересчёт
  }
  const excludePoint = async (dataset: string, id: string) => {
    try {
      const r = await api.exclude(project.id, dataset, [id], [], 'Исключено кликом на графике')
      if (r.added) await exclusionDone(`Точка исключена. Всего исключено: ${r.excluded}.`)
    } catch (e) { setToast({ text: (e as Error).message, undo: false }) }
  }
  const applyTable = (dataset: string) => async (add: string[], remove: string[], reason: string) => {
    const r = await api.exclude(project.id, dataset, add, remove, reason)
    await exclusionDone(`Фильтр сохранен: исключено ${r.added}, возвращено ${r.removed}. Кривые и таблицы пересчитаны.`)
  }
  const undo = async () => {
    try {
      const r = await api.undo(project.id)
      await exclusionDone(r.removed ? `Возвращено точек: ${r.removed}.` : 'Отменять нечего.', false)
    } catch (e) { setToast({ text: (e as Error).message, undo: false }) }
  }
  const saveView = async () => {
    if (!params) return
    try {
      onProject(await api.saveState(project.id, spec.id, params, panel))
      setSaved(await api.savedState(project.id, spec.id, panel))
      setToast({ text: 'Сохранено в проекте; параметры будут открываться по умолчанию.', undo: false })
    } catch (e) { setToast({ text: (e as Error).message, undo: false }) }
  }
  const reset = () => { changeParams(withSettings(spec, defaults(spec), project)); setResets(n => n + 1) }

  if (!params) return <p className="muted loading-line">Загрузка…</p>

  const changed = hasAuto || JSON.stringify(params) !== JSON.stringify(withSettings(spec, defaults(spec), project))
  const selectable = !!result?.charts.some(c => c.series.some(s => s.ids))
  const pages = Math.max(1, Math.ceil((result?.charts.length ?? 0) / pageSize))
  const shown = result?.charts.slice((Math.min(page, pages) - 1) * pageSize, Math.min(page, pages) * pageSize) ?? []

  return (
    <section className="panel">
      <div className="panel-head">
        {labelled && <strong>Панель {panel + 1}</strong>}
        <span className="spacer" />
        {status.kind === 'running' && <span className="pulse">Считаю…</span>}
        {status.kind === 'done' && result && <span className="muted">Расчет {Math.round(result.elapsed_ms)} мс</span>}
        {changed && <button type="button" className="quiet" onClick={reset}>Сбросить параметры</button>}
        {!spec.auto_run && <button type="button" className="primary" onClick={() => run(params)}>Рассчитать</button>}
      </div>

      <ParamBar key={resets} spec={spec} project={project.id} panel={panel} values={params} onChange={changeParams} />

      <div className="toolbar">
        {selectable && (
          <label className={'toggle mode' + (excludeMode ? ' on' : '')}>
            <input type="checkbox" checked={excludeMode} onChange={e => setExcludeMode(e.target.checked)} />
            <span>Исключать точки кликом</span>
          </label>
        )}
        {project.excluded > 0 && <button type="button" className="quiet" onClick={undo}>Отменить последнее исключение</button>}
        {project.excluded > 0 && <span className="muted">Исключено в проекте: {project.excluded}</span>}
        <span className="spacer" />
        {saved && saved.history.length > 0 && (
          <label className="inline-field">Сохраненный расчет
            <select value="" onChange={e => {
              const item = saved.history[Number(e.target.value)]
              if (item) changeParams(withSettings(spec, { ...defaults(spec), ...item.params }, project))
            }}>
              <option value="">открыть…</option>
              {saved.history.map((h, i) => <option key={i} value={i}>{formatDate(h.date)}</option>)}
            </select>
          </label>
        )}
        {result && spec.save_label && <button type="button" className="quiet" onClick={saveView}>{spec.save_label}</button>}
        {result && result.tables.length > 0 && (
          <button type="button" className="quiet" onClick={() => api.exportTables(spec.id, project.id, params).catch(e => setToast({ text: (e as Error).message, undo: false }))}>
            Все таблицы XLSX
          </button>
        )}
      </div>

      {status.kind === 'error' && (
        <div className={'note ' + (status.missing ? 'info' : 'warning')} role="alert">{status.message}</div>
      )}

      {result && (
        <div className={'results' + (status.kind === 'running' ? ' stale' : '')}>
          {result.notes.map((n, i) => <div key={i} className={'note ' + n.level}>{n.text}</div>)}
          <CommandBar result={result} project={project.id} onDone={text => exclusionDone(text, false)} onError={text => setToast({ text, undo: false })} />
          {result.charts.length > 0 && (
            <>
              {excludeMode && <div className="note info">Щелкните по измеренной точке, чтобы исключить ее из расчета. Расчетные кривые и серые исключенные точки не выбираются.</div>}
              <div className="chart-grid">
                {shown.map(c => (
                  <ChartView key={c.id} chart={c} excludeMode={excludeMode} onExclude={excludePoint}
                    onDownload={(format, dpi) => api.exportChart(spec.id, project.id, params, c.id, format, dpi)} />
                ))}
              </div>
              {result.charts.length > 1 && (
                <div className="pager">
                  <label className="inline-field">Графиков на странице
                    <select value={pageSize} onChange={e => { const v = Number(e.target.value); setPageSize(v); remembered.set('chartPage', v); setPage(1) }}>
                      {PAGE_SIZES.map(n => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </label>
                  <button type="button" className="quiet" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Назад</button>
                  <span>Страница {Math.min(page, pages)} из {pages}, всего графиков {result.charts.length}</span>
                  <button type="button" className="quiet" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Вперед</button>
                </div>
              )}
            </>
          )}
          {result.tables.map(t => (
            <TableView key={t.id} table={t}
              onDownload={format => api.exportTables(spec.id, project.id, params, t.id, format)}
              onApply={t.action ? applyTable(t.action.dataset) : undefined} />
          ))}
        </div>
      )}

      {toast && (
        <div className="toast" role="status">
          <span>{toast.text}</span>
          {toast.undo && <button type="button" onClick={() => { setToast(null); undo() }}>Отменить</button>}
          <button type="button" aria-label="Закрыть" onClick={() => setToast(null)}>×</button>
        </div>
      )}
    </section>
  )
}

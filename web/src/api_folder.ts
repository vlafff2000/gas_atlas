// Папка проекта: список файлов папки, роли и манифест (сервер: atlas/project_folder.py).
import type { Project } from './api'

export interface FolderRole { value: string; label: string }

export interface QcSummary {
  file: string
  title?: string
  summary?: string
  counts?: Record<string, number>
  created?: string
  error?: string
}

export interface FolderFile {
  name: string
  size: number
  modified: string
  role: string | null
  role_label: string
  role_source: '' | 'manifest' | 'name' | 'content'
  role_reason: string
  normalized: boolean
  known: string
  qc: QcSummary | null
  load: FolderLoad | null
}

/** Статус загрузки в проект: null — проект не выбран или файл не таблица. */
export type FolderLoad = 'loaded' | 'changed' | 'not_loaded'

export interface FolderLoadResult {
  name: string
  status: 'loaded' | 'attention' | 'error'
  message: string
  undo?: string
}

export interface FolderLoadReply {
  results: FolderLoadResult[]
  folder: FolderScan
  project: string
  revision: number | null
  warning: string
  /** Снимок до всей пачки: по нему откатывается загрузка целиком (пусто, если ничего не загружено). */
  undo?: string
}

export interface FolderScan {
  folder: string
  manifest: boolean
  warning: string
  roles: FolderRole[]
  registry: { by: 'name' | 'content'; match: string; role: string | null; label: string }[]
  files: FolderFile[]
}

/** Пробная проверка файла без записи в проект: ok — можно грузить, attention — есть замечания, error — не разобран, skip — тип не определён. */
export interface FolderCheck {
  name: string
  role: string | null
  role_label: string
  status: 'ok' | 'attention' | 'error' | 'skip'
  message: string
  issues: { level: string; reason: string }[]
  issues_count: number
}

/** Что делать с файлом, где есть отклонённые строки: не грузить / только корректные / все, плохие исключить из расчётов. */
export type RejectedMode = 'skip' | 'accept' | 'keep'

export interface FolderEdit { role?: string | null; normalized?: boolean }

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error ?? `Ошибка ${response.status}`)
  return data as T
}

/** Общий выбор проекта из «Базы ПХГ»: папка проекта и её подпапки «готовые» и «выгрузки». */
export interface ProjectFolder { slot: 'ready' | 'exports'; label: string; path: string; found: boolean; files: string[] }
export interface ProjectFolders { project: string; folders: ProjectFolder[] }

export const folderApi = {
  projectState: async (): Promise<ProjectFolders> => {
    const r = await fetch('/api/folder/project')
    const data = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(data.error ?? `Ошибка ${r.status}`)
    return data as ProjectFolders
  },
  scan: (folder: string, project?: string) => post<FolderScan>('/api/folder/scan', project ? { folder, project } : { folder }),
  load: (project: string, folder: string, files: string[], policy = 'new', rejected: RejectedMode = 'skip') =>
    post<FolderLoadReply>(`/api/projects/${encodeURIComponent(project)}/folder/load`, { folder, files, policy, rejected }),
  check: (project: string, folder: string, files: string[]) =>
    post<{ results: FolderCheck[] }>(`/api/projects/${encodeURIComponent(project)}/folder/check`, { folder, files }),
  undo: (project: string, snapshot: string, revision: number) =>
    post<Project>(`/api/projects/${encodeURIComponent(project)}/folder/undo`, { snapshot, revision }),
  saveManifest: (folder: string, files: Record<string, FolderEdit>, project?: string) =>
    post<FolderScan>('/api/folder/manifest', project ? { folder, files, project } : { folder, files }),
}

// Папка проекта: список файлов папки, роли и манифест (сервер: atlas/project_folder.py).

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
  role_source: '' | 'manifest' | 'name'
  normalized: boolean
  known: string
  qc: QcSummary | null
}

export interface FolderScan {
  folder: string
  manifest: boolean
  warning: string
  roles: FolderRole[]
  files: FolderFile[]
}

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

export const folderApi = {
  scan: (folder: string) => post<FolderScan>('/api/folder/scan', { folder }),
  saveManifest: (folder: string, files: Record<string, FolderEdit>) =>
    post<FolderScan>('/api/folder/manifest', { folder, files }),
}

// Источник пресетов скважин для списка скважин (MultiSelect, presets=...) и фильтра. Пресеты лежат в well_presets.json проекта Атласа
// (pxg_core/well_presets.py), поэтому одинаковы во всех программах; приложение лишь говорит, по какому адресу их брать.
export interface WellPreset { id: string; kind: string; label: string; wells: string[] }

export interface PresetSource {
  list: () => Promise<WellPreset[]>
  save: (name: string, wells: string[]) => Promise<WellPreset[]>
  remove: (id: string) => Promise<WellPreset[]>
}

const call = async (url: string, init?: RequestInit): Promise<WellPreset[]> => {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.error ?? `Ошибка ${r.status}`)
  return body.presets as WellPreset[]
}

/** Пресеты по адресам вида `<base>` (GET/POST) и `<base>/<id>` (DELETE). Один и тот же объект на один адрес. */
const sources = new Map<string, PresetSource>()
export function presetSource(base = '/api/well-presets'): PresetSource {
  let s = sources.get(base)
  if (!s) {
    s = {
      list: () => call(base),
      save: (name, wells) => call(base, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, wells }) }),
      remove: id => call(`${base}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    }
    sources.set(base, s)
  }
  return s
}

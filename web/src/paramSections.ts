// Группировка параметров по разделам панели: один раздел — один блок,
// даже если его параметры в спецификации перемежаются другими разделами (show_if).
export function groupSections<T extends { section?: string }>(params: T[]): [string, T[]][] {
  const out: [string, T[]][] = []
  for (const p of params) {
    const key = p.section ?? ''
    const same = out.find(s => s[0] === key)
    if (same) same[1].push(p); else out.push([key, [p]])
  }
  return out
}

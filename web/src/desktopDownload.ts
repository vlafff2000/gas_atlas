/**
 * Скачивание файлов в окне приложения (pywebview на Windows).
 * WebView2 не всегда показывает диалог сохранения для blob-ссылок, поэтому, если ядро дало окну
 * метод save_file, файлы уходят через него (системное окно «Сохранить как»). В обычном браузере
 * ничего не меняется: работает штатное скачивание.
 */
interface DesktopApi { save_file?: (name: string, data: string) => Promise<{ ok: boolean; path?: string; error?: string }> }

const bridge = (): DesktopApi | undefined => (window as unknown as { pywebview?: { api?: DesktopApi } }).pywebview?.api

const toBase64 = (blob: Blob) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
  reader.onerror = () => reject(reader.error)
  reader.readAsDataURL(blob)
})

async function saveThroughWindow(url: string, name: string) {
  const api = bridge()!
  const blob = await (await fetch(url)).blob()
  const answer = await api.save_file!(name, await toBase64(blob))
  if (!answer.ok && answer.error) window.alert(`Файл не сохранён: ${answer.error}`)
}

function intercept(a: HTMLAnchorElement): boolean {
  if (!a.hasAttribute('download') || !a.href || !bridge()?.save_file) return false
  const name = a.getAttribute('download') || decodeURIComponent(a.href.split('/').pop()?.split('?')[0] ?? '') || 'atlas'
  saveThroughWindow(a.href, name).catch(e => window.alert(`Файл не сохранён: ${(e as Error).message}`))
  return true
}

export function installDesktopDownload() {
  const click = HTMLAnchorElement.prototype.click
  HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
    if (!intercept(this)) click.call(this)
  }
  document.addEventListener('click', e => {
    const a = (e.target as Element | null)?.closest?.('a[download]') as HTMLAnchorElement | null
    if (a && intercept(a)) e.preventDefault()
  })
}

installDesktopDownload()

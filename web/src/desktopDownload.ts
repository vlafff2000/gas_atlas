/**
 * Скачивание файлов через наш проводник (во всех программах, в браузере и в окне приложения).
 * Любая ссылка <a download> перехватывается: открывается проводник («Сохранить как»), инженер сам выбирает папку и имя,
 * а локальный сервер записывает файл туда (POST /api/fs/save). Системные диалоги WebView2 не используются:
 * на Windows они молча не срабатывали. Последняя папка сохранения запоминается (~/.pxg/ui.json).
 */
import { openFilePicker } from './FilePicker'

/** Имя из Content-Disposition (filename*=UTF-8''… или filename="…"). */
function dispositionName(h: string | null): string {
  if (!h) return ''
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(h)
  if (star) { try { return decodeURIComponent(star[1].trim()) } catch { /* ниже возьмём обычное имя */ } }
  const plain = /filename\s*=\s*"?([^";]+)"?/.exec(h)
  return plain ? plain[1].trim() : ''
}

const lastSegment = (url: string) => { try { return decodeURIComponent(url.split('#')[0].split('?')[0].split('/').pop() ?? '') } catch { return '' } }

function toast(text: string, bad = false) {
  const el = document.createElement('div')
  el.textContent = text
  el.setAttribute('role', 'status')
  el.style.cssText = `position:fixed;right:16px;bottom:16px;z-index:100000;max-width:480px;padding:10px 14px;border-radius:6px;font:13px/1.4 system-ui,sans-serif;color:#fff;background:${bad ? '#b3261e' : '#1b6e3c'};box-shadow:0 4px 14px rgba(0,0,0,.3);word-break:break-all`
  document.body.appendChild(el)
  setTimeout(() => el.remove(), bad ? 9000 : 5000)
}

/** Предложить сохранить файл: проводник → запись на диск. Вернёт путь или null (отмена). */
export async function saveFileWithPicker(source: Blob | Promise<Blob>, name: string): Promise<string | null> {
  const blob = Promise.resolve(source)
  blob.catch(() => undefined)  // ошибку чтения покажем ниже, не теряя её как «необработанную»
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : ''
  const target = await openFilePicker({ mode: 'save', name, filter: ext, title: 'Сохранить файл' })
  if (!target) return null
  const r = await fetch('/api/fs/save?overwrite=1&path=' + encodeURIComponent(target), {
    method: 'POST', headers: { 'X-PXG': '1', 'Content-Type': 'application/octet-stream' }, body: await blob })
  const answer = (await r.json().catch(() => ({}))) as { ok?: boolean; path?: string; error?: string }
  if (!r.ok || !answer.ok) throw new Error(answer.error || `ошибка ${r.status}`)
  return answer.path || target
}

async function saveAnchor(a: HTMLAnchorElement) {
  const href = a.href
  // запрос уходит сразу: ссылку на blob после click() часто тут же отзывают
  const resp = await fetch(href)
  if (!resp.ok) throw new Error(`не удалось получить файл (${resp.status})`)
  const blob = resp.blob()
  const name = a.getAttribute('download') || dispositionName(resp.headers.get('Content-Disposition')) || lastSegment(href) || 'файл'
  const path = await saveFileWithPicker(blob, name)
  if (path) toast('Сохранено: ' + path)
}

function intercept(a: HTMLAnchorElement): boolean {
  if (!a.hasAttribute('download') || !a.href || a.href.startsWith('javascript:')) return false
  saveAnchor(a).catch(e => toast(`Файл не сохранён: ${(e as Error).message}`, true))
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

"""Браузерный обход всех разделов Атласа (Playwright) на демо-проекте.

Для каждого раздела из /api/modules: открыть страницу, дождаться окончания расчёта, собрать ошибки
консоли, необработанные исключения JS и неудачные запросы (4xx/5xx), проверить что нарисованные
графики не пусты (canvas с пикселями). Новые разделы попадают в обход сами. Запуск:
``python tools/check_browser.py`` (нужны playwright и chromium; код выхода 1 при замечаниях).
409 — штатный ответ «нет данных для раздела», ошибкой не считается. Известные допустимые замечания — в ``tools/browser_allow.json`` (список подстрок), с причиной.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get('ATLAS_CHECK_PORT', '8791'))
BASE = f'http://127.0.0.1:{PORT}'
PAGE_TIMEOUT_MS = 30_000


def call(path: str, data: dict | None = None):
    req = urllib.request.Request(BASE + path, method='POST' if data is not None else 'GET',
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def start_server(storage: str) -> subprocess.Popen:
    env = {**os.environ, 'GAS_ATLAS_STORAGE': storage}
    proc = subprocess.Popen([sys.executable, '-m', 'atlas', '--server', '--port', str(PORT)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            call('/api/health')
            return proc
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit('Сервер не поднялся')


# Пиксели canvas: доля не прозрачных и не белых точек на сетке выборки.
CANVAS_JS = """() => [...document.querySelectorAll('[_echarts_instance_] canvas')].filter(c => c.width > 200 && c.height > 100).map(c => {
  let ink = 0, n = 0;
  try {
    const g = document.createElement('canvas'); g.width = Math.min(c.width, 400); g.height = Math.min(c.height, 300);
    const x = g.getContext('2d'); x.drawImage(c, 0, 0, g.width, g.height);
    const d = x.getImageData(0, 0, g.width, g.height).data;
    for (let i = 0; i < d.length; i += 4) { n++; if (d[i + 3] > 0 && !(d[i] > 245 && d[i + 1] > 245 && d[i + 2] > 245)) ink++ }
  } catch (e) { return { w: c.width, h: c.height, ink: -1 } }
  return { w: c.width, h: c.height, ink, n }
})"""


def main() -> int:
    from playwright.sync_api import sync_playwright
    allow = []
    f = ROOT / 'tools' / 'browser_allow.json'
    if f.exists():
        allow = [a['match'] for a in json.loads(f.read_text(encoding='utf-8'))]
    with tempfile.TemporaryDirectory() as storage:
        proc = start_server(storage)
        problems: list[str] = []
        try:
            modules = call('/api/modules')
            pid = call('/api/projects/demo', {})['id']
            with sync_playwright() as p:
                browser = p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get('CHROMIUM_PATH') or None)
                ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, locale='ru-RU')
                ctx.add_init_script(f"try{{localStorage.setItem('atlas:project', JSON.stringify('{pid}'))}}catch(e){{}}")
                page = ctx.new_page()
                log: list[str] = []
                page.on('console', lambda m: log.append(f'console.{m.type}: {m.text}') if m.type == 'error' and '(Conflict)' not in m.text else None)
                page.on('pageerror', lambda e: log.append(f'pageerror: {e}'))
                page.on('requestfailed', lambda r: log.append(f'requestfailed: {r.method} {r.url} {r.failure}')
                        if 'abort' not in str(r.failure).lower() else None)
                page.on('response', lambda r: log.append(f'HTTP {r.status}: {r.request.method} {r.url}') if r.status >= 400 and r.status != 409 else None)
                page.goto(BASE + '/', wait_until='networkidle')
                for m in modules:
                    mid = m['id']
                    t0 = time.monotonic()
                    page.evaluate(f"location.hash = '#/{mid}'")
                    try:
                        page.wait_for_load_state('networkidle', timeout=PAGE_TIMEOUT_MS)
                        page.wait_for_function("() => !document.querySelector('.busy-bar, [aria-busy=true]')", timeout=PAGE_TIMEOUT_MS)
                        page.wait_for_timeout(700)   # отрисовка ECharts после данных
                    except Exception as e:
                        log.append(f'timeout: {type(e).__name__}')
                    text = page.inner_text('main') if page.query_selector('main') else page.inner_text('body')
                    charts = page.evaluate(CANVAS_JS)
                    for c in charts:
                        if c['ink'] == 0:
                            log.append(f'пустой график {c["w"]}x{c["h"]}')
                    bad = [l for l in log if not any(a in l for a in allow)]
                    state = 'ОК ' if not bad else 'ОШИБКА'
                    print(f'{state} {mid:<22} {time.monotonic() - t0:5.1f} c  графиков: {len(charts)}  текста: {len(text)}', flush=True)
                    for l in bad:
                        print('     ', l[:300])
                        problems.append(f'{mid}: {l[:300]}')
                    log.clear()
                browser.close()
        finally:
            proc.terminate()
    if problems:
        print(f'\nЗамечаний: {len(problems)}')
        return 1
    print('\nВсе разделы открылись без ошибок')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

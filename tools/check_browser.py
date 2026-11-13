"""Браузерный обход всех разделов Атласа (Playwright) на демо-проекте.

Для каждого раздела из /api/modules: открыть страницу, дождаться окончания расчёта, собрать ошибки
консоли, необработанные исключения JS и неудачные запросы (4xx/5xx), проверить что нарисованные
графики не пусты (canvas с пикселями). Новые разделы попадают в обход сами. В конце — сценарий предпросмотра «как в файле»
(``stage_scenario``): перетащить заголовок и убедиться, что он встал туда же в новом рисунке. Запуск:
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


def call(path: str, data: dict | None = None, method: str | None = None):
    req = urllib.request.Request(BASE + path, method=method or ('POST' if data is not None else 'GET'),
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


STAGE_MODULE, STAGE_PARAMS = 'gdi', {'wells': ['31', '70']}


def stage_scenario(page, pid: str) -> list[str]:
    """Сценарий предпросмотра с диагностикой: при сбое в замечание попадает, какие запросы вкладки ушли и что показывает страница."""
    seen: list[str] = []

    def note(r):
        if '/export/any/' in r.url:
            seen.append(f'{r.status} {r.url.rsplit("/", 1)[-1]}')

    page.on('response', note)
    try:
        return _stage_scenario(page, pid)
    except Exception as e:
        try:
            shown = f'предпросмотров на странице: {page.locator(".stage").count()}, заметки: {page.locator(".note").all_inner_texts()[:3]}'
        except Exception:
            shown = 'страница не отвечает'
        return [f'{type(e).__name__}: {str(e)[:160]}; ответы вкладки: {seen[-8:]}; {shown}']
    finally:
        page.remove_listener('response', note)


def _stage_scenario(page, pid: str) -> list[str]:
    """Предпросмотр «как в файле» (Экспорт → Любой график): перетащенный заголовок в новом рисунке стоит там, куда его отпустили,
    а остальное осталось на месте. Рисунок предпросмотра — тот же PNG, что уходит на выгрузку (tests/atlas/test_export_any.py)."""
    def is_preview(r):
        return r.url.endswith('/export/any/preview') and r.status == 200

    def boxes(response):
        return {e['id']: e['box'] for e in response.json()['scene']}

    # Раздел, скважины и график заданы заранее (как «последний выбор» в проекте): сценарий не зависит от значений по умолчанию.
    found = call(f'/api/projects/{pid}/export/any/charts', {'module': STAGE_MODULE, 'params': STAGE_PARAMS})['charts']
    if not found:
        return ['в разделе «ГДИ» демо-проекта нет графиков для предпросмотра']
    last = {'module': STAGE_MODULE, 'chart': found[0]['id'], 'params': STAGE_PARAMS}
    call(f'/api/projects/{pid}/settings', {'values': {'export_any': {'last': last}}}, 'PATCH')
    page.evaluate("location.hash = '#/@export'")
    page.reload(wait_until='networkidle')
    with page.expect_response(is_preview, timeout=PAGE_TIMEOUT_MS) as first:
        page.get_by_text('Любой график', exact=True).first.click()
    before = boxes(first.value)
    stage = page.locator('.stage')
    stage.wait_for(timeout=PAGE_TIMEOUT_MS)
    page.wait_for_timeout(1500)      # настройки графика улеглись: больше предпросмотр сам не перерисуется
    stage.scroll_into_view_if_needed()
    if 'title' not in before:
        return ['в сцене предпросмотра нет заголовка']
    rect = stage.bounding_box()
    x = rect['x'] + (before['title'][0] + before['title'][2]) / 2 * rect['width']
    y = rect['y'] + (before['title'][1] + before['title'][3]) / 2 * rect['height']
    page.mouse.move(x, y)
    page.mouse.down()
    with page.expect_response(is_preview, timeout=PAGE_TIMEOUT_MS) as moved:
        page.mouse.move(x + 90, y + 45, steps=6)
        page.mouse.up()
    after = boxes(moved.value)
    want = (90 / rect['width'], 45 / rect['height'])
    got = (after['title'][0] - before['title'][0], after['title'][1] - before['title'][1])
    out = []
    if abs(got[0] - want[0]) > 0.004 or abs(got[1] - want[1]) > 0.004:
        out.append(f'заголовок сдвинут на {got[0]:.4f}, {got[1]:.4f} рисунка вместо {want[0]:.4f}, {want[1]:.4f}')
    if after.get('plot') != before.get('plot'):
        out.append('после сдвига заголовка изменилась область построения')
    if 'Своё положение: 1' not in page.inner_text('.stage-bar'):
        out.append('панель предпросмотра не показывает, что у элемента своё положение')
    return out


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
                t0 = time.monotonic()
                try:
                    bad = stage_scenario(page, pid)
                except Exception as e:
                    bad = [f'{type(e).__name__}: {str(e)[:200]}']
                bad += [l for l in log if not any(a in l for a in allow)]
                print(f'{"ОК " if not bad else "ОШИБКА"} {"предпросмотр файла":<22} {time.monotonic() - t0:5.1f} c', flush=True)
                for l in bad:
                    print('     ', l[:300])
                    problems.append(f'export-stage: {l[:300]}')
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

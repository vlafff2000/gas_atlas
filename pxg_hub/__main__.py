"""Запуск: ``python -m pxg_hub`` — меню приложений ПХГ (окно или браузер)."""
from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .hub import Hub, app_url, port_open


def open_app(app) -> None:
    """Отдельное окно приложения (Chromium --app), нет браузера — обычная вкладка. Окно меню остаётся."""
    from atlas.app_window import open_app_window
    if open_app_window(app_url(app), app.title) is None:
        webbrowser.open(app_url(app))

PAGE = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ПХГ — все приложения</title><style>
:root{--bg:#f5f6f8;--card:#fff;--text:#1d2330;--muted:#667085;--line:#d9dde5;--accent:#1f5fbf;--ok:#1a7f4b}
@media (prefers-color-scheme:dark){:root{--bg:#161a22;--card:#1f2430;--text:#e8ebf2;--muted:#9aa3b5;--line:#343b4a;--accent:#6aa3ff;--ok:#4cc38a}}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:28px 16px}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:8px}
.card h2{font-size:17px;margin:0}.card p{margin:0;color:var(--muted);flex:1}.st{font-size:13px;color:var(--muted)}.st.on{color:var(--ok)}
.row{display:flex;gap:8px}button{font:inherit;padding:7px 14px;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--text);cursor:pointer}
button.main{background:var(--accent);border-color:var(--accent);color:#fff}button:disabled{opacity:.55;cursor:wait}
#err{color:#c0392b;margin-top:14px;white-space:pre-wrap}footer{margin-top:22px;color:var(--muted);font-size:13px}
</style></head><body><main><h1>Газовый атлас и приложения ПХГ</h1>
<p class="sub">Папка проекта: <span id="proj"></span>. Все приложения кладут данные в неё и знают адреса друг друга.</p>
<div class="grid" id="grid"></div><div id="err"></div>
<footer><button id="quit">Закрыть все приложения и меню</button></footer></main><script>
const H={'X-PXG':'1'};
async function post(u){const r=await fetch(u,{method:'POST',headers:H});const j=await r.json();if(!r.ok)throw new Error(j.error||r.statusText);return j}
async function load(){const j=await (await fetch('/api/status')).json();document.getElementById('proj').textContent=j.project;
 document.getElementById('grid').innerHTML=j.apps.map(a=>`<div class="card"><h2>${a.title}</h2><p>${a.note}</p>
 <div class="st ${a.running?'on':''}">${a.running?'работает: '+a.url:'остановлено'}</div>
 <div class="row"><button class="main" data-open="${a.id}">Открыть</button>${a.ours?`<button data-stop="${a.id}">Остановить</button>`:''}</div></div>`).join('')}
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;const err=document.getElementById('err');err.textContent='';
 try{if(b.dataset.open){b.disabled=true;b.textContent='Запускаю…';await post('/api/start/'+b.dataset.open+'?open=1')}
  else if(b.dataset.stop)await post('/api/stop/'+b.dataset.stop);
  else if(b.id==='quit'){await post('/api/quit');document.body.innerHTML='<main><p>Приложения остановлены. Окно можно закрыть.</p></main>';return}}
 catch(x){err.textContent=x.message}load()});
load();setInterval(load,3000);
</script></body></html>'''


def make_handler(hub: Hub, quit_event: threading.Event):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # тишина в терминале
            pass

        def send(self, code, body, kind='application/json; charset=utf-8'):
            data = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def host_ok(self):  # защита от DNS-rebinding: чужое имя в Host не пускаем
            return self.headers.get('Host', '').rsplit(':', 1)[0] in ('127.0.0.1', 'localhost')

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, '{}')
            if self.path == '/':
                self.send(200, PAGE, 'text/html; charset=utf-8')
            elif self.path == '/api/status':
                self.send(200, json.dumps({'project': str(hub.project), 'apps': hub.status()}, ensure_ascii=False))
            else:
                self.send(404, '{}')

        def do_POST(self):
            if not self.host_ok() or self.headers.get('X-PXG') != '1':  # чужая страница в браузере не может запускать процессы
                return self.send(403, json.dumps({'error': 'запрещено'}))
            path, _, query = self.path.partition('?')
            parts = path.strip('/').split('/')
            try:
                if parts[:2] == ['api', 'start'] and parts[2] in hub.apps:
                    result = hub.start(parts[2])
                    if 'open=1' in query.split('&'):  # окно открывает сам процесс меню: window.open из окна меню рождает пустое «about:blank»
                        open_app(hub.apps[parts[2]])
                    return self.send(200, json.dumps(result, ensure_ascii=False))
                if parts[:2] == ['api', 'stop'] and parts[2] in hub.apps:
                    hub.stop(parts[2])
                    return self.send(200, '{}')
                if parts == ['api', 'quit']:
                    hub.stop_all()
                    quit_event.set()
                    return self.send(200, '{}')
            except Exception as error:
                return self.send(500, json.dumps({'error': str(error)}, ensure_ascii=False))
            self.send(404, '{}')

    return Handler


def serve(hub: Hub, port: int):
    quit_event = threading.Event()
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(hub, quit_event))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, quit_event


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog='pxg_hub', description='Меню приложений ПХГ')
    parser.add_argument('--port', type=int, default=8760)
    parser.add_argument('--browser', action='store_true', help='открыть в браузере, а не в окне')
    parser.add_argument('--server', action='store_true', help='только меню, ничего не открывать')
    args = parser.parse_args(argv)
    if port_open(args.port):  # меню уже запущено: просто открыть его
        url = 'http://127.0.0.1:%d/' % args.port
        if not args.server:
            webbrowser.open(url)
        print('Меню уже запущено:', url)
        return
    hub = Hub()
    try:
        server, quit_event = serve(hub, args.port)
    except OSError as error:
        raise SystemExit('Не удалось занять порт %d (%s). Закройте программу, которая его использует, или укажите --port.' % (args.port, error))
    url = 'http://127.0.0.1:%d/' % args.port
    print('ПХГ — все приложения: %s\nПапка проекта: %s' % (url, hub.project))
    try:
        if args.server:
            quit_event.wait()
            return
        window = False
        if not args.browser:
            try:
                import webview
                webview.create_window('ПХГ — все приложения', url, width=980, height=640)
                webview.start()
                window = True  # окно открылось и было закрыто пользователем
            except Exception as error:  # нет WebView2/библиотеки окна: меню откроется в браузере, а не молча закроется
                print('Окно приложения недоступно (%s) — открываю в браузере' % error)
        if not window and not args.browser:  # окно приложения через Яндекс/Chromium/Chrome (--app)
            from atlas.app_window import open_app_window, wait_closed
            proc = open_app_window(url, 'ПХГ меню')
            if proc is not None:
                if wait_closed(proc):
                    return
                window = True
                print('Остановка — кнопка «Закрыть все» в меню или Ctrl+C')
                quit_event.wait()
        if not window:
            webbrowser.open(url)
            print('Остановка — кнопка «Закрыть все» в меню или Ctrl+C')
            quit_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        hub.stop_all()
        server.shutdown()


if __name__ == '__main__':
    main()

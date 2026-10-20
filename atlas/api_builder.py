"""API библиотеки макетов конструктора графиков: список, создание, открытие, переименование, копия, удаление,
файл JSON (экспорт и импорт), Word с одним графиком. Логика — ``atlas/builder_library.py``."""
from __future__ import annotations

from urllib.parse import quote

from starlette.responses import Response
from starlette.routing import Route

from . import builder_library as lib
from .contract import ParamError
from .engine.core.export import safe_name

DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
ACTION = 'Макеты конструктора'


def _download(content: bytes, name: str, mime: str) -> Response:
    return Response(content, media_type=mime, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})


def routes(projects, E) -> list[Route]:
    def settings_of(request):
        return projects.manifest(request.path_params['pid']).get('settings', {})

    def save(request, cfg, details):
        projects._commit(request.path_params['pid'], cfg, None, ACTION, details)

    def listing(request, body):
        return {'items': lib.listing(settings_of(request))}

    def create(request, body):
        cfg, item = lib.add(settings_of(request), body.get('name'), body.get('layout'))
        save(request, cfg, {'action': 'создан', 'name': item['name']})
        return {'item': lib.summary(item), 'items': lib.listing(cfg)}

    def opened(request, body):
        item = lib.find(settings_of(request), request.path_params['lid'])
        data = projects.select(request.path_params['pid'], (), tuple(lib.DatasetKind))
        return {'id': item['id'], 'name': item['name'], 'layout': item['layout'], 'missing': lib.missing_of(data, item['layout'])}

    def change(request, body):
        cfg, item = lib.change(settings_of(request), request.path_params['lid'], body.get('name'), body.get('layout'))
        save(request, cfg, {'action': 'изменён', 'name': item['name']})
        return {'item': lib.summary(item), 'items': lib.listing(cfg)}

    def duplicate(request, body):
        cfg, item = lib.duplicate(settings_of(request), request.path_params['lid'])
        save(request, cfg, {'action': 'копия', 'name': item['name']})
        return {'item': lib.summary(item), 'items': lib.listing(cfg)}

    def delete(request, body):
        old = lib.find(settings_of(request), request.path_params['lid'])
        cfg = lib.remove(settings_of(request), old['id'])
        save(request, cfg, {'action': 'удалён', 'name': old['name']})
        return {'items': lib.listing(cfg)}

    def import_file(request, body):
        text = body.get('content')
        if not isinstance(text, str):
            raise ParamError('Файл макета не получен')
        name, layout = lib.from_file(text)
        settings = settings_of(request)
        names = {i['name'].casefold() for i in lib.items_of(settings)}
        name = name or str(body.get('file_name') or '').rsplit('.', 1)[0] or 'Импортированный макет'
        base, n = name, 1
        while name.casefold() in names:
            n += 1
            name = f'{base} (импорт{"" if n == 2 else " " + str(n - 1)})'
        cfg, item = lib.add(settings, name, layout)
        save(request, cfg, {'action': 'импорт', 'name': item['name']})
        data = projects.select(request.path_params['pid'], (), tuple(lib.DatasetKind))
        return {'item': lib.summary(item), 'items': lib.listing(cfg), 'layout': item['layout'], 'missing': lib.missing_of(data, layout)}

    def export_file(request, body):
        name = ' '.join(str(body.get('name') or 'Макет').split())[:120] or 'Макет'
        return _download(lib.to_file(name, body.get('layout')), safe_name(name) + '.layout.json', 'application/json')

    def word(request, body):
        data = projects.select(request.path_params['pid'], (), tuple(lib.DatasetKind))
        chart, notes = lib.chart_of(data, body.get('layout'))
        if chart is None:
            raise ParamError('Нечего выгружать: на графике нет рядов с данными.' + (' ' + notes[0] if notes else ''))
        title = str(body.get('title') or chart.title or '').strip()[:300]
        caption = str(body.get('caption') or title or '').strip()[:500]
        orientation = body.get('orientation') or 'landscape'
        if orientation not in ('landscape', 'portrait'):
            raise ParamError('Ориентация листа: альбомная или книжная')
        content, name = lib.word_file(chart, title, caption, orientation)
        return _download(content, safe_name(title or name.removesuffix('.docx')) + '.docx', DOCX)

    base = '/api/projects/{pid}/builder'
    return [
        Route(base + '/layouts', E(listing), methods=['GET']),
        Route(base + '/layouts', E(create), methods=['POST']),
        Route(base + '/layouts/import', E(import_file), methods=['POST']),
        Route(base + '/layouts/file', E(export_file), methods=['POST']),
        Route(base + '/layouts/{lid}', E(opened), methods=['GET']),
        Route(base + '/layouts/{lid}', E(change), methods=['PATCH']),
        Route(base + '/layouts/{lid}', E(delete), methods=['DELETE']),
        Route(base + '/layouts/{lid}/duplicate', E(duplicate), methods=['POST']),
        Route(base + '/word', E(word), methods=['POST']),
    ]

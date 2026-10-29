"""API библиотеки макетов конструктора графиков: список, создание, открытие, переименование, копия, удаление,
файл JSON (экспорт и импорт), Word с одним графиком. Логика — ``atlas/builder_library.py``."""
from __future__ import annotations

from urllib.parse import quote

import pandas as pd
from starlette.responses import Response
from starlette.routing import Route

from . import builder_library as lib
from . import model_source
from .contract import ParamError
from .engine.core.export import safe_name

DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
ACTION = 'Макеты конструктора'


def _download(content: bytes, name: str, mime: str) -> Response:
    return Response(content, media_type=mime, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})


def routes(projects, E) -> list[Route]:
    def settings_of(request):
        m = projects.manifest(request.path_params['pid'])
        if not hasattr(request.state, 'revision'):
            request.state.revision = m.get('revision')      # версия, на которой правим: параллельная правка не затирается молча
        return m.get('settings', {})

    def save(request, cfg, details):
        projects._commit(request.path_params['pid'], cfg, getattr(request.state, 'revision', None), ACTION, details)

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
        caption_mode = body.get('caption_mode') or 'field'
        if caption_mode not in ('field', 'text'):
            raise ParamError('Вид номера рисунка: поле Word или обычный текст')
        content, name = lib.word_file(chart, title, caption, orientation, caption_mode=caption_mode)
        return _download(content, safe_name(title or name.removesuffix('.docx')) + '.docx', DOCX)

    def series_wells(request, body):
        data = projects.select(request.path_params['pid'], (), tuple(lib.DatasetKind))
        return {**lib.wells_info(data, body.get('layout')), 'limit': lib.MAX_WELLS, 'formats': lib.SERIES_FORMATS}

    def series(request, body):
        data = projects.select(request.path_params['pid'], (), tuple(lib.DatasetKind))
        wells = body.get('wells')
        if not isinstance(wells, list):
            raise ParamError('Выберите скважины для серии')
        orientation = body.get('orientation') or 'landscape'
        if orientation not in ('landscape', 'portrait'):
            raise ParamError('Ориентация листа: альбомная или книжная')
        content, name, mime, notes = lib.series_file(data, body.get('layout'), [str(w) for w in wells], str(body.get('format') or 'png'),
                                                     str(body.get('title') or '').strip()[:300], orientation,
                                                     caption_mode=body.get('caption_mode') or 'field')
        response = _download(content, name, mime)
        if notes:
            response.headers['X-Atlas-Notes'] = quote(' '.join(notes))
        return response

    def clean_cells(raw):
        if not isinstance(raw, dict):
            raise ParamError('Настройки ячеек: ожидается объект')
        dates = raw.get('dates') or []
        if not isinstance(dates, list) or len(dates) > model_source.MAX_CELL_DATES:
            raise ParamError(f'Дат рестарта для ячеек не больше {model_source.MAX_CELL_DATES}')
        try:
            clean = [pd.Timestamp(str(d)[:10]).strftime('%Y-%m-%d') for d in dates]
            k_from, k_to, limit = (int(raw.get(k) or d) for k, d in (('k_from', 1), ('k_to', 0), ('max_points', 20000)))
        except (TypeError, ValueError):
            raise ParamError('Ячейки: даты ГГГГ-ММ-ДД, слои и число точек — целые') from None
        if k_from < 1 or k_to < 0 or (k_to and k_to < k_from) or not 100 <= limit <= 200_000:
            raise ParamError('Ячейки: слои с 1 (до пусто или не меньше начального), точек от 100 до 200 000')
        return {'dates': clean, 'k_from': k_from, 'k_to': k_to, 'max_points': limit}

    def refresh_cubes(request, body):
        cfg = settings_of(request)
        for crit in model_source.criterion_list_of(cfg):
            model_source.forget_cubes(model_source.sources_of(cfg), crit)
        return model_source.listing(model_source.sources_of(cfg), model_source.cubes_on(cfg), model_source.cubes_range(cfg), model_source.cells_of(cfg))

    def restarts(request, body):
        model = request.query_params.get('model', '')
        if model not in model_source.sources_of(settings_of(request)):
            raise ParamError('Сначала отметьте модель')
        try:
            return {'dates': model_source.restart_dates(model)}
        except model_source.ModelUnavailable as e:
            raise ParamError(str(e)) from None

    def models(request, body):
        cfg = settings_of(request)
        return model_source.listing(model_source.sources_of(cfg), model_source.cubes_on(cfg), model_source.cubes_range(cfg), model_source.cells_of(cfg))

    def criterion_info(request, body):
        cfg = settings_of(request)
        return {**model_source.criterion_view(model_source.criterion_of(cfg)), 'variants': cfg.get(model_source.VARIANTS_KEY) or []}

    def choose_models(request, body):
        picked = body.get('selected')
        if not isinstance(picked, list):
            raise ParamError('Выберите модели списком')
        cfg = dict(settings_of(request))
        cfg[model_source.KEY] = [str(x) for x in picked]
        if 'cubes' in body:
            cfg[model_source.CUBES_KEY] = body['cubes'] is True
        for key, name in zip(model_source.CUBES_RANGE, ('cubes_from', 'cubes_to')):
            if name in body:
                text = str(body[name] or '').strip()[:10]
                try:
                    if text:
                        pd.Timestamp(text)
                except ValueError:
                    raise ParamError('Дата рестарта: ГГГГ-ММ-ДД') from None
                cfg[key] = text
        if 'cells' in body:
            cfg[model_source.CELLS_KEY] = clean_cells(body['cells'])
        try:
            if 'criterion' in body:
                cfg[model_source.CRITERION_KEY] = model_source.criterion_clean(body['criterion'])
            if 'criterion_variants' in body:
                cfg[model_source.VARIANTS_KEY] = model_source.variants_clean(body['criterion_variants'])
        except ValueError as e:
            raise ParamError(str(e)) from None
        if all(model_source.cubes_range(cfg)) and model_source.cubes_range(cfg)[0] > model_source.cubes_range(cfg)[1]:
            raise ParamError('Рестарты «с» не могут быть позже «по»')
        save(request, cfg, {'action': 'модели ГДМ в конструкторе', 'count': len(picked)})
        return model_source.listing(cfg[model_source.KEY], model_source.cubes_on(cfg), model_source.cubes_range(cfg), model_source.cells_of(cfg))

    base = '/api/projects/{pid}/builder'
    return [
        Route(base + '/layouts', E(listing), methods=['GET']),
        Route(base + '/criterion', E(criterion_info), methods=['GET']),
        Route(base + '/layouts', E(create), methods=['POST']),
        Route(base + '/layouts/import', E(import_file), methods=['POST']),
        Route(base + '/layouts/file', E(export_file), methods=['POST']),
        Route(base + '/layouts/{lid}', E(opened), methods=['GET']),
        Route(base + '/layouts/{lid}', E(change), methods=['PATCH']),
        Route(base + '/layouts/{lid}', E(delete), methods=['DELETE']),
        Route(base + '/layouts/{lid}/duplicate', E(duplicate), methods=['POST']),
        Route(base + '/models', E(models), methods=['GET']),
        Route(base + '/models/restarts', E(restarts), methods=['GET']),
        Route(base + '/models/refresh', E(refresh_cubes), methods=['POST']),
        Route(base + '/models', E(choose_models), methods=['POST']),
        Route(base + '/word', E(word), methods=['POST']),
        Route(base + '/series/wells', E(series_wells), methods=['POST']),
        Route(base + '/series', E(series), methods=['POST']),
    ]

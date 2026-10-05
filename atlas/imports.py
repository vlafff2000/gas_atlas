"""Импорт данных в проект (раздел 5.8 «Импорт данных» и загрузка данных «Кроссплота давлений»).

Здесь только выбор данных и порядок шагов. Чтение файлов, распознавание шапки, проверка строк, слияние
и сопоставление факта с моделью — код 5.8: ``app/core/loader.py``, ``tabular.py``, ``import_rules.py``,
``pressure_import.py``, ``profiles.py``; запись — ``Store.commit`` с теми же действиями журнала,
что пишет 5.8 («Импорт данных», «Результат импорта», «Импорт кроссплота давлений»).

Шаги: загрузить файлы (``upload``) → посмотреть распознавание (``inspect`` / ``sheet``) →
проверить (``check``) → применить (``apply``). Загруженные файлы и проверенный результат держатся
в памяти ядра до применения.
"""
from __future__ import annotations

import hashlib
import tempfile
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pandas as pd

from app.core import import_rules as rules
from app.core import pressure_import as pq
from app.core import profiles, tabular
from app.core.config import MODULES, ROOT
from app.core.loader import column_map, detect_layout, load_file
from app.core import pressure_demo
from app.core.templates import input_templates
from app.core.well_import import REQUIRED

from .contract import Column, ParamError, Table, _table_json
from . import quality
from .projects import Conflict, Projects

QUALITY_ROWS = 500
MAX_FILES = 200
BINARY = (b'PK', b'\xd0\xcf\x11\xe0')
POLICIES = {'new': 'Добавить, совпадения заменить новыми', 'old': 'Добавить, совпадения оставить прежними',
            'replace': 'Заменить целиком только импортируемые модули'}
PRESSURE_MODES = {'add': 'Добавить / обновить объекты', 'scenarios': 'Добавить сценарии к объектам (прежние сохраняются)',
                  'replace': 'Заменить все данные давлений'}
DUPLICATES = {'first': 'Первая запись (как в Python-скрипте)', 'last': 'Последняя запись',
              'mean': 'Среднее значение', 'error': 'Остановить импорт'}
EXAMPLES = ROOT / 'examples'
ISSUE_COLUMNS = ['Файл', 'Лист', 'Строка', 'Уровень', 'Причина']
EDITOR_REQUIRED = {'production': ['well', 'date', 'q'], 'gdi': ['well', 'date', 'q'], 'response': ['well', 'date', 'horizon'],
                   'object_pressure': ['date', 'pressure'], 'plan': ['group', 'date', 'plan_volume'], 'groups': ['well', 'group'], 'subgroups': ['well', 'subgroup']}


def module_label(value) -> str:
    return MODULES.get(value, 'Группы') if value != 'subgroups' else 'Подгруппы'


def preview_json(raw: pd.DataFrame) -> dict[str, Any]:
    """Первые строки листа как есть: номера строк соответствуют файлу."""
    text = raw.fillna('').astype(str)
    return {'columns': [f'Колонка {j + 1}' for j in range(raw.shape[1])], 'rows': text.values.tolist()}


def frame_table(tid: str, title: str, frame: pd.DataFrame, note: str = '') -> dict[str, Any]:
    frame = frame.drop(columns=[c for c in ('_point_id',) if c in frame]).reset_index(drop=True)
    frame.columns = [str(c) for c in frame.columns]
    return _table_json(Table(tid, title, frame, note=note))


class Upload:
    def __init__(self, name: str, content: bytes):
        self.token = uuid.uuid4().hex
        self.name = Path(name or 'Файл').name or 'Файл'
        self.content = content
        self.sha = hashlib.sha256(content + self.name.encode()).hexdigest()   # как ключ листа в 5.8

    @property
    def binary(self) -> bool:
        return self.content.startswith(BINARY)


class Imports:
    def __init__(self, projects: Projects):
        self.projects = projects
        self.lock = threading.RLock()
        self.files: OrderedDict[str, Upload] = OrderedDict()
        self.samples: OrderedDict[tuple, tuple] = OrderedDict()
        self.full: OrderedDict[tuple, dict] = OrderedDict()
        self.parsed: OrderedDict[tuple, dict] = OrderedDict()
        self.pending: OrderedDict[str, dict] = OrderedDict()

    # ---------- файлы ----------
    @staticmethod
    def _keep(cache: OrderedDict, key, value, size: int):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > size:
            cache.popitem(last=False)
        return value

    def upload(self, name: str, content: bytes) -> dict[str, Any]:
        if not content:
            raise ParamError('Пустой файл')
        item = Upload(name, content)
        with self.lock:
            self._keep(self.files, item.token, item, MAX_FILES)
        out = {'token': item.token, 'name': item.name, 'bytes': len(content), 'binary': item.binary}
        try:
            fmt, tables = self.sample(item.token)
            out.update(format=fmt, sheets=list(tables), error='')
        except Exception as e:        # файл принят, но не читается: сообщение — в строке таблицы
            out.update(format='?', sheets=[], error=str(e))
        return out

    def file(self, token: str) -> Upload:
        with self.lock:
            item = self.files.get(token)
        if item is None:
            raise KeyError('Файл не найден: загрузите его заново')
        return item

    def sample(self, token: str, encoding='auto', delimiter='auto'):
        """Первые 31 строка каждого листа (``import_editor.samples`` в 5.8)."""
        key = (token, encoding, delimiter)
        with self.lock:
            if key in self.samples:
                return self.samples[key]
        item = self.file(token)
        value = tabular.read_content(item.content, item.name, 31, encoding, delimiter)
        with self.lock:
            return self._keep(self.samples, key, value, 64)

    def tables(self, token: str, encoding='auto', delimiter='auto') -> dict[str, pd.DataFrame]:
        """Все строки каждого листа (``import_editor.full_tables``)."""
        key = (token, encoding, delimiter)
        with self.lock:
            if key in self.full:
                return self.full[key]
        item = self.file(token)
        value = tabular.read_content(item.content, item.name, None, encoding, delimiter)[1]
        with self.lock:
            return self._keep(self.full, key, value, 16)

    def raw(self, token, sheet, encoding='auto', delimiter='auto', pressure=False) -> pd.DataFrame:
        """Лист для редактора: как в 5.8 — образец 31 строки; для давлений — начало полного листа."""
        tables = self.tables(token, encoding, delimiter) if pressure else self.sample(token, encoding, delimiter)[1]
        if sheet not in tables:
            raise KeyError(f'В файле нет листа «{sheet}»')
        return tables[sheet].head(31) if pressure else tables[sheet]

    # ---------- редактор листа (import_editor.sheet_editor) ----------
    @staticmethod
    def editor_state(raw: pd.DataFrame, module='auto', header: int | None = None, chosen: str | None = None,
                     pressure=False, fonds=False) -> dict[str, Any]:
        """Значения по умолчанию редактора листа 5.8 при выбранной строке заголовков и типе."""
        if raw.empty or raw.shape[1] == 0:
            return {'empty': True}
        try:
            layout = ({'header': 0, 'mapping': {}, 'wide': False} if fonds else rules.pressure_layout(raw) if pressure
                      else detect_layout(raw.values.tolist(), module))
        except ValueError:
            layout = {'header': 0, 'mapping': {}, 'wide': False, 'module': None}
        detected_header = layout['header']
        top = min(31, len(raw)) - 1
        header = detected_header if header is None else max(-1, min(int(header), top))
        if header != detected_header:
            try:
                layout = (rules.pressure_layout(raw.iloc[header:].reset_index(drop=True)) if pressure and header >= 0
                          else {'mapping': column_map(list(raw.iloc[header])) if header >= 0 else {}, 'wide': False})
            except ValueError:
                layout = {'mapping': {}, 'wide': False}
        labels = list(raw.iloc[header]) if header >= 0 else ['Колонка ' + str(i + 1) for i in range(raw.shape[1])]
        labels = ['' if pd.isna(v) else str(v).strip() for v in labels]
        columns = list(range(len(labels)))
        out: dict[str, Any] = {'empty': False, 'header': header, 'detected_header': detected_header, 'max_header': top,
                               'labels': labels, 'preview': preview_json(raw)}
        if pressure:
            wide = bool(layout.get('wide', False)) and not fonds
            fields = ['date'] if wide else ['well', 'fond'] if fonds else ['date', 'well', 'value']
            out.update(module='pressure_match', effective='pressure_match', wide=wide, wide_allowed=not fonds, fields=fields)
        else:
            suggested = module if module != 'auto' else layout.get('module') or 'auto'
            chosen = chosen or suggested
            effective = layout.get('module') if chosen == 'auto' else chosen
            wide = bool(layout.get('wide', False))
            required = REQUIRED.get(effective, EDITOR_REQUIRED.get(effective, []))
            fields = ['date'] if wide else list(dict.fromkeys(list(layout.get('mapping', {})) + sorted(required)))
            out.update(module=chosen, suggested=suggested, effective=effective, wide=wide,
                       wide_allowed=effective in ('production', 'plan', None), fields=fields)
        mapping = {f: c for f, c in layout.get('mapping', {}).items() if c in columns}
        out['mapping'] = {f: mapping[f] for f in out['fields'] if f in mapping}
        out['layout_mapping'] = mapping
        datecol = mapping.get('date', 0)
        out['wellcols'] = [i for i in columns if i != datecol and labels[i] and not labels[i].startswith('Unnamed:')]
        if fonds:
            import re
            wells = [j for j, v in enumerate(labels) if re.search(r'скваж|well|^скв', v, re.I)]
            types = [j for j, v in enumerate(labels) if re.search(r'тип|type|фонд|fond', v, re.I)]
            out['fond_pairs'] = [[wells[n] if n < len(wells) else 0, types[n] if n < len(types) else min(1, len(columns) - 1)]
                                 for n in range(max(1, len(wells)))]
        else:
            out['fond_pairs'] = []
        return out

    def finish_spec(self, raw: pd.DataFrame, spec: dict, module='auto', pressure=False, fonds=False) -> dict[str, Any]:
        """Разметка листа в форме ``sheet_editor`` 5.8: проверка и итоговый тип данных."""
        if not isinstance(spec, dict):
            raise ParamError('Некорректная разметка листа')
        if not spec.get('enabled', True):
            return {'enabled': False}
        try:
            header = int(spec.get('header', 0))
            mapping = {str(f): int(c) for f, c in (spec.get('mapping') or {}).items() if c is not None and int(c) >= 0}
            wellcols = [int(c) for c in spec.get('wellcols') or []]
            pairs = [[int(a), int(b)] for a, b in spec.get('fond_pairs') or []]
        except (TypeError, ValueError):
            raise ParamError('Некорректная разметка листа') from None
        width = raw.shape[1]
        labels = list(raw.iloc[header]) if 0 <= header < len(raw) else ['Колонка ' + str(i + 1) for i in range(width)]
        labels = ['' if pd.isna(v) else str(v).strip() for v in labels]
        given = spec.get('names') or {}
        names = {str(i): str(given.get(str(i), labels[i]) or '').strip() for i in range(width)}
        wide = bool(spec.get('wide', False))
        problems = []
        if any(c >= width for c in [*mapping.values(), *wellcols, *[c for p in pairs for c in p]]):
            problems.append('Номер колонки за пределами листа.')
        if len(set(mapping.values())) != len(mapping):
            problems.append('Одной колонке назначены разные поля. Исправьте сопоставление.')
        if wide and not wellcols:
            problems.append('Выберите хотя бы одну колонку скважины.')
        if fonds and any(a == b for a, b in pairs):
            problems.append('Скважина и фонд должны быть в разных колонках.')
        if wide:
            mapping = {k: v for k, v in mapping.items() if k == 'date'}
        if pressure:
            detected = 'pressure_match'
        else:
            detected = spec.get('module') or 'auto'
            if detected == 'auto':
                detected = self.editor_state(raw, module, header).get('effective')
            if detected is None:
                if wide:
                    detected = 'production'
                else:
                    semantic = [None] * width
                    for f, c in mapping.items():
                        semantic[c] = f
                    detected = detect_layout([semantic] + raw.iloc[max(0, header + 1):].values.tolist())['module']
        return {'enabled': True, 'valid': not problems, 'module': detected, 'header': header, 'mapping': mapping,
                'wide': wide, 'datecol': mapping.get('date', 0), 'wellcols': wellcols if wide else [], 'names': names,
                'fond_pairs': pairs if fonds else [], 'problems': problems}

    @staticmethod
    def stored(spec: dict) -> dict:
        """Разметка без служебных полей 6 (в профилях и в load_file — формат 5.8)."""
        return {k: v for k, v in spec.items() if k != 'problems'}

    def sheet(self, body: dict) -> dict[str, Any]:
        token, sheet = body.get('token'), body.get('sheet')
        enc, delim = body.get('encoding') or 'auto', body.get('delimiter') or 'auto'
        pressure, fonds = bool(body.get('pressure')), bool(body.get('fonds'))
        raw = self.raw(token, sheet, enc, delim, pressure)
        header = body.get('header')
        state = self.editor_state(raw, body.get('mode') or 'auto', None if header is None else int(header),
                                  body.get('module'), pressure, fonds)
        kind = 'pressure_fond' if fonds else 'pressure' if pressure else 'general'
        state['remembered'] = profiles.find(raw, kind) is not None
        state['sheet'] = sheet
        return state

    def profile(self, body: dict) -> dict[str, Any]:
        """«Запомнить для файлов с такой же шапкой» — общий файл профилей 5.8 (storage/import_profiles.json)."""
        pressure, fonds = bool(body.get('pressure')), bool(body.get('fonds'))
        raw = self.raw(body.get('token'), body.get('sheet'), body.get('encoding') or 'auto', body.get('delimiter') or 'auto', pressure)
        spec = self.finish_spec(raw, body.get('spec'), body.get('mode') or 'auto', pressure, fonds)
        kind = 'pressure_fond' if fonds else 'pressure' if pressure else 'general'
        if not spec.get('enabled') or not spec['valid']:
            raise ParamError('Сначала исправьте разметку листа')
        if body.get('remember'):
            if not profiles.save(raw, self.stored(spec), kind):
                raise ParamError('В строке заголовков меньше двух заполненных ячеек: такую шапку нельзя запомнить.')
        else:
            profiles.forget(raw, self.stored(spec), kind)
        return {'remembered': profiles.find(raw, kind) is not None, 'profiles': profiles.count()}

    # ---------- общий импорт: распознавание ----------
    def inspect(self, body: dict) -> dict[str, Any]:
        mode = body.get('mode') or 'auto'
        if mode not in rules.MODULE_CHOICES:
            raise ParamError('Неизвестный тип таблицы')
        if body.get('view') == 'detailed':
            return {'files': [self._file_info(f, mode) for f in body.get('files') or []]}
        rows, problems, options, errors = self.simple(body.get('files') or [], mode)
        return {'rows': rows, 'problems': problems, 'errors': errors, 'blocked': self._blocked(options, problems, errors),
                'counts': {'files': len(body.get('files') or []), 'sheets': len(rows),
                           'use': sum(r['use'] for r in rows),
                           'unknown': sum(r['status'] == 'Таблица не распознана' for r in rows)}}

    def _file_info(self, f: dict, mode: str) -> dict[str, Any]:
        """Подробный режим (``import_editor.file_editor``): листы файла и признаки книги давлений."""
        item = self.file(f.get('token'))
        out = {'token': item.token, 'name': item.name, 'binary': item.binary, 'error': '', 'sheets': [], 'book': None}
        try:
            fmt, tables = self.sample(item.token, f.get('encoding') or 'auto', f.get('delimiter') or 'auto')
        except Exception as e:
            out['error'] = str(e)
            return out
        names = list(tables)
        out.update(format=fmt, sheets=names)
        fs = next((n for n in names if any(k in n.lower() for k in ('факт', 'hist', 'fact'))), None)
        ms = [n for n in names if any(k in n.lower() for k in ('модел', 'gdm', 'model'))]
        if mode == 'auto' and fs and ms:
            fonds = [n for n in names if 'fond' in n.lower() or 'фонд' in n.lower()]
            out['book'] = {'fact': fs, 'models': [n for n in ms if n != fs],
                           'fonds': [n for n in fonds if n != fs and n not in ms], 'object': Path(item.name).stem}
        return out

    def simple(self, files: list[dict], mode: str):
        """Простой режим (``general_import.simple_options`` и сборка параметров листов в ``render``)."""
        rows, problems, errors, options = [], [], [], {}
        for f in files:
            item = self.file(f.get('token'))
            enc, delim = f.get('encoding') or 'auto', f.get('delimiter') or 'auto'
            choices = f.get('choices') or {}
            try:
                fmt, tables = self.sample(item.token, enc, delim)
            except Exception as e:
                problems.append(item.name + ': ' + str(e))
                continue
            if mode == 'auto' and rules.is_pressure_book(tables):
                rows.append({'token': item.token, 'file': item.name, 'sheet': '(вся книга)', 'use': False, 'module': 'book',
                             'found': None, 'fields': '', 'book': True, 'custom': False, 'binary': item.binary,
                             'status': 'Это книга факта и моделей давлений: загрузите ее в разделе «Данные давлений» ниже'})
                continue
            sheets, any_rows = {}, False
            for sheet, raw in tables.items():
                if sheet == 'Инструкция':
                    continue
                any_rows = True
                found, fields = rules.describe(raw, mode)
                c = choices.get(sheet) or {}
                remembered = profiles.find(raw, 'general')
                override = c['spec'] if 'spec' in c else remembered
                chosen = c.get('module') or found or 'unknown'
                use = bool(c.get('use', found is not None))
                status = 'OK' if found else 'Таблица не распознана'
                if chosen != found and chosen != 'unknown':
                    try:
                        forced = rules.auto_spec(raw, chosen)
                        fields = ', '.join(rules.FIELDS.get(k, k) for k in forced['mapping']) if not forced['wide'] else 'матрица: группы × месяцы' if forced['module'] == 'plan' else 'матрица: даты × скважины'
                        status = 'OK'
                    except ValueError as e:
                        fields, status = '', 'Не подходит: ' + str(e)
                spec = None
                if override is not None:
                    spec = self.finish_spec(raw, override, mode)
                    status = 'По сохраненному профилю' if remembered else 'Настроено вручную'
                    if not spec.get('enabled', True) or spec['valid']:
                        spec = self.stored(spec)
                    else:
                        errors.append(f'{item.name} / {sheet}: ' + ' '.join(spec['problems']))
                        spec = None
                rows.append({'token': item.token, 'file': item.name, 'sheet': sheet, 'use': use, 'module': chosen,
                             'found': found, 'fields': fields, 'status': status, 'book': False,
                             'custom': override is not None, 'binary': item.binary})
                module = c.get('module') or found
                if not use:
                    sheets[sheet] = {'enabled': False}
                elif spec is not None:
                    sheets[sheet] = spec
                elif module and module != found:
                    try:
                        sheets[sheet] = rules.auto_spec(raw, module)
                    except ValueError as e:
                        errors.append(f'{item.name} / {sheet}: {e}')
            if any_rows:
                options[item.token] = {'sheets': sheets, 'encoding': enc, 'delimiter': delim}
        return rows, problems, options, errors

    @staticmethod
    def _blocked(options, problems, errors) -> bool:
        return bool(problems or errors) or not any(
            any(s.get('enabled', True) for s in o['sheets'].values()) or not o['sheets'] for o in options.values())

    def _detailed_options(self, files: list[dict], mode: str):
        options, errors = {}, []
        for f in files:
            item = self.file(f.get('token'))
            enc, delim = f.get('encoding') or 'auto', f.get('delimiter') or 'auto'
            book = f.get('pressure_book')
            if book:
                tables = self.tables(item.token, enc, delim)
                fonds = set(book.get('fonds') or [])
                sheets = {}
                for name in [book.get('fact'), *(book.get('models') or []), *fonds]:
                    if name not in tables:
                        raise ParamError(f'{item.name}: нет листа «{name}»')
                    spec = self.finish_spec(tables[name].head(31), (book.get('sheets') or {}).get(name) or {},
                                            mode, True, name in fonds)
                    if spec.get('enabled') and not spec['valid']:
                        errors.append(f'{item.name} / {name}: ' + ' '.join(spec['problems']))
                    sheets[name] = self.stored(spec)
                duplicate = book.get('duplicate') or 'first'
                if duplicate not in DUPLICATES:
                    raise ParamError('Неизвестное правило повторов')
                options[item.token] = {'sheets': sheets, 'encoding': enc, 'delimiter': delim, 'pressure_book': True,
                                       'fact': book.get('fact'), 'models': list(book.get('models') or []),
                                       'fonds': list(book.get('fonds') or []),
                                       'object': str(book.get('object') or Path(item.name).stem), 'duplicate': duplicate}
                continue
            tables = self.sample(item.token, enc, delim)[1]
            sheets = {}
            for name, spec in (f.get('sheets') or {}).items():
                if name not in tables:
                    raise ParamError(f'{item.name}: нет листа «{name}»')
                spec = self.finish_spec(tables[name], spec, mode)
                if spec.get('enabled') and not spec['valid']:
                    errors.append(f'{item.name} / {name}: ' + ' '.join(spec['problems']))
                sheets[name] = self.stored(spec)
            options[item.token] = {'sheets': sheets, 'encoding': enc, 'delimiter': delim}
        return options, errors

    # ---------- общий импорт: проверка и применение ----------
    def check(self, pid: str, body: dict) -> dict[str, Any]:
        """«Проверить файлы»: те же load_file / parse_pressure_book, пересчёт МПа, журнал замечаний."""
        m = self.projects.manifest(pid)
        mode = body.get('mode') or 'auto'
        kind = body.get('kind') or 'withdrawal'
        punit = body.get('production_unit') or 'м³/сут'
        gunit = body.get('gdi_unit') or 'тыс. м³/сут'
        pressure_unit = body.get('pressure_unit') or 'кгс/см²'
        if mode not in rules.MODULE_CHOICES or kind not in ('withdrawal', 'injection') \
                or punit not in ('м³/сут', 'тыс. м³/сут') or gunit not in ('м³/сут', 'тыс. м³/сут') \
                or pressure_unit not in ('кгс/см²', 'МПа'):
            raise ParamError('Недопустимые параметры импорта')
        files = body.get('files') or []
        if not files:
            raise ParamError('Выберите файлы')
        if body.get('view') == 'detailed':
            options, errors = self._detailed_options(files, mode)
            if errors:
                raise ParamError(' '.join(errors))
        else:
            _, problems, options, errors = self.simple(files, mode)
            if self._blocked(options, problems, errors):
                raise ParamError(' '.join(problems + errors) or 'Нет листов для загрузки: отметьте хотя бы один.')
        parsed, issues, originals, rejected, warnings = {}, [], [], 0, 0
        with tempfile.TemporaryDirectory(prefix='gas_atlas_import_') as staging:
            for i, f in enumerate(files):
                item = self.file(f.get('token'))
                if item.token not in options:
                    continue
                opts = options[item.token]
                path = Path(staging) / str(i) / item.name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.content)
                try:
                    if opts.get('pressure_book'):
                        r = rules.parse_pressure_book(item.content, item.name, opts,
                                                      self.tables(item.token, opts['encoding'], opts['delimiter']))
                    else:
                        r = load_file(path, mode, kind, punit, gunit, sheet_options=opts['sheets'],
                                      encoding=opts['encoding'], delimiter=opts['delimiter'])
                    if pressure_unit == 'МПа':
                        rules.to_kgf(r.frames)
                    for module, frame in r.frames.items():
                        parsed[module] = pd.concat([parsed[module], frame], ignore_index=True) if module in parsed else frame
                    issues.extend(r.issues)
                    rejected += r.rejected
                    warnings += r.warnings
                    if r.frames:
                        originals.append((item.name, item.content))
                except Exception as e:
                    issues.append({'Файл': item.name, 'Лист': '', 'Строка': 0, 'Уровень': 'ошибка', 'Причина': str(e)})
                    rejected += 1
        pending = {'id': uuid.uuid4().hex, 'kind': 'general', 'pid': pid, 'revision': m.get('revision'),
                   'frames': parsed, 'issues': pd.DataFrame(issues, columns=ISSUE_COLUMNS), 'rejected': rejected,
                   'warnings': warnings, 'originals': originals, 'tokens': [f.get('token') for f in files]}
        with self.lock:
            self._keep(self.pending, pending['id'], pending, 8)
        return self._pending_json(pending)

    def _pending_json(self, p: dict) -> dict[str, Any]:
        counts = [{'module': k, 'label': module_label(k), 'rows': len(v)} for k, v in p['frames'].items()]
        out = {'id': p['id'], 'counts': counts, 'rejected': p['rejected'], 'warnings': p['warnings'],
               'policies': [{'value': k, 'label': v} for k, v in POLICIES.items()]}
        out['issues'] = frame_table('issues', 'Журнал проверки', p['issues'].head(200),
                                    note=f'Показаны первые 200 из {len(p["issues"])}. Полный журнал — в выгрузке.'
                                    if len(p['issues']) > 200 else '') if len(p['issues']) else None
        out['issues_count'] = len(p['issues'])
        out['previews'] = [frame_table(k, module_label(k) + ' — предпросмотр', v.head(30),
                                       note=f'Первые 30 из {len(v)} строк.' if len(v) > 30 else '')
                           for k, v in p['frames'].items()]
        out['quality'] = self._quality_json(p)
        return out

    @staticmethod
    def _quality_frame(found: pd.DataFrame) -> pd.DataFrame:
        labels = {'production': 'Эксплуатация', 'gdi': 'ГДИ', 'response': 'Реагирование'}
        return pd.DataFrame({'Набор': found.dataset.map(labels), 'Скважина': found.well,
                             'Дата': pd.to_datetime(found.date, errors='coerce').dt.strftime('%d.%m.%Y').fillna(''), 'Проверка': found.check,
                             'Уровень': found.level, 'Значение': found.value, 'Пояснение': found.details})

    @staticmethod
    def _quality_json(p: dict) -> dict[str, Any]:
        """Отчёт о качестве загруженных данных (``atlas.quality``): находки до сохранения, ничего не исключается само."""
        found = p.get('quality')
        if found is None:
            found = p['quality'] = quality.scan({k: v for k, v in p['frames'].items() if k in quality.CHECKS})
        frame = Imports._quality_frame(found.head(QUALITY_ROWS))
        errors = int(found.level.eq('ошибка').sum())
        note = f'Первые {QUALITY_ROWS} из {len(found)} находок.' if len(found) > QUALITY_ROWS else ''
        return {'errors': errors, 'attention': len(found) - errors, 'by_check': quality.summary(found).to_dict('records'),
                'table': frame_table('quality', 'Находки проверки данных', frame, note=note) if len(found) else None}

    def _take(self, pid: str, pending_id: str, kind: str) -> dict:
        with self.lock:
            p = self.pending.get(pending_id)
        if p is None or p['pid'] != pid or p['kind'] != kind:
            raise KeyError('Результат проверки устарел: проверьте файлы заново')
        return p

    def pending_table(self, pid: str, pending_id: str, table: str) -> Table:
        with self.lock:
            p = self.pending.get(pending_id)
        if p is None or p['pid'] != pid:
            raise KeyError('Результат проверки устарел: проверьте файлы заново')
        if table == 'issues':
            return Table('issues', 'import_issues', p['issues'])
        if table == 'summary' and p.get('summary') is not None:
            return Table('summary', 'Сопоставление', p['summary'])
        if table == 'quality' and p.get('quality') is not None:
            return Table('quality', 'Проверка данных', self._quality_frame(p['quality']))
        if table == 'notes':
            return Table('notes', 'Замечания сопоставления', pd.DataFrame(p.get('notes') or []))
        if table in p.get('frames', {}):
            return Table(table, module_label(table), p['frames'][table].drop(columns=['_point_id'], errors='ignore'))
        raise KeyError('Нет такой таблицы')

    def _raw_frames(self, pid: str, m: dict) -> dict[str, pd.DataFrame]:
        """Таблицы проекта, как ``raw_frames`` страницы 5.8: все таблицы снимка, с ``_point_id``."""
        cache = self.projects._cache(pid, m)
        return {n: cache.raw(n) for n in m.get('tables', {})} if m.get('snapshot') else {}

    def _commit(self, pid, frames, expected, action, details=None, **kw):
        try:
            return self.projects.store.commit(pid, frames, expected=expected, action=action, details=details, **kw)
        except ValueError as e:
            if 'изменен' in str(e):
                raise Conflict('Проект изменён в другом окне (например, в версии 5.8). Проверьте файлы заново.') from None
            raise

    def _undo(self, pid: str) -> dict[str, Any] | None:
        """Копия данных до только что сохранённого импорта: по ней работает «Откатить этот импорт»."""
        versions = self.projects.store.versions(pid)
        before = versions[0]['before'] if versions else None
        return {'snapshot': before} if before else None

    def _keep_originals(self, pid: str, originals) -> list[dict]:
        kept = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, (name, content) in enumerate(originals):
                path = Path(tmp) / str(i) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                kept.append(self.projects.store.keep_original(pid, path))
        return kept

    def apply(self, pid: str, body: dict) -> dict[str, Any]:
        """«Применить загрузку»: merge_frames по выбранному правилу, группы, исходные файлы, журнал 5.8."""
        p = self._take(pid, body.get('pending'), 'general')
        policy = body.get('policy') or 'new'
        if policy not in POLICIES:
            raise ParamError('Неизвестное правило повторов')
        if not p['frames']:
            raise ParamError('Нет строк для загрузки')
        if p['rejected'] and not body.get('accept'):
            raise ParamError('Есть отклонённые строки: подтвердите загрузку корректных строк.')
        m = self.projects.manifest(pid)
        updated, groups, duplicates = rules.merge_import(self._raw_frames(pid, m), m.get('groups', {}), p['frames'], policy)
        originals = m.get('imports', []) + self._keep_originals(pid, p['originals'])
        saved = self._commit(pid, updated, p['revision'], 'Импорт данных', groups=groups, imports=originals)
        self.projects.store.event(pid, 'Результат импорта', {'removed_duplicates': duplicates, 'rejected': p['rejected']})
        self._forget(p)
        return {'message': 'Данные сохранены', 'duplicates': duplicates, 'project': self.projects.summary(saved),
                'undo': self._undo(pid)}

    def _forget(self, p: dict):
        with self.lock:
            self.pending.pop(p['id'], None)
            for token in p.get('tokens', []):
                self.files.pop(token, None)
            for cache in (self.samples, self.full, self.parsed):
                for key in [k for k in cache if k[0] in p.get('tokens', [])]:
                    cache.pop(key, None)

    # ---------- данные давлений (pressure_quick_import) ----------
    def _parsed(self, token, encoding, delimiter) -> dict:
        key = (token, encoding, delimiter)
        with self.lock:
            if key in self.parsed:
                return self.parsed[key]
        item = self.file(token)
        try:
            value = pq.parse_file(item.name, item.content, encoding, delimiter)
        except Exception as e:
            value = {'format': '?', 'sheets': {}, 'error': str(e)}
        with self.lock:
            return self._keep(self.parsed, key, value, 32)

    def _pressure_batch(self, body: dict):
        files, cache, bad = {}, {}, []
        tokens = {}
        for f in body.get('files') or []:
            item = self.file(f.get('token'))
            parsed = self._parsed(item.token, f.get('encoding') or 'auto', f.get('delimiter') or 'auto')
            if parsed.get('error'):
                bad.append(item.name + ': ' + parsed['error'])
                continue
            # Копия записи листа: разметка из «тонкой настройки» не меняет общий кэш.
            parsed = {**parsed, 'sheets': {s: dict(r) for s, r in parsed['sheets'].items()}}
            for sheet, spec in ((body.get('overrides') or {}).get(item.token) or {}).items():
                record = parsed['sheets'].get(sheet)
                if record is None:
                    continue
                fonds = bool(spec.get('fonds'))
                spec = self.stored(self.finish_spec(record['raw'].head(31), spec, 'auto', True, fonds))
                if fonds:
                    record['fond_spec'] = spec
                else:
                    pq.refresh(record, spec)
            files[item.sha] = (item.name, item.content)
            cache[item.sha] = parsed
            tokens[item.sha] = item.token
        choices = {}
        for token, sheets in (body.get('choices') or {}).items():
            sha = self.file(token).sha
            for sheet, c in (sheets or {}).items():
                choices[(sha, sheet)] = {k: v for k, v in c.items() if k in ('use', 'role', 'object', 'scenario', 'shared')}
        return files, cache, tokens, choices, bad

    def pressure_inspect(self, pid: str, body: dict) -> dict[str, Any]:
        m = self.projects.manifest(pid)
        duplicate = body.get('duplicate') or 'first'
        if duplicate not in DUPLICATES:
            raise ParamError('Неизвестное правило повторов')
        files, cache, tokens, choices, bad = self._pressure_batch(body)
        out: dict[str, Any] = {'bad': bad, 'rows': [], 'errors': [], 'warnings': [], 'ready': None,
                               'duplicates': [{'value': k, 'label': v} for k, v in DUPLICATES.items()]}
        if not files:
            return out
        rows = pq.build_rows(files, cache, choices, m['name'])
        out['rows'] = [{**{k: v for k, v in r.items() if k != '_sha'}, 'token': tokens[r['_sha']],
                        'binary': files[r['_sha']][1].startswith(BINARY)} for r in rows]
        out['counts'] = {'files': len(files), 'sheets': len(rows), 'use': sum(r['Исп.'] for r in rows),
                         'objects': len({r['Объект'] for r in rows if r['Исп.'] and r['Роль'] != pq.SKIP})}
        raw = self._raw_frames(pid, m)
        existing = raw.get('pressure_match')
        try:
            data, notes, errors, warnings, summary = pq.assemble(rows, cache, duplicate, existing)
        except Exception as e:
            data, notes, errors, warnings, summary = None, [], [str(e)], [], None
        out.update(errors=errors, warnings=warnings)
        if data is None or errors:
            return out
        pending = {'id': uuid.uuid4().hex, 'kind': 'pressure', 'pid': pid, 'revision': m.get('revision'), 'data': data,
                   'notes': notes, 'summary': summary, 'originals': list(files.values()), 'tokens': list(tokens.values())}
        with self.lock:
            self._keep(self.pending, pending['id'], pending, 8)
        out['ready'] = {
            'id': pending['id'],
            'text': f'Готово к сохранению: {len(data)} пар / неполных пар · объектов {data.object.nunique()} · сценариев {data.scenario.nunique()}',
            'summary': frame_table('summary', 'Сопоставление', summary),
            'notes': frame_table('notes', f'Замечания сопоставления: {len(notes)}', pd.DataFrame(notes), ) if notes else None,
            'existing': None if existing is None else {
                'objects': int(existing.object.nunique()),
                'replaced': sorted(set(existing.object) & set(data.object))},
            'modes': [{'value': k, 'label': v} for k, v in PRESSURE_MODES.items()],
        }
        return out

    def pressure_apply(self, pid: str, body: dict) -> dict[str, Any]:
        """«Сохранить в проект»: как ``pressure_quick_import.render.commit`` в 5.8."""
        p = self._take(pid, body.get('pending'), 'pressure')
        mode = body.get('mode') or 'add'
        if mode not in PRESSURE_MODES:
            raise ParamError('Неизвестный способ сохранения')
        m = self.projects.manifest(pid)
        raw = self._raw_frames(pid, m)
        data = p['data']
        final = data
        if 'pressure_match' in raw and mode == 'add':
            old = raw['pressure_match'].drop(columns=['_point_id'], errors='ignore')
            final = pd.concat([old[~old.object.isin(data.object.unique())], data], ignore_index=True)
        elif 'pressure_match' in raw and mode == 'scenarios':
            old = raw['pressure_match'].drop(columns=['_point_id'], errors='ignore')
            replaced = old.set_index(['object', 'scenario']).index.isin(list(zip(data.object, data.scenario)))
            final = pd.concat([old[~replaced], data], ignore_index=True)
        frames = dict(raw)
        frames['pressure_match'] = final
        label = PRESSURE_MODES[mode] if 'pressure_match' in raw else PRESSURE_MODES['add']
        saved = self._commit(pid, frames, p['revision'], 'Импорт кроссплота давлений',
                             details={'rows': len(data), 'files': len(p['originals']), 'mode': label, 'diagnostics': p['notes']})
        self._keep_originals(pid, p['originals'])
        self._forget(p)
        return {'message': f'Сохранено: {len(data)} строк, объектов {data.object.nunique()}',
                'project': self.projects.summary(saved), 'undo': self._undo(pid)}

    # ---------- демонстрационные варианты кроссплота (app/core/pressure_demo.py) ----------
    @staticmethod
    def pressure_demo_variants() -> list[dict[str, Any]]:
        return pressure_demo.variants()

    @staticmethod
    def pressure_demo_book(variant: str, name: str) -> bytes:
        for book, content in pressure_demo.books(variant):
            if book == name:
                return content
        raise KeyError('Нет такой книги')

    def pressure_demo_apply(self, pid: str, body: dict) -> dict[str, Any]:
        """Вариант сразу в проект — только в демонстрационном: рабочие проекты не заполняются выдуманными замерами."""
        m = self.projects.manifest(pid)
        if not m.get('demo'):
            raise ParamError('Демонстрационные варианты загружаются только в демонстрационный проект.')
        variant = body.get('variant') or pressure_demo.DEFAULT
        label = {v['value']: v['label'] for v in pressure_demo.variants()}.get(variant)
        if label is None:
            raise ParamError('Нет такого демонстрационного варианта')
        frames = self._raw_frames(pid, m)
        frames['pressure_match'] = pressure_demo.frame(variant)
        saved = self._commit(pid, frames, m.get('revision'), 'Демонстрационные данные давлений', details={'variant': label})
        return {'message': f'Загружен вариант «{label}»', 'project': self.projects.summary(saved)}

    # ---------- шаблоны и примеры ----------
    @staticmethod
    def templates() -> list[dict[str, str]]:
        out = [{'name': n, 'kind': 'template'} for n in input_templates()]
        out += [{'name': p.name, 'kind': 'example'} for p in sorted(EXAMPLES.glob('*')) if p.suffix in ('.csv', '.xlsx', '.txt')]
        return out

    @staticmethod
    def template(name: str) -> bytes:
        made = input_templates()
        if name in made:
            return made[name]
        path = EXAMPLES / Path(name).name
        if path.suffix in ('.csv', '.xlsx', '.txt') and path.is_file():
            return path.read_bytes()
        raise KeyError('Нет такого шаблона')

    @staticmethod
    def options() -> dict[str, Any]:
        """Списки для формы: типы таблиц, поля сопоставления (подписи 5.8)."""
        from app.core.loader import ALIASES
        return {'types': [{'value': v, 'label': rules.type_label(v)} for v in ['auto'] + rules.MODULE_CHOICES[1:]],
                'sheet_types': [{'value': v, 'label': 'Автоопределение' if v == 'auto' else module_label(v)}
                                for v in rules.MODULE_CHOICES],
                'fields': [{'value': f, 'label': rules.FIELDS[f]} for f in ALIASES],
                'pressure_fields': {f: rules.FIELDS[f] for f in ('date', 'well', 'value', 'fond')},
                'roles': pq.ROLES, 'duplicates': [{'value': k, 'label': v} for k, v in DUPLICATES.items()]}

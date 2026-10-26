"""Папка проекта: список файлов рядом с данными, роли файлов, манифест и отчёт проверки.

Только список: файлы в папке не читаются и не загружаются (загрузку делает раздел «Импорт данных»).
Манифест — файл ``gas_atlas_folder.json`` в самой папке: какой файл чем является (расходы, давления, ГДИ, вода)
и нормирована ли база расходов. Отчёт проверки Базы ПХГ — файл ``<имя результата>.qc.json`` рядом с результатом
(формат ``pxg_core/qc.py``, ``Report.to_dict``).

| Запрос | Что делает |
|---|---|
| `POST /api/folder/scan` `{folder}` | список файлов папки: роль (из манифеста или по имени), известные результаты Базы ПХГ, отчёт проверки |
| `POST /api/folder/manifest` `{folder, files: {имя: {role, normalized}}}` | записать роли файлов в манифест |
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .api import error
from . import folder_check, workspace_folders
from .engine.core import ggh_import as ggh
from .engine.core import gis_import, import_rules, tabular, water_monthly_import
from .imports import Imports, base_book
from .api_projects import internal_error_text
from .contract import ParamError
from .imports import POLICIES
from .projects import Conflict

log = logging.getLogger(__name__)

MANIFEST = 'gas_atlas_folder.json'
LOADS = 'folder_loads.json'          # в папке проекта: что и когда загружено из папки (отпечаток файла)
QC_SUFFIX = '.qc.json'
EXTENSIONS = ('.xlsx', '.xlsm', '.xls', '.csv', '.txt')
ROLES = {
    'production': 'Расходы (отбор/закачка)',
    'pressure': 'Давления',
    'gdi': 'ГДИ',
    'water': 'Вода',
    'elpro': 'ЭЛПРО (параметры работы ГСП)',
    'gas': 'БД по учету газа',
    'gis': 'База ГИС (пачки, интервалы, замеры)',
    'geo': 'Положение и перфорация скважин (X, Y, альтитуды, перфорация)',
    'ggh': 'Газогидрохимия (ГГХ)',
    'other': 'Прочее',
}
# Результаты Базы ПХГ (all_scripts, pxg_base): имя → роль, нормирована ли база, что это. Порядок важен: длинные раньше.
KNOWN_RESULTS = (
    ('бд расходы нормированная', 'production', True, 'База расходов, нормированная на узел учёта'),
    ('бд расходы', 'production', False, 'База расходов (База ПХГ)'),
    ('сводка закачка отбор', 'production', False, 'База расходов («Создание базы данных расходов» Базы ПХГ)'),
    # Сырая база замеров (Руст, Рпл без приведения): Атлас берёт приведённое давление из «Пересчёт_давлений».
    ('бд давлений по замерам', None, False, 'База давлений по замерам (База ПХГ): для Атласа загрузите «Пересчёт_давлений»'),
    ('пересчёт давлений', 'pressure', False, 'Пересчёт давлений (База ПХГ): приведённое Рпл по скважинам'),
    ('пересчет давлений', 'pressure', False, 'Пересчёт давлений (База ПХГ): приведённое Рпл по скважинам'),
    ('бд давл', 'pressure', False, 'База давлений (База ПХГ)'),
    ('бд гди', 'gdi', False, 'База ГДИ (База ПХГ)'),
    ('бд замеров воды', 'water', False, 'База замеров воды (База ПХГ)'),
    ('бд межколонки', 'other', False, 'База межколонок (База ПХГ)'),
    ('учёт газа отбор вынос воды', 'water', False, 'Учёт газа по отбору с выносом воды (База ПХГ)'),
    # Роль не угадываем: файл показываем как известный результат, роль назначает пользователь.
    ('бд по учету газа', 'gas', False, 'БД по учету газа (База ПХГ): суточные отбор и закачка по объекту, вынос воды'),
    ('бд элпро', 'elpro', False, 'База ЭЛПРО (База ПХГ) или месячные файлы ЭЛПРО'),
    ('daily well data', None, False, 'Суточные данные по скважинам (База ПХГ), роль назначьте вручную'),
    ('гис свод', 'gis', False, 'База ГИС: книга «ГИС_свод» (База ПХГ)'),
    ('gis packs', 'gis', False, 'База ГИС: пачки (База ПХГ)'),
    ('gis intervals', 'gis', False, 'База ГИС: интервалы (База ПХГ)'),
    ('gis observations', 'gis', False, 'База ГИС: замеры (База ПХГ)'),
    ('гис ', 'gis', False, 'Данные ГИС (База ПХГ)'),
    ('база шахматка', 'production', False, 'База шахматка (База ПХГ): отбор и закачка'),
    # Отчёты проверок Базы ПХГ: не данные, в проект не грузятся (иначе «Часы_…_расход_…» ушёл бы в расходы).
    ('часы ненулевые расход нулевой', None, False, 'Отчёт проверки Базы ПХГ (часы и расход не согласованы), не данные'),
    ('журнал нормировки', None, False, 'Журнал нормировки на узел учёта (База ПХГ), не данные'),
    ('даты к проверке', None, False, 'Даты к проверке (База ПХГ), не данные'),
    ('журнал поправки по пзрг', None, False, 'Журнал поправок по ПЗРГ (schedule, База ПХГ), не данные'),
    ('невязка по суткам', None, False, 'Невязка по суткам (schedule, База ПХГ), не данные'),
    ('гис разбор', None, False, 'Разбор ГИС по листам (База ПХГ), для Атласа берите «ГИС_свод»'),
    ('gis bottom', None, False, 'Текущий забой по ГИС (База ПХГ): в Атлас не грузится'),
    ('отчет копирования', None, False, 'Отчёт копирования файлов (База ПХГ), не данные'),
    ('отчёт копирования', None, False, 'Отчёт копирования файлов (База ПХГ), не данные'),
    ('include ', 'pressure', False, 'Include-таблица давлений для tNavigator (База ПХГ): скважина, дата, давление, бар'),
)
# Нормированная база — итог Базы ПХГ: рядом с ней исходная база расходов роли не получает, иначе сутки загрузятся дважды.
SUPERSEDED = 'Есть нормированная база расходов: эта исходная не загружается (роль можно назначить вручную)'
# Роль по словам в имени, если файл не известный результат и манифеста нет.
NAME_HINTS = (('глубин', 'geo'), ('перфорац', 'geo'), ('координат', 'geo'), ('альтитуд', 'geo'), ('xy', 'geo'), ('tnav', 'geo'), ('расход', 'production'), ('давлен', 'pressure'), ('гди', 'gdi'), ('вода', 'water'), ('воды', 'water'))


def _norm(name: str) -> str:
    """Имя для сравнения: регистр, «_», «-» и пробелы не различаются."""
    return re.sub(r'[\s_\-]+', ' ', name.lower()).strip()


def _known(name: str) -> dict[str, Any] | None:
    key = _norm(Path(name).stem)
    for prefix, role, normalized, label in KNOWN_RESULTS:
        if key.startswith(prefix):
            return {'role': role, 'normalized': normalized, 'label': label}
    return None


SNIFF_LIMIT = 80 * 1024 * 1024          # файлы крупнее не открываются для распознавания: роль по имени или вручную
_SNIFFED: dict[tuple, dict[str, Any] | None] = {}
BASE_ROLES = (('база ЭЛПРО', 'elpro'), ('«БД по учету газа»', 'gas'), ('таблица «База ГИС»', 'gis'),
              ('файл положения', 'geo'), ('замеры воды', 'water'))
GGH_REASON = 'лист с шапкой ГГХ: «№№ скв.» и «Дата отбора»'
# Признаки по листам и колонкам для файлов с любым именем: (роль, название, листы, колонки хотя бы на одном листе).
# Роль None — файл узнан, но в Атлас не грузится (отчёт или сырая база): причина всё равно показывается.
SIGNATURES = (
    (None, 'База давлений по замерам (сырые Руст и Рпл): для Атласа загрузите «Пересчёт_давлений»', {'Данные'}, {'Скважина', 'Дата', 'Категория', 'Руст'}),
    ('pressure', 'Пересчёт давлений или include-таблица: скважина, дата, давление', set(), {'Скважина', 'Дата', 'Давление, бар'}),
    ('pressure', 'Пересчёт давлений: приведённое Рпл по скважинам', {'Пересчёт'}, set()),
    ('production', 'База расходов Базы ПХГ (листы «Отборы» и «Закачка»)', {'Отборы', 'Закачка'}, set()),
    (None, 'Отчёт о несоответствиях часов и расхода (Базы ПХГ), не данные', {'Несоответствия'}, set()),
    (None, 'Журнал нормировки на узел учёта (Базы ПХГ), не данные', {'Параметры', 'Журнал'}, set()),
)
MODULE_ROLES = {'production': 'production', 'gdi': 'gdi', 'water': 'water', 'object_pressure': 'pressure', 'pressure': 'pressure'}


def sniff(path: Path) -> dict[str, Any] | None:
    """Тип файла по содержимому: листы и заголовки первых строк. Результат — подсказка с причиной
    ``{'role', 'reason'}``; пусто — по содержимому не узнан. Кэш по размеру и времени изменения."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_size, int(stat.st_mtime))
    if key in _SNIFFED:
        return _SNIFFED[key]
    out = None
    if stat.st_size <= SNIFF_LIMIT:
        try:
            out = _sniff_tables(path.name, tabular.read_content(path.read_bytes(), path.name, 31)[1])
        except Exception:                    # noqa: BLE001 — не читается: остаётся имя файла
            log.info('Файл %s не открыт для распознавания', path.name, exc_info=True)
    if len(_SNIFFED) > 2000:
        _SNIFFED.clear()
    _SNIFFED[key] = out
    return out


def _sniff_tables(name: str, tables: dict[str, Any]) -> dict[str, Any] | None:
    sheets = {str(k).strip() for k in tables}
    heads = [{str(v).strip() for v in raw.iloc[0].tolist()} for raw in tables.values() if raw is not None and not raw.empty]
    special_book = base_book(tables, name)
    if not special_book:
        for role, label, need_sheets, need_cols in SIGNATURES:
            if (need_sheets or need_cols) and need_sheets <= sheets and (not need_cols or any(need_cols <= h for h in heads)):
                found = ('листы ' + ', '.join(f'«{x}»' for x in sorted(need_sheets))) if need_sheets else ''
                cols = ('колонки ' + ', '.join(sorted(need_cols))) if need_cols else ''
                return {'role': role, 'reason': f'Содержимое: {label} ({"; ".join(x for x in (found, cols) if x)})'}
    special = base_book(tables, name)
    if not special and any(_looks_ggh(raw) for raw in tables.values()):
        return {'role': 'ggh', 'reason': 'Содержимое: ' + GGH_REASON}
    if special:
        role = next(r for label, r in BASE_ROLES if special.startswith(label))
        if role == 'gis':
            return {'role': 'gis', 'reason': 'Листы и заголовки как в выгрузке «Базы ГИС»: ' + _gis_parts(tables)}
        reasons = {'elpro': 'лист «Данные» с колонками Дата, Режим, ГСП, Скважина, Y круг', 'gas': 'лист «БД» с колонками Режим, Дата, Файл, Лист',
                   'geo': 'колонки положения и перфорации скважин', 'water': 'замеры воды по месяцам'}
        return {'role': role, 'reason': f'Содержимое: {reasons[role]}'}
    found = {}
    for sheet, raw in tables.items():
        if raw is None or raw.empty or sheet == 'Инструкция':
            continue
        module, fields = import_rules.describe(raw, 'auto')
        if module in MODULE_ROLES:
            found.setdefault(module, (sheet, fields))
    if len(found) == 1:
        module, (sheet, fields) = next(iter(found.items()))
        return {'role': MODULE_ROLES[module], 'reason': f'Содержимое: лист «{sheet}» — {import_rules.type_label(module)} ({fields})'}
    return None


def _looks_ggh(raw: Any) -> bool:
    """Лист ГГХ: в строке шапки скважина, дата и ещё минимум два признака пробы (газ, горизонт, состав): одной «Скважина + Дата» мало."""
    if raw is None or raw.empty:
        return False
    row = ggh.find_header(raw)
    if row is None:
        return False
    fields = {ggh._field(v) for v in raw.iloc[row].tolist()}
    return len(fields - {None, 'well', 'date'}) >= 2


def _gis_parts(tables: dict[str, Any]) -> str:
    parts = []
    for sheet, raw in tables.items():
        if raw is not None and not raw.empty:
            kind = gis_import.detect(raw.iloc[0].tolist())
            if kind:
                parts.append(f'лист «{sheet}» — {gis_import.LABELS[kind]}')
    return ', '.join(parts[:3]) or 'таблица ГИС'


def _role_by_name(name: str) -> str | None:
    key = _norm(name)
    words = set(key.split())
    return next((role for word, role in NAME_HINTS if any(w.startswith(word) for w in words)), None)


def _auto_role(path: Path, known: dict[str, Any] | None) -> tuple[str | None, str, str]:
    """Роль без манифеста: известное имя результата Базы ПХГ, затем содержимое файла, затем слова в имени.
    Возвращает роль, источник и причину — её видит пользователь и может сменить роль."""
    if known:                       # известное имя результата Базы ПХГ надёжнее: отчёты проверок так и остаются «не данными»
        return known['role'], 'name', f'По имени файла: {known["label"]}'
    sniffed = sniff(path)
    if sniffed:
        return sniffed['role'], 'content', sniffed['reason']
    role = _role_by_name(path.name)
    return role, 'name', 'По слову в имени файла (содержимое не узнано)' if role else ''


def registry() -> list[dict[str, Any]]:
    """Что Атлас узнаёт: известные имена результатов Базы ПХГ и признаки по содержимому (показывается в окне)."""
    names = [{'by': 'name', 'match': prefix, 'role': role, 'label': label} for prefix, role, _, label in KNOWN_RESULTS]
    signs = [{'by': 'content', 'match': ' + '.join(sorted(sheets) + sorted(cols)), 'role': role, 'label': label}
             for role, label, sheets, cols in SIGNATURES]
    books = [{'by': 'content', 'match': match, 'role': role, 'label': label} for match, role, label in (
        ('лист «Данные»: Дата, Режим, ГСП, Скважина, Y круг', 'elpro', 'База ЭЛПРО'),
        ('лист «БД»: Режим, Дата, Файл, Лист', 'gas', 'БД по учету газа'),
        ('листы «Свод», «Интервалы», «Замеры» или csv gis_*', 'gis', 'База ГИС'))]
    return books + signs + names


def _folder(raw: Any) -> Path:
    text = str(raw or '').strip().strip('"').strip()
    path = Path(text) if text else None
    if path is None or not path.is_dir():
        raise ParamError('Папка не найдена: проверьте путь или выберите папку заново.')
    return path


def read_manifest(folder: Path) -> tuple[dict[str, Any], str]:
    """Манифест папки и текст ошибки (если файл повреждён, он не трогается — работаем как без манифеста)."""
    path = folder / MANIFEST
    if not path.exists():
        return {}, ''
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        files = data.get('files') if isinstance(data, dict) else None
        return (files if isinstance(files, dict) else {}), ''
    except (OSError, ValueError):
        return {}, f'Манифест {MANIFEST} не читается: роли определены по именам файлов.'


def _qc_summary(folder: Path, name: str) -> dict[str, Any] | None:
    path = folder / (Path(name).stem + QC_SUFFIX)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'file': path.name, 'error': 'Отчёт проверки не читается'}
    if not isinstance(data, dict):
        return {'file': path.name, 'error': 'Отчёт проверки не читается'}
    return {'file': path.name, 'title': data.get('title', ''), 'summary': data.get('summary', ''),
            'counts': data.get('counts', {}), 'created': dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='minutes')}


def fingerprint(path: Path) -> dict[str, int]:
    """Отпечаток файла: размер и время изменения. Содержимое не читается (файлы бывают по сотням МБ)."""
    stat = path.stat()
    return {'size': stat.st_size, 'mtime': int(stat.st_mtime)}


def read_loads(project_dir: Path) -> dict[str, Any]:
    path = project_dir / LOADS
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data.get('files', {}) if isinstance(data, dict) and isinstance(data.get('files'), dict) else {}
    except (OSError, ValueError):
        log.warning('Не читается %s: все файлы будут показаны как «не загружены»', path)
        return {}


def write_loads(project_dir: Path, files: dict[str, Any]) -> None:
    path = project_dir / LOADS
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps({'format': 1, 'files': files}, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)


def _load_state(path: Path, loaded: dict[str, Any] | None) -> str | None:
    if loaded is None:
        return None
    entry = loaded.get(path.name)
    if not isinstance(entry, dict):
        return 'not_loaded'
    now = fingerprint(path)
    return 'loaded' if (entry.get('size'), entry.get('mtime')) == (now['size'], now['mtime']) else 'changed'


def scan(raw_folder: Any, loaded: dict[str, Any] | None = None) -> dict[str, Any]:
    """Список файлов папки. Ничего не открывается, кроме манифеста и отчётов проверки.
    ``loaded`` — что уже загружено в проект (из ``folder_loads.json``): тогда у каждого файла статус загрузки."""
    folder = _folder(raw_folder)
    manifest, warning = read_manifest(folder)
    paths = [p for p in sorted(folder.iterdir(), key=lambda p: p.name.lower())
             if p.is_file() and not p.name.startswith('~$') and p.suffix.lower() in EXTENSIONS]
    has_normalized = any((_known(p.name) or {}).get('normalized') for p in paths)
    files = []
    for path in paths:
        name = path.name
        known = _known(name)
        if known and has_normalized and known['role'] == 'production' and not known['normalized']:
            known = dict(known, role=None, label=SUPERSEDED)
        entry = manifest.get(name) if isinstance(manifest.get(name), dict) else {}
        reason = ''
        if 'role' in entry and (entry['role'] is None or (isinstance(entry['role'], str) and entry['role'] in ROLES)):
            role, source = entry['role'], 'manifest'     # явное «не назначено» сохраняется и не подменяется именем
            reason = 'Назначено вручную'
            sniffed = sniff(path)
            if sniffed and sniffed['role'] != role:
                reason += f'. По содержимому файл похож на «{ROLES[sniffed["role"]]}»'
            
        else:
            role, source, reason = _auto_role(path, known)
        normalized = entry['normalized'] if isinstance(entry.get('normalized'), bool) else bool(known and known['normalized'])
        stat = path.stat()
        files.append({'name': name, 'size': stat.st_size,
                      'modified': dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='minutes'),
                      'role': role, 'role_label': ROLES.get(role, ''), 'role_source': source if role else '', 'role_reason': reason,
                      'normalized': normalized, 'known': known['label'] if known else '',
                      'qc': _qc_summary(folder, name), 'load': _load_state(path, loaded)})
    if not files and not warning:
        warning = 'В папке нет таблиц Excel или CSV: положите файлы данных или выберите другую папку.'
    return {'folder': str(folder), 'manifest': bool(manifest) or (folder / MANIFEST).exists(), 'warning': warning,
            'roles': [{'value': k, 'label': v} for k, v in ROLES.items()], 'files': files, 'registry': registry()}


def save_manifest(raw_folder: Any, files: Any, loaded: dict[str, Any] | None = None) -> dict[str, Any]:
    """Записать роли и признак нормировки. Только файлы этой папки; неизвестная роль — ошибка."""
    folder = _folder(raw_folder)
    if not isinstance(files, dict):
        raise ParamError('Укажите роли файлов')
    manifest, warning = read_manifest(folder)
    if warning:
        raise ParamError(warning + ' Исправьте или удалите файл, затем сохраните роли.')
    names = {p.name for p in folder.iterdir() if p.is_file()}
    for name, value in files.items():
        if name not in names or Path(name).name != name or Path(name).suffix.lower() not in EXTENSIONS:
            raise ParamError(f'Файла «{name}» нет в папке проекта')
        if not isinstance(value, dict):
            raise ParamError(f'«{name}»: ожидаются роль и признак нормировки')
        role = value.get('role')
        if role is not None and not (isinstance(role, str) and role in ROLES):
            raise ParamError(f'«{name}»: неизвестная роль {role!r}')
        if 'normalized' in value and not isinstance(value['normalized'], bool):
            raise ParamError(f'«{name}»: признак нормировки — да или нет')
        entry = dict(manifest.get(name) or {})
        if 'role' in value:
            entry['role'] = role                 # None — явно «не назначено»
        if 'normalized' in value:
            entry['normalized'] = value['normalized']
        manifest[name] = entry
    data = {'format': 1, 'updated': dt.datetime.now().isoformat(timespec='seconds'), 'files': manifest}
    path = folder / MANIFEST
    tmp = path.with_suffix('.json.tmp')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        log.exception('Не записан манифест %s', path)
        raise ParamError('Нет прав на запись в папку проекта: манифест не сохранён.') from None
    return scan(str(folder), loaded)


def load_files(imports, projects, pid: str, raw_folder: Any, names: Any, policy: str, rejected: str = 'skip') -> dict[str, Any]:
    """Загрузить файлы папки в проект через общий импорт (check → apply), по одному файлу.
    Файл с отклонёнными строками не грузится автоматически: он получает статус «нужно внимание» и идёт вручную."""
    folder = _folder(raw_folder)
    if not isinstance(names, list) or not names:
        raise ParamError('Выберите файлы для загрузки')
    if policy not in POLICIES:
        raise ParamError('Неизвестное правило повторов')
    if rejected not in REJECTED:
        raise ParamError('Неизвестное правило для отклонённых строк')
    project_dir = projects.store.path(pid)
    m = projects.manifest(pid)                  # проверка, что проект есть
    loads = read_loads(project_dir)
    names_ok = {p.name for p in folder.iterdir() if p.is_file()}
    results = []
    warning = ''
    roles = {f['name']: f['role'] for f in scan(str(folder))['files']}
    try:
        for name in names:
            results.append(_load_one(imports, pid, folder, name, names_ok, policy, loads, roles.get(name), rejected))
        # откат всей пачки: снимок до первого применённого файла (по нему отменяются все файлы пачки)
        batch = next((r['undo'] for r in results if r.get('undo')), '')
        for r in results:
            if r.get('undo') and r['name'] in loads:
                loads[r['name']]['batch'] = batch
    finally:
        # записываем даже при сбое в середине: уже применённые файлы должны остаться отмеченными
        try:
            write_loads(project_dir, loads)
        except OSError:
            log.exception('Не записан %s в %s', LOADS, project_dir)
            warning = 'Данные загружены, но отметки загрузки в папке не записаны (нет прав на запись в папку проекта).'
    return {'results': results, 'folder': scan(str(folder), loads), 'project': pid, 'revision': m.get('revision'),
            'warning': warning, 'undo': batch}


REJECTED = ('skip', 'accept', 'keep')      # файл с отклонёнными строками: не грузить / только корректные / все, плохие исключены


def _load_ggh(imports, pid: str, name: str, content: bytes, policy: str) -> dict[str, Any]:
    up = imports.upload(name, content)
    if up['error']:
        raise ParamError(up['error'])
    shown = imports.ggh_inspect(pid, {'token': up['token']})
    if not shown['ready']:
        raise ParamError(shown['error'] or 'В файле нет данных ГГХ')
    return imports.ggh_apply(pid, {'pending': shown['ready']['id'], 'mode': 'merge'})


def _monthly_water(name: str, path: Path) -> bool:
    """Замеры воды за месяц (старый формат Карт ГСП): такой файл грузится своим разбором, остальные «вода» — как раньше."""
    try:
        tables = tabular.read_content(path.read_bytes(), name, 31)[1]
    except Exception:
        return False
    return water_monthly_import.looks_like(tables, name)


def _load_one(imports, pid: str, folder: Path, name: str, names_ok: set, policy: str, loads: dict, role: str | None = None, rejected: str = 'skip') -> dict[str, Any]:
    """Один файл: upload → check → apply (ЭЛПРО — свой разбор). Ошибка одного файла не обрывает остальные."""
    if name not in names_ok or Path(name).name != name or Path(name).suffix.lower() not in EXTENSIONS:
        return {'name': name, 'status': 'error', 'message': 'Файла нет в папке или он не таблица'}
    path = folder / name
    try:
        if role == 'elpro':
            applied = imports.elpro_load(pid, name, path.read_bytes(), policy)
        elif role == 'gas':
            applied = imports.gas_db_load(pid, name, path.read_bytes(), policy)
        elif role == 'gis':
            applied = imports.gis_load(pid, name, path.read_bytes(), policy)
        elif role == 'geo':
            applied = imports.geo_load(pid, name, path.read_bytes(), policy)
        elif role == 'ggh':
            applied = _load_ggh(imports, pid, name, path.read_bytes(), policy)
        elif role == 'water' and _monthly_water(name, path):
            applied = imports.water_monthly_load(pid, name, path.read_bytes(), policy)
        else:
            up = imports.upload(name, path.read_bytes())
            if up['error']:
                raise ParamError(up['error'])
            pending = imports.check(pid, {'files': [{'token': up['token']}], 'mode': 'auto', 'view': 'simple'})
            if pending['rejected'] and rejected == 'skip':
                imports.discard(pending['id'])
                return {'name': name, 'status': 'attention',
                        'message': f"Отклонённых строк: {pending['rejected']}. Загрузите этот файл вручную в «Импорт данных» "
                                   'или выберите, что делать с такими строками (загрузить корректные / загрузить все, плохие исключить).'}
            applied = imports.apply(pid, {'pending': pending['id'], 'policy': policy, 'accept': True,
                                          'keep_rejected': rejected == 'keep'})
        undo = (applied.get('undo') or {}).get('snapshot', '')
        loads[name] = dict(fingerprint(path), loaded_at=dt.datetime.now().isoformat(timespec='seconds'), message=applied['message'], undo=undo)
        return {'name': name, 'status': 'loaded', 'message': applied['message'], 'undo': undo}
    except ParamError as e:
        return {'name': name, 'status': 'error', 'message': str(e)}
    except (KeyError, Conflict) as e:
        message = str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)
        return {'name': name, 'status': 'error', 'message': message or 'Загрузка прервана: данные проекта изменились, повторите.'}
    except OSError as e:
        return {'name': name, 'status': 'error', 'message': f'Файл не прочитан: {e.strerror or e}'}
    except Exception:
        log.exception('Сбой загрузки %s из папки', name)
        return {'name': name, 'status': 'error', 'message': 'Файл не загружен: внутренняя ошибка. Подробности — в журнале.'}


def routes(projects) -> list[Route]:
    imports = Imports(projects)

    def wrap(work):
        async def handler(request: Request):
            try:
                body = await request.json()
            except ValueError:
                return error(400, 'Тело запроса должно быть JSON')
            if not isinstance(body, dict):
                return error(400, 'Тело запроса должно быть объектом JSON')
            try:
                out = await run_in_threadpool(work, request, body)
            except ParamError as e:
                return error(400, str(e))
            except KeyError as e:
                return error(404, str(e.args[0]) if e.args else 'Не найдено')
            except Exception:
                log.exception('Сбой запроса %s', request.url.path)
                return error(500, internal_error_text())
            return out if isinstance(out, Response) else JSONResponse(out)
        return handler

    def undo_batch(request, body):
        """«Откатить загрузку из папки»: данные возвращаются к снимку до пачки, файлы пачки снова «не загружены»."""
        pid = request.path_params['pid']
        projects.manifest(pid)
        snapshot = str(body.get('snapshot') or '')
        if not snapshot:
            raise ParamError('Нет снимка для отката')
        project_dir = projects.store.path(pid)
        loads = read_loads(project_dir)
        saved = projects.store.rollback(pid, snapshot, _revision(body))
        for name in [n for n, v in loads.items() if v.get('batch') == snapshot]:
            del loads[name]
        try:
            write_loads(project_dir, loads)
        except OSError:
            log.exception('Не записан %s в %s', LOADS, project_dir)
        return projects.summary(saved)

    def _revision(body):
        value = body.get('revision')
        return int(value) if isinstance(value, (int, float)) else None

    def _loads_of(pid_raw):
        if not pid_raw:
            return None
        pid = str(pid_raw)
        projects.manifest(pid)                  # нет проекта — KeyError → 404
        return read_loads(projects.store.path(pid))

    def scan_route(request, body):
        return scan(body.get('folder'), _loads_of(body.get('project')))

    async def project_state(request: Request):
        return JSONResponse(workspace_folders.state())

    return [
        Route('/api/folder/project', project_state, methods=['GET']),
        Route('/api/folder/scan', wrap(scan_route), methods=['POST']),
        Route('/api/folder/manifest', wrap(lambda r, b: save_manifest(b.get('folder'), b.get('files'), _loads_of(b.get('project')))), methods=['POST']),
        Route('/api/projects/{pid}/folder/load', wrap(lambda r, b: load_files(
            imports, projects, r.path_params['pid'], b.get('folder'), b.get('files'), b.get('policy') or 'new',
            b.get('rejected') or 'skip')), methods=['POST']),
        Route('/api/projects/{pid}/folder/check', wrap(lambda r, b: folder_check.check_files(
            imports, projects, r.path_params['pid'], b.get('folder'), b.get('files'))), methods=['POST']),
        Route('/api/projects/{pid}/folder/undo', wrap(undo_batch), methods=['POST']),
    ]

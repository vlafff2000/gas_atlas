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
from .api_projects import internal_error_text
from .contract import ParamError

log = logging.getLogger(__name__)

MANIFEST = 'gas_atlas_folder.json'
QC_SUFFIX = '.qc.json'
EXTENSIONS = ('.xlsx', '.xlsm', '.xls', '.csv', '.txt')
ROLES = {
    'production': 'Расходы (отбор/закачка)',
    'pressure': 'Давления',
    'gdi': 'ГДИ',
    'water': 'Вода',
    'other': 'Прочее',
}
# Результаты Базы ПХГ (all_scripts, pxg_base): имя → роль, нормирована ли база, что это. Порядок важен: длинные раньше.
KNOWN_RESULTS = (
    ('бд расходы нормированная', 'production', True, 'База расходов, нормированная на узел учёта'),
    ('бд расходы', 'production', False, 'База расходов (База ПХГ)'),
    ('бд давл', 'pressure', False, 'База давлений (База ПХГ)'),
    ('бд гди', 'gdi', False, 'База ГДИ (База ПХГ)'),
    ('бд замеров воды', 'water', False, 'База замеров воды (База ПХГ)'),
    ('бд межколонки', 'other', False, 'База межколонок (База ПХГ)'),
)
# Роль по словам в имени, если файл не известный результат и манифеста нет.
NAME_HINTS = (('расход', 'production'), ('давлен', 'pressure'), ('гди', 'gdi'), ('вода', 'water'), ('воды', 'water'))


def _norm(name: str) -> str:
    """Имя для сравнения: регистр, «_», «-» и пробелы не различаются."""
    return re.sub(r'[\s_\-]+', ' ', name.lower()).strip()


def _known(name: str) -> dict[str, Any] | None:
    key = _norm(Path(name).stem)
    for prefix, role, normalized, label in KNOWN_RESULTS:
        if key.startswith(prefix):
            return {'role': role, 'normalized': normalized, 'label': label}
    return None


def _role_by_name(name: str) -> str | None:
    key = _norm(name)
    words = set(key.split())
    return next((role for word, role in NAME_HINTS if any(w.startswith(word) for w in words)), None)


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


def scan(raw_folder: Any) -> dict[str, Any]:
    """Список файлов папки. Ничего не открывается, кроме манифеста и отчётов проверки."""
    folder = _folder(raw_folder)
    manifest, warning = read_manifest(folder)
    files = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        name = path.name
        if not path.is_file() or name.startswith('~$') or path.suffix.lower() not in EXTENSIONS:
            continue
        known = _known(name)
        entry = manifest.get(name) if isinstance(manifest.get(name), dict) else {}
        mrole = entry.get('role')
        role, source = (mrole, 'manifest') if isinstance(mrole, str) and mrole in ROLES else \
            (known['role'], 'name') if known else (_role_by_name(name), 'name')
        normalized = entry['normalized'] if isinstance(entry.get('normalized'), bool) else bool(known and known['normalized'])
        stat = path.stat()
        files.append({'name': name, 'size': stat.st_size,
                      'modified': dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='minutes'),
                      'role': role, 'role_label': ROLES.get(role, ''), 'role_source': source if role else '',
                      'normalized': normalized, 'known': known['label'] if known else '',
                      'qc': _qc_summary(folder, name)})
    if not files and not warning:
        warning = 'В папке нет таблиц Excel или CSV: положите файлы данных или выберите другую папку.'
    return {'folder': str(folder), 'manifest': bool(manifest) or (folder / MANIFEST).exists(), 'warning': warning,
            'roles': [{'value': k, 'label': v} for k, v in ROLES.items()], 'files': files}


def save_manifest(raw_folder: Any, files: Any) -> dict[str, Any]:
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
        if role is None:
            entry.pop('role', None)
        else:
            entry['role'] = role
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
    return scan(str(folder))


def routes() -> list[Route]:
    def wrap(work):
        async def handler(request: Request):
            try:
                body = await request.json()
            except ValueError:
                return error(400, 'Тело запроса должно быть JSON')
            if not isinstance(body, dict):
                return error(400, 'Тело запроса должно быть объектом JSON')
            try:
                out = await run_in_threadpool(work, body)
            except ParamError as e:
                return error(400, str(e))
            except Exception:
                log.exception('Сбой запроса %s', request.url.path)
                return error(500, internal_error_text())
            return out if isinstance(out, Response) else JSONResponse(out)
        return handler

    return [
        Route('/api/folder/scan', wrap(lambda b: scan(b.get('folder'))), methods=['POST']),
        Route('/api/folder/manifest', wrap(lambda b: save_manifest(b.get('folder'), b.get('files'))), methods=['POST']),
    ]

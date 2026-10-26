"""«Проверить всё» для файлов папки проекта: пробный разбор каждого файла по его роли, без записи в проект.

Тот же разбор, что при загрузке (``project_folder.load_files``), но результат — сводка по файлу: сколько строк и скважин,
какой период, какие замечания. Ошибка одного файла не мешает остальным; решение о загрузке остаётся за инженером.

| Запрос | Что делает |
|---|---|
| `POST /api/projects/{pid}/folder/check` `{folder, files}` | сводка по каждому файлу: статус ok / attention / error / skip, текст, замечания |
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from .contract import ParamError
from .engine.core import elpro_import as elpro
from .engine.core import gas_db_import, gis_import, tabular, water_monthly_import, well_geo_import
from .engine.core import ggh_import as ggh

log = logging.getLogger(__name__)
LIMIT = 30          # замечаний на файл в сводке


def _period(frame: pd.DataFrame, col: str = 'date') -> str:
    if col not in frame or frame.empty:
        return ''
    dates = pd.to_datetime(frame[col], errors='coerce').dropna()
    return f'{dates.min():%d.%m.%Y} — {dates.max():%d.%m.%Y}' if len(dates) else ''


def _stats(rows: int, wells: int | None = None, period: str = '') -> str:
    parts = [f'строк {rows}']
    if wells is not None:
        parts.append(f'скважин {wells}')
    if period:
        parts.append(period)
    return ', '.join(parts)


def _ok(message: str, notes: list[str] | None = None, rows: int = 0) -> dict[str, Any]:
    notes = [str(n) for n in (notes or []) if n]
    return {'rows': rows, 'status': 'attention' if notes else 'ok', 'message': message,
            'issues': [{'level': 'замечание', 'reason': n} for n in notes[:LIMIT]], 'issues_count': len(notes)}


def _elpro(name: str, content: bytes) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(content)
        data, _infos, cov, warn = elpro.build([str(path)])
    if data.empty:
        raise ParamError('В файле нет данных ЭЛПРО' + (f': {warn[0]}' if warn else '.'))
    new, _extra = elpro.keep_first(elpro.to_db(data))
    gaps = int((cov['Статус'] != 'есть').sum()) if not cov.empty else 0
    notes = list(warn) + ([f'Пропусков покрытия (ГСП × месяц): {gaps}'] if gaps else [])
    return _ok('ЭЛПРО: ' + _stats(len(new), new.well.nunique(), _period(new)), notes, len(new))


def _gas(name: str, content: bytes) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(content)
        new = gas_db_import.build(path)
    if new.empty:
        raise ParamError('В «БД по учету газа» нет суток с объёмом по объекту: проверьте лист «БД».')
    return _ok(f'БД по учету газа: суток отбора {int((new.kind == "withdrawal").sum())}, закачки {int((new.kind == "injection").sum())}, '
               + _period(new), rows=len(new))


def _gis(name: str, content: bytes, table: str = '') -> dict[str, Any]:
    parts = [p for p in gis_import.read_all(name, content, table) if not p[1].empty]
    if not parts:
        raise ParamError('Нет строк с датой и скважиной.')
    notes = [w for _kind, _new, warn in parts for w in warn]
    return _ok('База ГИС: ' + '; '.join(f'{gis_import.LABELS[k]} — строк {len(n)}, скважин {n["well"].nunique()}' for k, n, _ in parts), notes, sum(len(n) for _k, n, _w in parts))


def _geo(name: str, content: bytes) -> dict[str, Any]:
    new, warnings = well_geo_import.build(name, content)
    if new.empty:
        raise ParamError('Не нашлось строк «скважина, X, Y» или перфорации и альтитуд.')
    return _ok(f'Положение и перфорация: скважин {len(new)}', warnings, len(new))


def _water(name: str, content: bytes) -> dict[str, Any]:
    new, warnings = water_monthly_import.build(name, content)
    return _ok('Замеры воды за месяц: ' + _stats(len(new), new['well'].nunique(), _period(new)), warnings, len(new))


def _ggh(name: str, content: bytes) -> dict[str, Any]:
    tables = tabular.read_content(content, name)[1]
    sheet = ggh.find_sheet(tables)
    if sheet is None:
        raise ParamError('В файле нет листа ГГХ: нужна шапка с колонками «№№ скв.» и «Дата отбора».')
    data, notes = ggh.normalize(tables[sheet])
    return _ok(f'ГГХ, лист «{sheet}»: ' + _stats(len(data), data.well.nunique(), _period(data)), [f'строка {n[0]}: {n[2]}' for n in notes], len(data))


SPECIAL = {'elpro': _elpro, 'gas': _gas, 'gis': _gis, 'geo': _geo, 'ggh': _ggh}
KINDS = {**SPECIAL, 'water': _water}       # все виды файлов со своим разбором (общее окно импорта)


def _general(imports, pid: str, name: str, content: bytes) -> dict[str, Any]:
    """Расходы, давления, ГДИ, вода: общий разбор с проверкой строк; проверка нигде не сохраняется."""
    up = imports.upload(name, content)
    if up['error']:
        raise ParamError(up['error'])
    pending = imports.check(pid, {'files': [{'token': up['token']}], 'mode': 'auto', 'view': 'simple'})
    try:
        frame = imports.pending[pending['id']]['issues']
        issues = [{'level': str(r['Уровень']), 'reason': f"{r['Лист']}, строка {r['Строка']}: {r['Причина']}"}
                  for _, r in frame.head(LIMIT).iterrows()]
        text = ', '.join(f"{c['label']} — строк {c['rows']}" for c in pending['counts']) or 'нет строк для загрузки'
        out = {'status': 'ok', 'message': text, 'issues': issues, 'issues_count': pending.get('issues_count', 0)}
        if pending['rejected']:
            out['status'] = 'attention'
            out['message'] += f". Отклонённых строк: {pending['rejected']}"
        elif not pending['counts']:
            out['status'] = 'error'
        elif pending.get('issues_count'):
            out['status'] = 'attention'
        return out
    finally:
        imports.discard(pending['id'])


def check_one(imports, pid: str, folder: Path, name: str, role: str | None, names_ok: set) -> dict[str, Any]:
    from .project_folder import EXTENSIONS, ROLES
    out = {'name': name, 'role': role, 'role_label': ROLES.get(role, '')}
    if name not in names_ok or Path(name).name != name or Path(name).suffix.lower() not in EXTENSIONS:
        return dict(out, status='error', message='Файла нет в папке или он не таблица', issues=[], issues_count=0)
    if not role:
        return dict(out, status='skip', message='Тип файла не определён: выберите роль, и файл можно проверить.', issues=[], issues_count=0)
    try:
        content = (folder / name).read_bytes()
        if role in SPECIAL:
            result = SPECIAL[role](name, content)
        elif role == 'water' and water_monthly_import.looks_like(tabular.read_content(content, name, 31)[1], name):
            result = _water(name, content)
        else:
            result = _general(imports, pid, name, content)
        return dict(out, **result)
    except ParamError as e:
        return dict(out, status='error', message=str(e), issues=[], issues_count=0)
    except OSError as e:
        return dict(out, status='error', message=f'Файл не прочитан: {e.strerror or e}', issues=[], issues_count=0)
    except Exception as e:
        log.exception('Сбой проверки %s', name)
        return dict(out, status='error', message=f'Файл не разобран: {e}. Подробности — в журнале.', issues=[], issues_count=0)


def check_files(imports, projects, pid: str, raw_folder: Any, names: Any) -> dict[str, Any]:
    from .project_folder import _folder, scan
    folder = _folder(raw_folder)
    if not isinstance(names, list) or not names:
        raise ParamError('Выберите файлы для проверки')
    projects.manifest(pid)
    roles = {f['name']: f['role'] for f in scan(str(folder))['files']}
    names_ok = {p.name for p in folder.iterdir() if p.is_file()}
    return {'results': [check_one(imports, pid, folder, str(n), roles.get(str(n)), names_ok) for n in names]}

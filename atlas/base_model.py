"""Базовая модель проекта: из неё берутся базовые параметры скважин (устье X, Y, альтитуда, перфорация).

Модель выбирается в разделе «Импорт данных» из общего списка папок tNav и хранится в ``settings['base_model']`` проекта;
остальные программы (Карты, ГДМ) читают тот же проект. Значения берутся из входных файлов модели (.data, INCLUDE) читалкой
``tnav_results.base_model`` (all_scripts). Это подсказка: показывается сверка с загруженным файлом, а в таблицу ``well_geo``
значения попадают только по команде инженера — «дополнить пропуски» или «заменить» по выбранным полям. Файловое значение
можно оставить главным.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .engine.core import well_geo_import as geo

KEY = 'base_model'
FIELDS = {'x': ('x',), 'y': ('y',), 'altitude': ('altitude',), 'perf': ('perf_top', 'perf_bottom')}
LABELS = {'x': 'X', 'y': 'Y', 'altitude': 'Альтитуда', 'perf': 'Перфорация (верх, низ)'}
TOLERANCE = {'x': 1.0, 'y': 1.0, 'altitude': 1.0, 'perf_top': 1.0, 'perf_bottom': 1.0}     # м: меньшее расхождение не считается
MAX_ROWS = 300


class BaseModelUnavailable(RuntimeError):
    """Читалка модели недоступна или файлы модели не читаются: текст показывается инженеру."""


def selected(settings: Mapping[str, Any]) -> str:
    return str(settings.get(KEY) or '').strip().strip('"')


def _egrid(anchor: str) -> str | None:
    folder, name = os.path.split(anchor)
    stem = os.path.splitext(name)[0].lower()
    try:
        for n in sorted(os.listdir(folder or '.')):
            if os.path.splitext(n)[0].lower() == stem and n.upper().endswith('.EGRID'):
                return os.path.join(folder, n)
    except OSError:
        pass
    return None


def read(anchor: str) -> tuple[pd.DataFrame, dict[str, dict[str, str]], list[str]]:
    """Параметры скважин модели в формате ``well_geo``: (таблица, источники значений по скважинам, замечания)."""
    try:
        from tnav_results import base_model, perforations
    except ImportError as e:
        raise BaseModelUnavailable('Не найдена читалка tNavigator (пакет tnav_results из all_scripts).') from e
    try:
        res = base_model.well_params(anchor)
    except (OSError, ValueError) as e:
        raise BaseModelUnavailable(f'Входные файлы модели не прочитаны: {e}') from e
    notes = list(res['notes'])
    if not res['files']:
        raise BaseModelUnavailable('Рядом с моделью нет входного файла .data: параметры скважин взять не из чего. '
                                   + ' '.join(notes))
    grid = None
    egrid = _egrid(anchor)
    if egrid:
        try:
            from tnav_results.grid_cache import read_egrid_cached
            grid = read_egrid_cached(egrid)
        except Exception as e:      # битая сетка не мешает остальным значениям
            notes.append(f'Сетка EGRID не прочитана ({e}): отметки перфорации не посчитаны')
    else:
        notes.append('Рядом с моделью нет EGRID: отметки перфорации не посчитаны')
    rows, sources = [], {}
    for name, d in res['wells'].items():
        wid = geo.well_id(name)
        if wid is None:
            notes.append(f'Скважина «{name}»: номер не определён, пропущена')
            continue
        top = bottom = np.nan
        ivs = perforations.add_depths([perforations.PerfRow(name, r['i'], r['j'], r['k1'], r['k2'], r['status']) for r in d['intervals']], grid)
        ivs = [r for r in ivs if r.top_ao is not None]
        if ivs:
            top, bottom = max(r.top_ao for r in ivs), min(r.bottom_ao for r in ivs)
        rows.append({'well': wid, 'x': d['x'], 'y': d['y'], 'altitude': d['altitude'], 'perf_top': top, 'perf_bottom': bottom})
        sources[wid] = {**d['sources'], **({'perf': f'COMPDAT ({len(ivs)} инт.)'} if ivs else {})}
    frame = pd.DataFrame(rows, columns=geo.COLUMNS)
    for c in geo.VALUES:
        frame[c] = pd.to_numeric(frame[c], errors='coerce')
    frame = frame.drop_duplicates('well', keep='last')
    return frame.sort_values('well', key=lambda s: s.astype(int)).reset_index(drop=True), sources, notes


def compare(model: pd.DataFrame, file: pd.DataFrame | None) -> dict[str, Any]:
    """Сверка модели с загруженным ``well_geo``: по каждому полю — совпало, расходится, есть только в модели/только в файле."""
    f = file.set_index('well') if file is not None and not file.empty else pd.DataFrame(columns=geo.VALUES)
    m = model.set_index('well')
    counts = {k: {'same': 0, 'diff': 0, 'only_model': 0, 'only_file': 0} for k in FIELDS}
    rows = []
    for well in m.index:
        cells, flagged = {}, False
        for key, cols in FIELDS.items():
            state = 'none'
            for c in cols:
                a = m.at[well, c]
                b = f.at[well, c] if well in f.index and c in f.columns else np.nan
                if np.isnan(a) and np.isnan(b):
                    continue
                s = 'only_file' if np.isnan(a) else 'only_model' if np.isnan(b) else 'same' if abs(a - b) <= TOLERANCE[c] else 'diff'
                state = s if state in ('none', 'same') or s == 'diff' else state
                cells[c] = {'model': None if np.isnan(a) else float(a), 'file': None if np.isnan(b) else float(b), 'state': s}
            if state != 'none':
                counts[key][state] += 1
                flagged = flagged or state in ('diff', 'only_model')
        if flagged:
            rows.append({'well': well, **cells})
    return {'wells': int(len(m)), 'counts': counts, 'rows': rows[:MAX_ROWS], 'truncated': max(0, len(rows) - MAX_ROWS)}


def apply(old: pd.DataFrame | None, model: pd.DataFrame, fields: list[str], mode: str) -> pd.DataFrame:
    """Новый ``well_geo``: выбранные поля модели заполняют пропуски (``fill``) или заменяют значения файла (``replace``)."""
    cols = [c for k in fields for c in FIELDS[k]]
    new = model[['well', *cols]].copy()
    for c in geo.VALUES:
        if c not in new:
            new[c] = np.nan
    return geo.merge(old, new[geo.COLUMNS], keep_old=mode == 'fill')

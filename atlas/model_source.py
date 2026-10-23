"""Модели tNavigator как источник данных конструктора графиков: векторы скважин из SMSPEC/UNSMRY.

Кубы свойств (по запросу, считаются медленно): по датам рестарта показатели объекта — среднее давление и средняя Sg
по поровому объёму, газонасыщенный поровый объём, ГВК. Это набор ``model_object`` (дата, модель, показатели).

Читалка (``tnav_results``) лежит в репозитории all_scripts и есть в едином архиве; без неё модели не видны, остальной Атлас
работает. Набор ``model``: скважина, дата, имя модели и по колонке на вектор (wgpr, wbhp…), значения сразу в единицах
проекта (тыс. м³/сут, кгс/см² абс.). Несколько записей за сутки сводятся к последней. Выбранные модели —
``settings['model_sources']`` (пути к файлам из общего списка папок tNav), сами данные в проект не копируются.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Mapping

import pandas as pd

KEY = 'model_sources'
CUBES_KEY = 'model_cubes'        # True — считать кубы выбранных моделей
CUBES_RANGE = ('model_cubes_from', 'model_cubes_to')     # рестарты с … по … (включительно, 'ГГГГ-ММ-ДД'); пусто — без границы
SG_THRESHOLD = 0.01              # порог газонасыщенности: значение заказчика, как в ГДМ
FIELD_NAME = ':+:+:+:+'          # у векторов объекта в WGNAMES стоит этот заполнитель, скважины там нет
_CACHE_LIMIT = 4
_cache: dict[tuple, pd.DataFrame] = {}
_lock = threading.Lock()

# вектор → (подпись, единица на экране). Остальные W*-векторы берут подпись «<ключ> (модель)» и единицу сводки.
LABELS = {
    'WGPR': ('Дебит газа (модель)', 'тыс. м³/сут'), 'WGIR': ('Закачка газа (модель)', 'тыс. м³/сут'),
    'WWPR': ('Дебит воды (модель)', 'м³/сут'), 'WWIR': ('Закачка воды (модель)', 'м³/сут'),
    'WBHP': ('Рзаб (модель)', 'кгс/см²'), 'WBP': ('Давление в ячейке скважины (модель)', 'кгс/см²'),
    'WBP4': ('Давление вокруг ячейки, 4 соседа (модель)', 'кгс/см²'),
    'WBP9': ('Давление вокруг ячейки, 9 соседей (модель)', 'кгс/см²'),
    'WTHP': ('Руст (модель)', 'кгс/см²'),
    'WGPT': ('Накопленная добыча газа (модель)', 'млн м³'), 'WGIT': ('Накопленная закачка газа (модель)', 'млн м³'),
    'WWPT': ('Накопленная добыча воды (модель)', 'м³'),
}
# единица сводки → (множитель, единица проекта) для давления
_PRESSURE = {'BARSA': (1.0197162, 'кгс/см²'), 'BARS': (1.0197162, 'кгс/см²'), 'ATMA': (1.0, 'кгс/см²'),
             'KPA': (0.0101972, 'кгс/см²'), 'KPASCAL': (0.0101972, 'кгс/см²'), 'MPA': (10.19716, 'кгс/см²'),
             'PSIA': (0.0703070, 'кгс/см²')}
_GAS_VOLUME = {'SM3': 1e-6, 'KSM3': 1e-3, 'MSM3': 1.0}      # → млн м³
CUBE_LABELS = {
    'p_avg': ('Среднее пластовое давление (модель)', 'кгс/см²'), 'sg_avg': ('Средняя газонасыщенность (модель)', 'д.ед.'),
    'gpv': ('Газонасыщенный поровый объём (модель)', 'млн м³'), 'gwc_mean': ('ГВК: среднее по колоннам (модель)', 'м'),
    'gwc_area': ('ГВК: среднее по площади (модель)', 'м'), 'gwc_min': ('ГВК: самый высокий (модель)', 'м'),
    'gwc_max': ('ГВК: самый низкий (модель)', 'м'),
}
_PRESSURE_BY_UNITS = {1: 1.0197162, 2: 0.0703070, 3: 1.0332275, 4: 1.0332275}     # INTEHEAD[2]: бар, psi, атм → кгс/см²
_registry: dict[str, tuple[str, str]] = {}                 # колонка → (подпись, единица): заполняется при чтении


class ModelUnavailable(RuntimeError):
    """Читалка tNav недоступна или файлы модели не читаются: текст показывается инженеру."""


def available() -> bool:
    try:
        import tnav_results  # noqa: F401
    except ImportError:
        return False
    return True


def scale(keyword: str, unit: str) -> tuple[float, str]:
    """Множитель к единицам проекта и единица на экране для вектора сводки."""
    u = (unit or '').strip().upper()
    gas = keyword[1:2] == 'G'
    if u in _PRESSURE and 'P' in keyword[1:]:
        return _PRESSURE[u]
    if gas and u == 'SM3/DAY':
        return 1e-3, 'тыс. м³/сут'
    if gas and u in _GAS_VOLUME:
        return _GAS_VOLUME[u], 'млн м³'
    return 1.0, (unit or '').strip()


def column_meta(column: str) -> tuple[str, str]:
    """(подпись, единица) колонки набора ``model``."""
    if column in _registry:
        return _registry[column]
    if column in CUBE_LABELS:
        return CUBE_LABELS[column]
    kw = column.upper()
    return LABELS.get(kw, (f'{kw} (модель)', ''))[0], ''


def _indicators():
    try:
        from tnav_results import files, indicators, parallel
    except ImportError as e:
        raise ModelUnavailable('Не найдена читалка tNavigator (пакет tnav_results из all_scripts).') from e
    return indicators, files, parallel


def _tnav():
    try:
        import tnav_results
        from tnav_results import catalog
    except ImportError as e:
        raise ModelUnavailable('Не найдена читалка tNavigator (пакет tnav_results из all_scripts). '
                               'Она входит в единый архив; отдельно её нужно положить рядом с Атласом.') from e
    return tnav_results, catalog


def listing(selected: list[str], cubes: bool = False, span: tuple[str, str] = ('', '')) -> dict[str, Any]:
    """Модели из общего списка папок tNav (с готовой сводкой) и отметка выбранных."""
    try:
        _, catalog = _tnav()
    except ModelUnavailable as e:
        return {'available': False, 'error': str(e), 'folders': [], 'models': [], 'cubes': False, 'cubes_from': '', 'cubes_to': ''}
    folders = catalog.load_folders()
    models = [{'id': m['id'], 'name': m['name'], 'folder': m['folder'], 'selected': m['id'] in selected, 'indicators': bool(m.get('indicators'))}
              for m in catalog.scan(folders) if m['summary']]
    return {'available': True, 'error': '', 'folders': folders, 'models': models, 'cubes': cubes, 'cubes_from': span[0], 'cubes_to': span[1]}


def cubes_on(settings: Mapping[str, Any]) -> bool:
    return settings.get(CUBES_KEY) is True


def cubes_range(settings: Mapping[str, Any]) -> tuple[str, str]:
    return tuple(str(settings.get(k) or '')[:10] for k in CUBES_RANGE)     # type: ignore[return-value]


def sources_of(settings: Mapping[str, Any]) -> list[str]:
    raw = settings.get(KEY)
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _summary_files(anchor: str) -> tuple[str, str]:
    folder, name = os.path.split(str(anchor or '').strip().strip('"'))
    stem = os.path.splitext(name)[0].lower()
    found: dict[str, str] = {}
    try:
        names = sorted(os.listdir(folder or '.'))
    except OSError:
        names = []
    for n in names:
        base, ext = os.path.splitext(n)
        if base.lower() == stem and ext[1:].upper() in ('SMSPEC', 'UNSMRY'):
            found[ext[1:].upper()] = os.path.join(folder, n)
    if len(found) < 2:
        raise ModelUnavailable(f'У модели «{name}» нет файлов сводки (SMSPEC и UNSMRY) рядом: {folder}')
    return found['SMSPEC'], found['UNSMRY']


def read_model(anchor: str, label: str = '') -> pd.DataFrame:
    """Векторы скважин одной модели; результат кэшируется по размеру и времени файлов."""
    tnav, _ = _tnav()
    smspec, unsmry = _summary_files(anchor)
    key = (smspec, unsmry, *(v for f in (smspec, unsmry) for v in (os.path.getmtime(f), os.path.getsize(f))))
    with _lock:
        if key in _cache:
            return _cache[key]
    try:
        summary = tnav.read_summary(smspec, unsmry)
    except (OSError, ValueError, KeyError) as e:
        raise ModelUnavailable(f'Сводку модели «{os.path.basename(smspec)}» прочитать не удалось: {e}') from e
    dates = pd.to_datetime(pd.Series(summary.dates)).dt.normalize()
    values = pd.DataFrame(summary.data, dtype=float)
    columns: dict[str, pd.Series] = {}
    keys: list[tuple[str, str]] = []                  # (скважина, колонка)
    for ci, (kw, name, nums, unit) in enumerate(summary.columns):
        name = str(name).strip()
        if kw[:1] != 'W' or not name or name == FIELD_NAME or ci >= values.shape[1]:
            continue
        factor, shown = scale(kw, unit)
        column = kw.lower()
        _registry[column] = (LABELS.get(kw, (f'{kw} (модель)', ''))[0], shown)
        columns[(name, column)] = values[ci] * factor
        keys.append((name, column))
    if not columns:
        raise ModelUnavailable(f'В сводке «{os.path.basename(smspec)}» нет векторов скважин (W…)')
    parts = []
    for well in dict.fromkeys(w for w, _ in keys):
        part = pd.DataFrame({c: columns[(w, c)].to_numpy() for w, c in keys if w == well})
        part.insert(0, 'date', dates.to_numpy())
        part.insert(0, 'well', well)
        parts.append(part.drop_duplicates('date', keep='last'))      # несколько записей за сутки: последняя
    long = pd.concat(parts, ignore_index=True)
    long = long.dropna(subset=[c for c in long.columns if c not in ('date', 'well')], how='all')
    long.insert(2, 'model', label or os.path.splitext(os.path.basename(smspec))[0])
    long = long.sort_values(['well', 'date'], kind='stable').reset_index(drop=True)
    with _lock:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.pop(next(iter(_cache)))
        _cache[key] = long
    return long


def frame(anchors: list[str]) -> tuple[pd.DataFrame | None, list[str]]:
    """Общий набор ``model`` по выбранным моделям и заметки о тех, что не прочитались."""
    parts, notes = [], []
    names = {}
    try:
        _, catalog = _tnav()
        names = catalog.load_names()
    except ModelUnavailable as e:
        return None, [str(e)]
    for anchor in anchors:
        try:
            parts.append(read_model(anchor, names.get(anchor) or catalog.model_name(anchor)))
        except ModelUnavailable as e:
            notes.append(str(e))
    if not parts:
        return None, notes
    return pd.concat(parts, ignore_index=True), notes


# ---------- кубы свойств ----------

def _cube_files(anchor: str) -> dict[str, str]:
    folder, name = os.path.split(str(anchor or '').strip().strip('"'))
    stem = os.path.splitext(name)[0].lower()
    found: dict[str, str] = {}
    try:
        names = sorted(os.listdir(folder or '.'))
    except OSError:
        names = []
    for n in names:
        base, ext = os.path.splitext(n)
        if base.lower() == stem and ext[1:].upper() in ('EGRID', 'INIT', 'UNRST'):
            found[ext[1:].upper()] = os.path.join(folder, n)
    missing = [k for k in ('EGRID', 'INIT', 'UNRST') if k not in found]
    if missing:
        raise ModelUnavailable(f'Для кубов у модели «{name}» нет файлов: {", ".join(missing)}')
    return found


def _cube_row(model, step, ctx):
    """Показатели объекта на одном шаге рестарта (None — на шаге нет SGAS). Функция верхнего уровня: считается в процессах."""
    import numpy as np
    ind, files, _ = _indicators()
    unrst, threshold, porv, factor = ctx
    sg = files.read_restart_keyword(unrst, step, 'SGAS')
    if sg is None:
        return None
    w = np.asarray(porv[:model.n_active], dtype=float)
    total = float(w.sum())
    row = {'date': step.date, 'gpv': ind.gas_pore_volume(model, porv, sg, threshold).total / 1e6}
    if total > 0:
        row['sg_avg'] = float((np.asarray(model.to_units(sg, 'Sg')[0], dtype=float) * w).sum() / total)
        p = files.read_restart_keyword(unrst, step, 'PRESSURE')
        if p is not None:
            row['p_avg'] = float((np.asarray(model.to_units(p, 'PRESSURE')[0], dtype=float) * w).sum() / total * factor)
    stats = ind.gwc_stats(model, ind.gwc_map(model, sg, threshold))
    if stats.columns:
        row.update(gwc_mean=-stats.mean, gwc_area=-stats.mean_area, gwc_min=-stats.max, gwc_max=-stats.min)    # глубина вниз → а.о. со знаком минус
    return row


def read_cubes(anchor: str, label: str = '', span: tuple[str, str] = ('', '')) -> pd.DataFrame:
    """Показатели объекта по датам рестарта одной модели (кэш по размеру и времени файлов)."""
    ind, files, parallel = _indicators()
    found = _cube_files(anchor)
    key = ('cubes', span, *(v for f in found.values() for v in (f, os.path.getmtime(f), os.path.getsize(f))))
    with _lock:
        if key in _cache:
            return _cache[key]
    try:
        model = ind.load_model(found['EGRID'])
        low = pd.Timestamp(span[0]) if span[0] else None
        high = pd.Timestamp(span[1]) + pd.Timedelta(days=1) if span[1] else None       # «по» включает весь день
        steps = [s for s in files.iter_restart_steps(found['UNRST'])
                 if s.date is not None and (low is None or pd.Timestamp(s.date) >= low) and (high is None or pd.Timestamp(s.date) < high)]
        if not steps:
            raise ModelUnavailable(f'В рестарте «{os.path.basename(found["UNRST"])}» нет шагов в выбранных датах')
        porv_raw = files.read_init(found['INIT'], ['PORV'])['PORV']
        porv = [v for part in model.to_units(porv_raw, 'PORV', 'sum') for v in part]
        head = files.read_restart_keyword(found['UNRST'], steps[0], 'INTEHEAD') if steps else None
        factor = _PRESSURE_BY_UNITS.get(int(head[2]), 1.0) if head is not None else 1.0
        rows = parallel.map_steps(_cube_row, model, steps, (found['UNRST'], SG_THRESHOLD, porv, factor), found['EGRID'])
    except (OSError, ValueError, KeyError, IndexError) as e:
        raise ModelUnavailable(f'Кубы модели «{os.path.basename(found["EGRID"])}» прочитать не удалось: {e}') from e
    rows = [r for r in rows if r is not None]
    if not rows:
        raise ModelUnavailable(f'В рестарте «{os.path.basename(found["UNRST"])}» нет куба SGAS')
    frame = pd.DataFrame(rows)
    frame['date'] = pd.to_datetime(frame['date']).dt.normalize()
    frame = frame.drop_duplicates('date', keep='last').reset_index(drop=True)
    frame.insert(1, 'model', label or os.path.splitext(os.path.basename(found['EGRID']))[0])
    with _lock:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.pop(next(iter(_cache)))
        _cache[key] = frame
    return frame


def cubes_frame(anchors: list[str], span: tuple[str, str] = ('', '')) -> tuple[pd.DataFrame | None, list[str]]:
    parts, notes = [], []
    try:
        _, catalog = _tnav()
        names = catalog.load_names()
    except ModelUnavailable as e:
        return None, [str(e)]
    for anchor in anchors:
        try:
            parts.append(read_cubes(anchor, names.get(anchor) or catalog.model_name(anchor), span))
        except ModelUnavailable as e:
            notes.append(str(e))
    return (pd.concat(parts, ignore_index=True) if parts else None), notes

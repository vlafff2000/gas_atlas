"""Модели tNavigator как источник данных конструктора графиков: векторы скважин из SMSPEC/UNSMRY.

Кубы свойств (по запросу, считаются медленно): по датам рестарта показатели объекта — среднее давление и средняя Sg
по поровому объёму, газонасыщенный поровый объём, ГВК. Это набор ``model_object`` (дата, модель, показатели).

Читалка (``tnav_results``) лежит в репозитории all_scripts и есть в едином архиве; без неё модели не видны, остальной Атлас
работает. Набор ``model``: скважина, дата, имя модели и по колонке на вектор (wgpr, wbhp…), значения сразу в единицах
проекта (тыс. м³/сут, кгс/см² абс.). Несколько записей за сутки сводятся к последней. Выбранные модели —
``settings['model_sources']`` (пути к файлам из общего списка папок tNav), сами данные в проект не копируются.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any, Mapping

import pandas as pd

KEY = 'model_sources'
CUBES_KEY = 'model_cubes'        # True — считать кубы выбранных моделей
CELLS_KEY = 'model_cells'        # {'dates': ['ГГГГ-ММ-ДД', …], 'k_from': 1, 'k_to': 0 (до низа), 'max_points': 20000}
MAX_CELL_DATES = 6
CELLS_DEFAULT = {'dates': [], 'k_from': 1, 'k_to': 0, 'max_points': 20000}
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
CELL_LABELS = {
    'restart': ('Дата рестарта', ''), 'i': ('Ячейка: i', ''), 'j': ('Ячейка: j', ''), 'k': ('Ячейка: слой k', ''),
    'depth': ('Глубина ячейки, а.о. (модель)', 'м'), 'p': ('Давление в ячейке (модель)', 'кгс/см²'),
    'sg': ('Газонасыщенность ячейки (модель)', 'д.ед.'), 'porv': ('Поровый объём ячейки (модель)', 'тыс. м³'),
}
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
    if column in CELL_LABELS:
        return CELL_LABELS[column]
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


def listing(selected: list[str], cubes: bool = False, span: tuple[str, str] = ('', ''), cells: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Модели из общего списка папок tNav (с готовой сводкой) и отметка выбранных."""
    try:
        _, catalog = _tnav()
    except ModelUnavailable as e:
        return {'available': False, 'error': str(e), 'folders': [], 'models': [], 'cubes': False, 'cubes_from': '', 'cubes_to': '', 'cells': dict(CELLS_DEFAULT)}
    folders = catalog.load_folders()
    models = [{'id': m['id'], 'name': m['name'], 'folder': m['folder'], 'selected': m['id'] in selected, 'indicators': bool(m.get('indicators'))}
              for m in catalog.scan(folders) if m['summary']]
    return {'available': True, 'error': '', 'folders': folders, 'models': models, 'cubes': cubes, 'cubes_from': span[0], 'cubes_to': span[1], 'cells': dict(cells or CELLS_DEFAULT)}


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


DISK_FILES = 24                     # столько файлов кэша держим; старые удаляются


def _disk_dir() -> str:
    home = os.environ.get('PXG_HOME') or os.path.join(os.path.expanduser('~'), '.pxg')     # тот же каталог, что у списка папок tNav
    return os.path.join(home, 'model_cache')


def _disk_path(found: Mapping[str, str], threshold: float) -> str:
    """Файл кэша шагов одной модели. Ключ: сетка и INIT (путь, размер, время), путь к рестарту и начало рестарта. Рестарт при дозаписи
    только растёт, начало не меняется, поэтому посчитанные шаги остаются верными; пересчитанная модель меняет начало и ключ."""
    parts = [f'{threshold}']
    for kind in ('EGRID', 'INIT'):
        f = found[kind]
        parts += [os.path.abspath(f), str(os.path.getsize(f)), str(os.path.getmtime(f))]
    with open(found['UNRST'], 'rb') as fh:
        parts += [os.path.abspath(found['UNRST']), hashlib.sha1(fh.read(65536)).hexdigest()]
    return os.path.join(_disk_dir(), 'cubes_' + hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:20] + '.json')


def _disk_load(path: str) -> dict[str, dict]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _disk_save(path: str, rows: dict[str, dict]) -> None:
    """Не вышло записать (нет прав, диск полон) — не страшно: модель просто посчитается заново."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False)
        os.replace(tmp, path)
        old = sorted((os.path.join(os.path.dirname(path), n) for n in os.listdir(os.path.dirname(path)) if n.startswith('cubes_') and n.endswith('.json')),
                     key=os.path.getmtime)
        for stale in old[:-DISK_FILES]:
            os.remove(stale)
    except OSError:
        pass


def _step_key(step) -> str:
    return f'{getattr(step, "seqnum", "")}|{pd.Timestamp(step.date):%Y-%m-%dT%H:%M:%S}'


def forget_cubes(anchors: list[str]) -> int:
    """Сбрасывает сохранённые шаги кубов выбранных моделей (память и диск): следующее чтение считает всё заново."""
    removed = 0
    for anchor in anchors:
        try:
            os.remove(_disk_path(_cube_files(anchor), SG_THRESHOLD))
            removed += 1
        except (OSError, ModelUnavailable):
            pass
    with _lock:
        _cache.clear()
    return removed


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
        disk = _disk_path(found, SG_THRESHOLD)
        saved = _disk_load(disk)
        todo = [s for s in steps if _step_key(s) not in saved]
        if todo:                                                       # на диске нет только новых шагов
            porv_raw = files.read_init(found['INIT'], ['PORV'])['PORV']
            porv = [v for part in model.to_units(porv_raw, 'PORV', 'sum') for v in part]
            head = files.read_restart_keyword(found['UNRST'], todo[0], 'INTEHEAD')
            factor = _PRESSURE_BY_UNITS.get(int(head[2]), 1.0) if head is not None else 1.0
            fresh = parallel.map_steps(_cube_row, model, todo, (found['UNRST'], SG_THRESHOLD, porv, factor), found['EGRID'])
            for step, row in zip(todo, fresh):
                saved[_step_key(step)] = None if row is None else {**row, 'date': f'{pd.Timestamp(row["date"]):%Y-%m-%dT%H:%M:%S}'}
            _disk_save(disk, saved)
        rows = [saved[_step_key(s)] for s in steps]
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


# ---------- ячейки куба (для кроссплотов) ----------

def cells_of(settings: Mapping[str, Any]) -> dict[str, Any]:
    raw = settings.get(CELLS_KEY)
    raw = raw if isinstance(raw, Mapping) else {}
    dates = [str(d)[:10] for d in raw.get('dates', []) if d][:MAX_CELL_DATES] if isinstance(raw.get('dates'), list) else []
    return {'dates': dates, **{k: int(raw.get(k) or v) if str(raw.get(k) or '').lstrip('-').isdigit() else v
                              for k, v in CELLS_DEFAULT.items() if k != 'dates'}}


def restart_dates(anchor: str) -> list[str]:
    """Даты рестарта модели (читается только заголовок каждого шага)."""
    _, files, _ = _indicators()
    try:
        steps = files.iter_restart_steps(_cube_files(anchor)['UNRST'])
        return sorted({s.date.strftime('%Y-%m-%d') for s in steps if s.date is not None})
    except (OSError, ValueError) as e:
        raise ModelUnavailable(f'Рестарты модели прочитать не удалось: {e}') from e


def read_cells(anchor: str, label: str, cfg: Mapping[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    """Ячейки куба на выбранные даты: слои k_from…k_to, не больше max_points на дату (каждая n-я ячейка, это видно в заметке)."""
    import numpy as np
    ind, files, _ = _indicators()
    found = _cube_files(anchor)
    key = ('cells', tuple(cfg['dates']), cfg['k_from'], cfg['k_to'], cfg['max_points'],
           *(v for f in found.values() for v in (f, os.path.getmtime(f), os.path.getsize(f))))
    with _lock:
        if key in _cache:
            return _cache[key]
    notes: list[str] = []
    try:
        model = ind.load_model(found['EGRID'])
        steps = [s for s in files.iter_restart_steps(found['UNRST']) if s.date is not None]
        init = files.read_init(found['INIT'], ['PORV', 'DEPTH'])
        porv = np.asarray(model.to_units(init['PORV'], 'PORV', 'sum')[0], dtype=float)
        depth = np.asarray(model.to_units(init['DEPTH'], 'DEPTH')[0], dtype=float) if 'DEPTH' in init else None
        head = files.read_restart_keyword(found['UNRST'], steps[0], 'INTEHEAD') if steps else None
        factor = _PRESSURE_BY_UNITS.get(int(head[2]), 1.0) if head is not None else 1.0
        rep = np.asarray(model._rep)
        ni, nj = model.grid.ni, model.grid.nj
        layer = (rep // (ni * nj)) + 1
        keep = np.flatnonzero((layer >= cfg['k_from']) & ((layer <= cfg['k_to']) if cfg['k_to'] else True))
        step_by_day = {}
        for want in cfg['dates']:
            step = ind.pick_step(steps, pd.Timestamp(want).to_pydatetime())
            step_by_day[pd.Timestamp(step.date).normalize()] = step
            if pd.Timestamp(step.date).normalize() != pd.Timestamp(want):
                notes.append(f'Ячейки: рестарта на {want} нет, взят ближайший — {pd.Timestamp(step.date):%Y-%m-%d}')
        stride = max(1, -(-len(keep) // cfg['max_points']))
        if stride > 1:
            notes.append(f'Ячейки: из {len(keep)} показана каждая {stride}-я ({len(keep[::stride])}); число точек задаётся в настройке')
        pick = keep[::stride]
        parts = []
        for day, step in step_by_day.items():
            sg = files.read_restart_keyword(found['UNRST'], step, 'SGAS')
            pr = files.read_restart_keyword(found['UNRST'], step, 'PRESSURE')
            part = pd.DataFrame({'date': day, 'i': rep[pick] % ni + 1, 'j': (rep[pick] // ni) % nj + 1, 'k': layer[pick]})
            if depth is not None:
                part['depth'] = -depth[pick]                                  # глубина вниз → а.о. со знаком минус
            if pr is not None:
                part['p'] = np.asarray(model.to_units(pr, 'PRESSURE')[0], dtype=float)[pick] * factor
            if sg is not None:
                part['sg'] = np.asarray(model.to_units(sg, 'Sg')[0], dtype=float)[pick]
            part['porv'] = porv[pick] / 1e3
            part['restart'] = day.strftime('%Y-%m-%d')
            parts.append(part)
    except (OSError, ValueError, KeyError, IndexError) as e:
        raise ModelUnavailable(f'Ячейки модели «{os.path.basename(found["EGRID"])}» прочитать не удалось: {e}') from e
    if not parts:
        raise ModelUnavailable('Для ячеек выберите даты рестарта')
    frame = pd.concat(parts, ignore_index=True)
    frame.insert(1, 'model', label)
    with _lock:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (frame, notes)
    return frame, notes


def cells_frame(anchors: list[str], cfg: Mapping[str, Any]) -> tuple[pd.DataFrame | None, list[str]]:
    if not cfg['dates']:
        return None, []
    parts, notes = [], []
    try:
        _, catalog = _tnav()
        names = catalog.load_names()
    except ModelUnavailable as e:
        return None, [str(e)]
    for anchor in anchors:
        try:
            frame, more = read_cells(anchor, names.get(anchor) or catalog.model_name(anchor), cfg)
            parts.append(frame)
            notes += more
        except ModelUnavailable as e:
            notes.append(str(e))
    return (pd.concat(parts, ignore_index=True) if parts else None), notes

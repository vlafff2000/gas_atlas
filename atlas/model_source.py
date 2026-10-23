"""Модели tNavigator как источник данных конструктора графиков: векторы скважин из SMSPEC/UNSMRY.

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
    kw = column.upper()
    return LABELS.get(kw, (f'{kw} (модель)', ''))[0], ''


def _tnav():
    try:
        import tnav_results
        from tnav_results import catalog
    except ImportError as e:
        raise ModelUnavailable('Не найдена читалка tNavigator (пакет tnav_results из all_scripts). '
                               'Она входит в единый архив; отдельно её нужно положить рядом с Атласом.') from e
    return tnav_results, catalog


def listing(selected: list[str]) -> dict[str, Any]:
    """Модели из общего списка папок tNav (с готовой сводкой) и отметка выбранных."""
    try:
        _, catalog = _tnav()
    except ModelUnavailable as e:
        return {'available': False, 'error': str(e), 'folders': [], 'models': []}
    folders = catalog.load_folders()
    models = [{'id': m['id'], 'name': m['name'], 'folder': m['folder'], 'selected': m['id'] in selected}
              for m in catalog.scan(folders) if m['summary']]
    return {'available': True, 'error': '', 'folders': folders, 'models': models}


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

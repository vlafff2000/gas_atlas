"""Большой демонстрационный объект для проверки скорости: синтетика в формате импорта 5.8 / 6.

Объёмы задаются в строках, по умолчанию: отбор и закачка (эксплуатация фонда) 1 000 000, ГДИ 300 000,
реагирование 200 000, кроссплот давлений 500 000 пар. Данные детерминированы (``seed``), строятся векторно
и никогда не попадают в рабочие проекты: проект помечается как демонстрационный.

Код держит Python 3.8 (5.8 и инструмент ``tools/make_large_demo.py``).
"""
import math

import numpy as np
import pandas as pd

DEFAULTS = {'production': 1000000, 'gdi': 300000, 'response': 200000, 'pressure_match': 500000}
LABELS = {'production': 'Отбор и закачка', 'gdi': 'ГДИ', 'response': 'Реагирование', 'pressure_match': 'Кроссплот давлений'}
FIRST_YEAR = 2016
YEARS = 10                      # сезоны 2016-2017 … 2025-2026
WITHDRAWAL_DAYS, INJECTION_DAYS = 180, 150
GROUP_SIZE = 25                 # скважин в группе (ГСП)
HORIZONS = ('Окский', 'Бобриковский', 'Турнейский')
GDI_METHODS = ('Установившиеся отборы', 'Изохронный')
OBJECTS = ('Северный купол', 'Центральный купол', 'Южный купол')
SCENARIOS = ('Базовый', 'Адаптация 2024', 'Прогноз')
SOURCE = 'Демонстрация (большой объём)'


def _wells(count, start=101):
    return np.array([str(start + i) for i in range(count)], dtype=object)


def _group_of(index):
    return np.array(['ГСП %d' % (i // GROUP_SIZE + 1) for i in index], dtype=object)


def _subgroup_of(index):
    return np.array([str(i % GROUP_SIZE // 9 + 1) for i in index], dtype=object)


def production_wells(rows):
    """Число скважин, чтобы 10 сезонов отбора и закачки дали нужное число суточных строк."""
    return max(1, math.ceil(rows / (YEARS * (WITHDRAWAL_DAYS + INJECTION_DAYS))))


def production_frame(rows, rng):
    n = production_wells(rows)
    wells = _wells(n)
    base = rng.uniform(40, 320, n) * 1000                  # м³/сут на скважину
    blocks = []
    for year in range(FIRST_YEAR, FIRST_YEAR + YEARS):
        for kind, start, days in (('withdrawal', '%d-11-01' % year, WITHDRAWAL_DAYS),
                                  ('injection', '%d-05-01' % year, INJECTION_DAYS)):
            dates = pd.date_range(start, periods=days).values
            w = np.repeat(np.arange(n), days)
            t = np.tile(np.arange(days), n)
            q = (base[w] * (1 - .35 * t / days) * (1 + .04 * np.sin(t / 6 + w)) * (1 + .02 * (year - FIRST_YEAR))
                 * rng.normal(1, .03, len(w)))
            q[rng.random(len(w)) < .015] = 0.0                  # остановки
            blocks.append(pd.DataFrame({
                'w': w, 'date': np.tile(dates, n), 'q': np.round(np.maximum(q, 0), 2), 'kind': kind,
                'season': '%d-%d' % (year, year + 1) if kind == 'withdrawal' else '', 't': t}))
    d = pd.concat(blocks, ignore_index=True).sort_values(['w', 'date'], kind='stable').head(rows)
    d = d.reset_index(drop=True)
    w = d.pop('w').to_numpy()
    t = d.pop('t').to_numpy()
    d.insert(0, 'well', wells[w])
    d['year'] = ''
    d['group'] = _group_of(w)
    d['subgroup'] = _subgroup_of(w)
    d['file'] = SOURCE
    d['sheet'] = d.kind
    d['_row'] = t + 2
    return d, wells


def gdi_frame(rows, wells, rng):
    """Исследования на установившихся режимах: 5–7 режимов, двучлен ΔP² = aQ + bQ² с шумом и редкими выбросами."""
    n = len(wells)
    sizes = rng.integers(5, 8, size=max(1, rows // 5 + 1))
    sizes = sizes[:np.searchsorted(np.cumsum(sizes), rows) + 1]
    studies = len(sizes)
    well = np.arange(studies) % n
    k = np.arange(studies) // n                             # номер исследования скважины
    per_well = math.ceil(studies / n)
    span = (pd.Timestamp('%d-11-01' % (FIRST_YEAR + YEARS)) - pd.Timestamp('%d-11-01' % FIRST_YEAR)).days
    step = max(1, span // per_well)
    start = pd.Timestamp('%d-11-01' % FIRST_YEAR).to_datetime64()
    study_date = start + ((k * step + well % max(1, step)) * np.timedelta64(1, 'D'))
    a0, b0, p0 = rng.uniform(.4, 1.6, n), rng.uniform(.006, .02, n), rng.uniform(70, 95, n)
    age = k / max(1, per_well)
    a = a0[well] * (1 + .15 * age) * rng.normal(1, .03, studies)
    b = b0[well] * (1 + .25 * age) * rng.normal(1, .03, studies)
    month = pd.DatetimeIndex(study_date).month.to_numpy()
    p_res = p0[well] - 6 * age + np.where((month >= 11) | (month <= 4), -3, 3) + rng.normal(0, .4, studies)
    qmax = rng.uniform(150, 320, studies)
    s = np.repeat(np.arange(studies), sizes)
    regime = np.concatenate([np.arange(m) for m in sizes])
    q = np.round(qmax[s] * (regime + 1) / sizes[s] * rng.normal(1, .02, len(s)), 1)
    dp2 = (a[s] * q + b[s] * q * q) * rng.normal(1, .02, len(s))
    dp2 = np.where(rng.random(len(s)) < .01, dp2 * rng.uniform(1.3, 1.8, len(s)), dp2)   # выбросы
    dp2 = np.minimum(dp2, p_res[s] ** 2 * .9)
    p_bh = np.sqrt(p_res[s] ** 2 - dp2)
    year = pd.DatetimeIndex(study_date[s]).year.to_numpy()
    month_s = month[s]
    season_year = np.where(month_s >= 11, year, year - 1)
    withdrawal = (month_s >= 11) | (month_s <= 4)
    d = pd.DataFrame({
        'well': wells[well[s]], 'date': study_date[s], 'q': q, 'p_res': np.round(p_res[s], 2),
        'p_bh': np.round(p_bh, 2), 'dp2': np.round(dp2, 1), 'a_db': np.round(a[s] * 1.01, 4), 'b_db': np.round(b[s], 5),
        'method': np.array(GDI_METHODS, dtype=object)[k[s] % 4 // 3], 'study': (k[s] + 1).astype(str),
        'season': ['%d-%d' % (y, y + 1) if on else '' for y, on in zip(season_year, withdrawal)],
        'group': _group_of(well[s]), 'subgroup': '', 'file': SOURCE, 'sheet': 'ГДИ', '_row': regime + 2})
    return d.head(rows).reset_index(drop=True)


def response_frame(rows, rng):
    """Суточные замеры уровня и приведённого давления в наблюдательных скважинах контрольных горизонтов."""
    dates = pd.date_range('%d-01-01' % FIRST_YEAR, '%d-12-31' % (FIRST_YEAR + YEARS - 1)).values
    series = max(1, math.ceil(rows / (len(dates) * .97)))     # 2 % дней без замера
    wells = _wells(series, start=2001)
    i = np.repeat(np.arange(series), len(dates))
    t = np.tile(np.arange(len(dates)), series)
    doy = np.tile(pd.DatetimeIndex(dates).dayofyear.to_numpy(), series)
    season = np.cos(2 * np.pi * (doy - 30) / 365.25)        # максимум отбора — зимой
    amp = rng.uniform(2, 9, series)
    level = 30 + 2 * (i % 7) + amp[i] * season - .0004 * t + rng.normal(0, .25, len(i))
    pressure = 68 + .4 * (i % 9) + .3 * amp[i] * season + rng.normal(0, .1, len(i))
    gaps = rng.random(len(i)) < .02
    d = pd.DataFrame({'well': wells[i], 'date': np.tile(dates, series), 'horizon': np.array(HORIZONS, dtype=object)[i % 3],
                      'level': np.round(level, 2), 'pressure': np.round(pressure, 2),
                      'group': 'Наблюдательные', 'subgroup': '', 'file': SOURCE, 'sheet': 'Реагирование',
                      '_row': t + 2})
    return d[~gaps].head(rows).reset_index(drop=True)


def pressure_frame(rows, wells, rng):
    """Пары факт / модель, как их собирает быстрый импорт: объект × сценарий × скважина × дата."""
    n = len(wells)
    per_object = np.array_split(np.arange(n), len(OBJECTS))
    combos = len(SCENARIOS) * n
    count = max(1, math.ceil(rows / combos))
    dates = pd.date_range('%d-01-01' % FIRST_YEAR, periods=count, freq='7D').values
    fond = np.where(rng.random(n) < .2, 'Наблюдательные', 'Эксплуатационные').astype(object)
    p0 = rng.uniform(80, 120, n)
    doy = pd.DatetimeIndex(dates).dayofyear.to_numpy()
    seasonal = np.cos(2 * np.pi * (doy - 30) / 365.25)
    parts = []
    for o, idx in enumerate(per_object):
        w = np.repeat(idx, count)
        t = np.tile(np.arange(count), len(idx))
        fact = p0[w] - 10 * seasonal[t] - .01 * t + rng.normal(0, .8, len(w))
        for s, scenario in enumerate(SCENARIOS):
            model = fact + (s - 1) * 1.5 + rng.normal(0, 1 + s, len(w))
            m = model.copy()
            m[rng.random(len(w)) < .005] = np.nan                # нет модели на дату замера
            parts.append(pd.DataFrame({
                'date': dates[t], 'well': wells[w], 'fact': np.round(fact, 2), '_row': t + 2,
                'model': np.round(m, 2), '_model_row': t + 2, 'object': OBJECTS[o], 'scenario': scenario,
                'fond': fond[w], 'group': 'Без группы', 'subgroup': '', 'file': OBJECTS[o] + '.xlsx', 'sheet': scenario}))
    d = pd.concat(parts, ignore_index=True)
    return d.head(rows).reset_index(drop=True)


def large_demo_frames(production=None, gdi=None, response=None, pressure_match=None, seed=2026):
    """Наборы большого демо. ``None`` — объём по умолчанию, 0 — набор не создаётся (кроме отбора и закачки)."""
    sizes = dict(DEFAULTS)
    for name, value in (('production', production), ('gdi', gdi), ('response', response),
                        ('pressure_match', pressure_match)):
        if value is not None:
            sizes[name] = int(value)
    if sizes['production'] < 1:
        raise ValueError('Нужна хотя бы одна строка отбора и закачки')
    rng = np.random.default_rng(seed)
    frames = {}
    frames['production'], wells = production_frame(sizes['production'], rng)
    if sizes['gdi'] > 0:
        frames['gdi'] = gdi_frame(sizes['gdi'], wells, rng)
    if sizes['response'] > 0:
        frames['response'] = response_frame(sizes['response'], rng)
    if sizes['pressure_match'] > 0:
        frames['pressure_match'] = pressure_frame(sizes['pressure_match'], wells, rng)
    return frames


def create_large_demo(store, name=None, settings=None, **sizes):
    """Создаёт демонстрационный проект в хранилище 5.8 / 6 и возвращает его id."""
    from atlas.engine.core.config import DEFAULT_SETTINGS
    frames = large_demo_frames(**sizes)
    total = sum(len(f) for f in frames.values())
    pid = store.create(name or 'Демонстрационный объект (большой, %s строк)' % format(total, ',').replace(',', ' '), demo=True)
    merged = dict(DEFAULT_SETTINGS)
    merged['working_horizons'] = ['Окский']
    merged.update(settings or {})
    store.commit(pid, frames, settings=merged, action='Демонстрационные данные (большой объём)')
    return pid

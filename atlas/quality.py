"""Проверка качества данных: сомнительные значения в таблицах проекта и в загрузке перед сохранением.

Только поиск: ничего не исключается и не исправляется само, решение за инженером. Проверки идут по готовым
таблицам (колонки как в ``atlas.domain``), поэтому одни и те же правила работают и для проекта, и для файлов,
которые ещё не сохранены. Каждая находка — строка: набор, скважина, дата, проверка, значение, пояснение.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

LIMIT = 2000                       # находок одной проверки в таблице: дальше — только счётчик
GAP_DAYS = (3, 45)                 # пропуск в суточных замерах внутри сезона: от и до дней (длиннее — это уже перерыв сезона)
DP2_TOLERANCE = 0.05               # расхождение ΔP² с Рпл² − Рзаб², доля

COLUMNS = ['dataset', 'id', 'well', 'date', 'check', 'level', 'value', 'details']


@dataclass(frozen=True)
class Limits:
    jump: float = 3.0              # скачок дебита: во сколько раз отличается от соседних дней
    pressure_jump: float = 0.3     # скачок давления между замерами горизонта, доля


def _finding(frame: pd.DataFrame, mask, check: str, level: str, value, details: str, dataset: str) -> pd.DataFrame:
    """``value`` — строка, серия по всей таблице или функция от отобранных строк (подпись считается только для находок)."""
    rows = frame[mask]
    if rows.empty:
        return pd.DataFrame(columns=COLUMNS)
    if callable(value):
        values = value(rows)
    else:
        values = value.loc[rows.index] if isinstance(value, pd.Series) else value
    out = pd.DataFrame({
        'dataset': dataset,
        'id': rows['_point_id'].to_numpy() if '_point_id' in rows else '',
        'well': rows['well'].astype(str).to_numpy(),
        'date': pd.to_datetime(rows['date'], errors='coerce').to_numpy(),
        'check': check, 'level': level,
        'value': values.to_numpy() if isinstance(values, pd.Series) else values, 'details': details})
    return out


def _fmt(series: pd.Series, digits: int = 1) -> pd.Series:
    return series.map(lambda v: '' if pd.isna(v) else f'{v:,.{digits}f}'.replace(',', ' ').replace('.', ','))


def _cap(found: pd.DataFrame) -> pd.DataFrame:
    return found.head(LIMIT)


def production(d: pd.DataFrame, limits: Limits) -> list[pd.DataFrame]:
    if d.empty or not {'well', 'date', 'q'} <= set(d.columns):
        return []
    d = d.copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d.sort_values(['well', 'kind', 'date'] if 'kind' in d else ['well', 'date'], kind='stable').reset_index(drop=True)
    keys = [c for c in ('well', 'kind') if c in d]
    out = [_finding(d, d.q.lt(0), 'Отрицательный расход', 'ошибка', lambda r: _fmt(r.q), 'Расход не может быть меньше нуля.', 'production')]
    dup = d.duplicated(keys + ['date'], keep=False) & d.date.notna()
    out.append(_finding(d, dup, 'Повтор даты', 'ошибка', lambda r: _fmt(r.q), 'Для скважины и даты несколько строк: сумма или '
                        'последняя запись — решает правило загрузки, проверьте источник.', 'production'))
    grouped = d.groupby(keys, sort=False)['q']
    prev, nxt = grouped.shift(1), grouped.shift(-1)
    before = pd.concat([grouped.shift(i) for i in (1, 2, 3)], axis=1)
    after = pd.concat([grouped.shift(-i) for i in (1, 2, 3)], axis=1)
    around = pd.concat([before, after], axis=1).where(lambda x: x.gt(0)).median(axis=1)
    ratio = d.q / around
    jump = d.q.gt(0) & around.gt(0) & ((ratio >= limits.jump) | (ratio <= 1 / limits.jump))
    shown = lambda r: ratio[r.index].map(lambda x: '' if pd.isna(x) else (f'в {x:.1f} раза выше' if x >= 1 else f'в {1 / x:.1f} раза ниже').replace('.', ','))
    out.append(_finding(d, jump, 'Скачок дебита', 'внимание', shown, f'Расход отличается от соседних дней не менее чем в {limits.jump:g} раза: '
                        'возможна ошибка единиц, опечатка или остановка.', 'production'))
    lone_zero = d.q.eq(0) & prev.gt(0) & nxt.gt(0)
    out.append(_finding(d, lone_zero, 'Ноль посреди отбора', 'внимание', '0', 'Нулевой расход между двумя днями с расходом: '
                        'остановка на сутки или пропуск записи.', 'production'))
    if 'season' in d:
        step = d.groupby(keys + ['season'], sort=False)['date'].diff().dt.days
        gap = step.gt(GAP_DAYS[0]) & step.le(GAP_DAYS[1])
        out.append(_finding(d, gap, 'Пропуск замеров', 'внимание', lambda r: step[r.index].map(lambda n: '' if pd.isna(n) else f'{n - 1:.0f} дн.'),
                            'Между соседними записями сезона нет суточных данных: график проведёт линию через пропуск.',
                            'production'))
    return [_cap(f) for f in out]


def gdi(d: pd.DataFrame, limits: Limits) -> list[pd.DataFrame]:
    if d.empty or 'well' not in d:
        return []
    d = d.reset_index(drop=True)
    out = []
    if {'p_res', 'p_bh'} <= set(d.columns):
        bad = d.p_bh.notna() & d.p_res.notna() & d.p_bh.ge(d.p_res)
        out.append(_finding(d, bad, 'Рзаб не ниже Рпл', 'ошибка', lambda r: _fmt(r.p_bh, 2) + ' / ' + _fmt(r.p_res, 2),
                            'Забойное давление должно быть меньше пластового (значение: Рзаб / Рпл), иначе ΔP² не положителен.', 'gdi'))
        if 'dp2' in d:
            expected = d.p_res ** 2 - d.p_bh ** 2
            diff = (d.dp2 - expected).abs() / expected.abs().where(expected.abs() > 1e-9)
            off = d.dp2.notna() & diff.gt(DP2_TOLERANCE) & d.p_bh.lt(d.p_res)
            out.append(_finding(d, off, 'ΔP² не сходится с давлениями', 'внимание',
                                lambda r: _fmt(r.dp2, 1) + ' вместо ' + _fmt(expected[r.index], 1),
                                f'ΔP² отличается от Рпл² − Рзаб² более чем на {DP2_TOLERANCE:.0%}: проверьте единицы давления.', 'gdi'))
    if 'q' in d:
        out.append(_finding(d, d.q.le(0), 'Расход не положителен', 'ошибка', lambda r: _fmt(r.q, 1), 'Точка не участвует в подборе a и b.', 'gdi'))
    if 'dp2' in d:
        out.append(_finding(d, d.dp2.le(0), 'ΔP² не положителен', 'ошибка', lambda r: _fmt(r.dp2, 1), 'Точка не участвует в подборе a и b.', 'gdi'))
    keys = [c for c in ('well', 'date', 'method', 'study', 'q') if c in d]
    out.append(_finding(d, d.duplicated(keys, keep=False), 'Повтор точки', 'внимание', '', 'Одинаковые скважина, дата, метод, '
                        'исследование и расход встречаются несколько раз.', 'gdi'))
    return [_cap(f) for f in out]


def response(d: pd.DataFrame, limits: Limits) -> list[pd.DataFrame]:
    if d.empty or 'well' not in d:
        return []
    d = d.copy().reset_index(drop=True)
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    keys = [c for c in ('well', 'horizon') if c in d]
    out = [_finding(d, d.duplicated(keys + ['date'], keep=False) & d.date.notna(), 'Повтор даты', 'ошибка', '',
                    'Для скважины и горизонта на одну дату несколько замеров.', 'response')]
    if 'pressure' in d:
        out.append(_finding(d, d.pressure.le(0), 'Давление не положительно', 'ошибка', lambda r: _fmt(r.pressure, 2), '', 'response'))
        d = d.sort_values(keys + ['date'], kind='stable').reset_index(drop=True)
        prev = d.groupby(keys, sort=False)['pressure'].shift(1)
        change = (d.pressure - prev).abs() / prev.where(prev > 0)
        jump = change.gt(limits.pressure_jump)
        out.append(_finding(d, jump, 'Скачок давления', 'внимание', lambda r: change[r.index].map(lambda c: '' if pd.isna(c) else f'{c:.0%}'),
                            f'Давление изменилось более чем на {limits.pressure_jump:.0%} между соседними замерами горизонта.', 'response'))
    return [_cap(f) for f in out]


def units(frames: dict[str, pd.DataFrame]) -> list[pd.DataFrame]:
    """Давление в других единицах: кгс/см² для ПХГ — десятки и сотни, МПа — единицы.

    Медиана считается по каждому файлу отдельно: файл в МПа внутри набора в кгс/см² иначе не виден."""
    rows = []
    for name, column in (('gdi', 'p_res'), ('response', 'pressure'), ('pressure_match', 'fact')):
        d = frames.get(name)
        if d is None or column not in d or d[column].dropna().empty:
            continue
        keys = d['file'].fillna('').astype(str) if 'file' in d else pd.Series('', index=d.index)
        for file, part in d.groupby(keys, sort=False):
            values = part[column].dropna()
            if values.empty:
                continue
            median = float(values.median())
            where = f' (файл «{file}»)' if file and keys.nunique() > 1 else ''
            if median < 15:
                rows.append((name, f'медиана {median:.1f}'.replace('.', ','), 'Давление похоже на МПа, а проект работает в кгс/см²: '
                             'при загрузке выберите единицы давления «МПа» или укажите единицу в заголовке колонки' + where + '.'))
            elif median > 1000:
                rows.append((name, f'медиана {median:.0f}', 'Давление слишком велико для кгс/см²: возможно, указано в других единицах' + where + '.'))
    return [pd.DataFrame({'dataset': n, 'id': '', 'well': '', 'date': pd.NaT, 'check': 'Единицы давления', 'level': 'внимание',
                          'value': v, 'details': t} for n, v, t in rows)] if rows else []


CHECKS = {'production': production, 'gdi': gdi, 'response': response}


def scan(frames: dict[str, pd.DataFrame], limits: Limits | None = None) -> pd.DataFrame:
    """Все находки по таблицам ``{имя набора: данные}``; порядок — по набору, проверке, скважине, дате."""
    limits = limits or Limits()
    found: list[pd.DataFrame] = []
    for name, check in CHECKS.items():
        if name in frames:
            found.extend(check(frames[name], limits))
    found.extend(units(frames))
    found = [f for f in found if not f.empty]
    if not found:
        return pd.DataFrame(columns=COLUMNS).astype({'date': 'datetime64[ns]'})
    out = pd.concat(found, ignore_index=True)
    out['date'] = pd.to_datetime(out['date'], errors='coerce')
    order = {'ошибка': 0, 'внимание': 1}
    out['_o'] = out['level'].map(order)
    out = out.sort_values(['_o', 'dataset', 'check', 'well', 'date'], kind='stable').drop(columns='_o')
    return out.reset_index(drop=True)[COLUMNS]


def summary(found: pd.DataFrame) -> pd.DataFrame:
    """Сколько находок каждой проверки: для короткой сводки над таблицами."""
    if found.empty:
        return pd.DataFrame(columns=['dataset', 'check', 'level', 'count'])
    out = found.groupby(['dataset', 'check', 'level'], sort=False).size().reset_index(name='count')
    out['_o'] = out['level'].map({'ошибка': 0, 'внимание': 1})
    return out.sort_values(['_o', 'count'], ascending=[True, False], kind='stable').drop(columns='_o').reset_index(drop=True)


def _runs(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Серии подряд идущих суток: на ключ — число серий, самая длинная, начало и конец последней."""
    if frame.empty:
        return pd.DataFrame(columns=keys + ['episodes', 'longest', 'last_start', 'last_end'])
    f = frame[keys + ['date']].drop_duplicates().sort_values(keys + ['date']).reset_index(drop=True)
    step = f.groupby(keys, sort=False)['date'].diff().dt.days
    f['run'] = (step.ne(1)).cumsum()
    runs = f.groupby(keys + ['run'], sort=False)['date'].agg(['min', 'max', 'size']).reset_index()
    runs = runs.sort_values(keys + ['max'])
    out = runs.groupby(keys, sort=False).agg(episodes=('size', 'size'), longest=('size', 'max'),
                                              last_start=('min', 'last'), last_end=('max', 'last')).reset_index()
    return out


def open_without_flow(production: pd.DataFrame, mass_share: float = 0.5, mass_min_wells: int = 3):
    """Сутки, когда скважина открыта (время работы > 0), а расход равен нулю.

    Такие строки не ошибка и не удаляются: это сигнал о скважине (гидратная пробка, обводнение, закрытая арматура)
    или о замерном узле. Возвращает ``None``, если в данных нет времени работы, иначе словарь таблиц:
    ``wells`` — по скважинам, ``groups`` — по группам (сутки, когда без расхода сразу многие скважины группы),
    ``months`` — по месяцам. Расход равен нулю — именно ``q == 0``; пропуск расхода сюда не входит."""
    if production is None or production.empty or 'hours' not in production.columns:
        return None
    f = production.copy()
    f['hours'] = pd.to_numeric(f['hours'], errors='coerce')
    f['date'] = pd.to_datetime(f['date'], errors='coerce')
    f = f.dropna(subset=['hours', 'date', 'q'])
    if f.empty:
        return None
    if 'kind' not in f:
        f['kind'] = 'withdrawal'
    if 'group' not in f:
        f['group'] = ''
    f['well'] = f['well'].astype(str)
    opened = f[f['hours'] > 0].copy()
    if opened.empty:
        return {'wells': pd.DataFrame(), 'groups': pd.DataFrame(), 'months': pd.DataFrame(), 'open_days': 0, 'zero_days': 0}
    opened['zero'] = opened['q'].eq(0)
    zero = opened[opened['zero']]
    keys = ['well', 'kind']
    wells = opened.groupby(keys, sort=False).agg(open_days=('zero', 'size'), zero_days=('zero', 'sum')).reset_index()
    wells = wells[wells['zero_days'] > 0]
    runs = _runs(zero, keys)
    wells = wells.merge(runs, on=keys, how='left')
    last_group = f.sort_values('date').groupby('well')['group'].last()
    wells['group'] = wells['well'].map(last_group)
    wells['share'] = wells['zero_days'] / wells['open_days'] * 100
    first = zero.groupby(keys)['date'].min().rename('first').reset_index()
    wells = wells.merge(first, on=keys, how='left')
    wells = wells.sort_values(['zero_days', 'share'], ascending=False).reset_index(drop=True)
    wells = wells[['well', 'group', 'kind', 'open_days', 'zero_days', 'share', 'episodes', 'longest', 'first',
                   'last_end']].rename(columns={'last_end': 'last'})

    gday = opened.groupby(['group', 'kind', 'date'], sort=False).agg(open_wells=('zero', 'size'),
                                                                      zero_wells=('zero', 'sum')).reset_index()
    gday['share'] = gday['zero_wells'] / gday['open_wells']
    gday['mass'] = (gday['open_wells'] >= mass_min_wells) & (gday['share'] >= mass_share)
    mass = gday[gday['mass']]
    g = gday.groupby(['group', 'kind'], sort=False).agg(days=('date', 'size'), max_share=('share', 'max')).reset_index()
    gm = mass.groupby(['group', 'kind'], sort=False).agg(mass_days=('date', 'size'), last=('date', 'max')).reset_index()
    gr = _runs(mass, ['group', 'kind'])[['group', 'kind', 'longest']].rename(columns={'longest': 'mass_longest'})
    groups = g.merge(gm, on=['group', 'kind'], how='left').merge(gr, on=['group', 'kind'], how='left')
    groups['mass_days'] = pd.to_numeric(groups['mass_days'], errors='coerce').fillna(0).astype(int)
    groups['mass_longest'] = pd.to_numeric(groups['mass_longest'], errors='coerce').fillna(0).astype(int)
    groups['max_share'] = groups['max_share'] * 100
    groups = groups.sort_values('mass_days', ascending=False).reset_index(drop=True)

    opened['month'] = opened['date'].dt.to_period('M').dt.to_timestamp()
    months = opened.groupby(['month', 'kind'], sort=True).agg(open_days=('zero', 'size'), zero_days=('zero', 'sum')).reset_index()
    months['share'] = months['zero_days'] / months['open_days'] * 100
    return {'wells': wells, 'groups': groups, 'months': months, 'open_days': int(len(opened)), 'zero_days': int(len(zero))}

"""Фонд скважин по сезонам: средний расход, форма кривой, раскрытие КРУ, фон группы и объекта, ГДИ.

Чистые функции над суточными таблицами, без интерфейса. Расход — тыс. м³/сут, раскрытие КРУ — % (ЭЛПРО, Y), сезон —
период суточной эксплуатации, как в ``well_analysis``. Пропуск не считается нулём: сутки без записи в средние не входят.
Изменения считаются к предыдущему сезону, в котором у скважины была работа. Результат — основание для инженера, не вывод.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_DAYS = 10        # минимум суток с расходом для тренда и связи с КРУ
FLAT_PERCENT = 5.0   # тренд в пределах ±5 % за 30 суток — кривая ровная
COLUMNS = ['well', 'group', 'period', 'gas_days', 'working_days', 'mean_rate', 'kru_days', 'kru_mean', 'high_days',
           'rate_high', 'kru_corr', 'trend', 'shape', 'group_rate', 'object_rate', 'gdi_q', 'gdi_studies',
           'prev_period', 'd_rate', 'd_high', 'd_group', 'd_object']


def _pct(now, before) -> float:
    """Изменение в процентах; пропуск или нулевая база — пропуск."""
    if pd.isna(now) or pd.isna(before) or before <= 0:
        return np.nan
    return (now / before - 1) * 100


def background(daily: pd.DataFrame, seasons: list[str]) -> tuple[dict, dict]:
    """Средний суточный расход объекта по сезонам и группы по сезонам (тыс. м³/сут), по суткам с суммой."""
    d = daily[daily.period.isin(seasons)]
    obj = d[['date', 'period', 'object_volume']].drop_duplicates('date')
    object_rate = (obj.groupby('period').object_volume.mean() / 1000).to_dict()
    grp = d[['group', 'date', 'period', 'group_volume']].drop_duplicates(['group', 'date'])
    group_rate = {(g, p): v for (g, p), v in (grp.groupby(['group', 'period']).group_volume.mean() / 1000).items()}
    return object_rate, group_rate


def _shape(working: pd.DataFrame) -> tuple[float, str]:
    """Тренд расхода в работающие сутки, % за 30 суток от среднего, и форма кривой словами."""
    if len(working) < MIN_DAYS or working.rate.mean() <= 0:
        return np.nan, '—'
    x = (working.date - working.date.min()).dt.days.to_numpy(float)
    slope = np.polyfit(x, working.rate.to_numpy(float), 1)[0]
    trend = slope * 30 / working.rate.mean() * 100
    if trend > FLAT_PERCENT:
        return trend, 'растёт'
    return trend, 'падает' if trend < -FLAT_PERCENT else 'ровная'


def _kru_corr(working: pd.DataFrame) -> float:
    """Связь раскрытия КРУ и расхода по суткам (ранговая корреляция); мало суток или нет разброса — пропуск."""
    paired = working.dropna(subset=['y'])
    if len(paired) < MIN_DAYS or paired.y.nunique() < 2 or paired.rate.nunique() < 2:
        return np.nan
    return paired.y.rank().corr(paired.rate.rank())


def seasonal(daily: pd.DataFrame, seasons: list[str], elpro: pd.DataFrame | None = None,
             gdi: pd.DataFrame | None = None, wells: list[str] | None = None, high_kru: float = 50.0) -> pd.DataFrame:
    """Строка на скважину и сезон (сезоны — в порядке ``seasons``, от старых к новым).

    ``daily`` — ``well_analysis`` daily одного режима: well, date, period, group, gas_volume_m3 (м³/сут), object_volume,
    group_volume. ``elpro`` — ЭЛПРО режима: well, date, y (КРУ, %). ``gdi`` — история ГДИ по скважинам: well, date,
    reliable, q_reference (тыс. м³/сут при общем ΔP²). ``high_kru`` — порог «высокого» раскрытия КРУ, %.
    """
    seasons = list(seasons)
    if daily.empty or not seasons:
        return pd.DataFrame(columns=COLUMNS)
    d = daily[daily.period.isin(seasons)].assign(well=lambda x: x.well.astype(str))
    if wells is not None:
        d = d[d.well.isin([str(w) for w in wells])]
    if d.empty:
        return pd.DataFrame(columns=COLUMNS)
    object_rate, group_rate = background(daily, seasons)
    date_period = daily[daily.period.isin(seasons)][['date', 'period']].drop_duplicates('date')

    gas = pd.DataFrame({'well': d.well, 'date': d.date, 'period': d.period, 'rate': d.gas_volume_m3 / 1000, 'y': np.nan})
    parts = [gas]
    if elpro is not None and not elpro.empty:
        e = elpro.assign(well=elpro.well.astype(str), date=pd.to_datetime(elpro.date).dt.normalize())
        e = e.groupby(['well', 'date'], as_index=False).y.mean().merge(date_period, on='date')
        e = e[e.well.isin(d.well.unique())]
        parts.append(e.assign(rate=np.nan, y=e.y.clip(0, 100))[['well', 'date', 'period', 'rate', 'y']])
    # Сутки с расходом и сутки с КРУ — одна строка на скважину и дату; пропуск одной величины не заменяется нулём.
    frame = pd.concat(parts, ignore_index=True).groupby(['well', 'date', 'period'], as_index=False).agg(
        rate=('rate', 'first'), y=('y', 'first'))
    frame['working'] = frame.rate.gt(0)
    frame['high'] = frame.working & frame.y.ge(high_kru)

    res = frame.groupby(['well', 'period']).agg(gas_days=('rate', 'count'), working_days=('working', 'sum'),
                                                kru_days=('y', 'count'), kru_mean=('y', 'mean'),
                                                high_days=('high', 'sum'))
    res = res.join(frame[frame.working].groupby(['well', 'period']).rate.mean().rename('mean_rate'))
    res = res.join(frame[frame.high].groupby(['well', 'period']).rate.mean().rename('rate_high')).reset_index()
    shapes, corrs = {}, {}
    for key, g in frame[frame.working].groupby(['well', 'period']):
        shapes[key] = _shape(g)
        corrs[key] = _kru_corr(g)
    keys = list(zip(res.well, res.period))
    res['trend'] = [shapes.get(k, (np.nan, '—'))[0] for k in keys]
    res['shape'] = [shapes.get(k, (np.nan, '—'))[1] for k in keys]
    res['kru_corr'] = [corrs.get(k, np.nan) for k in keys]
    groups = d.drop_duplicates('well').set_index('well').group
    res = _with_grid(res, seasons, groups)
    res['group_rate'] = [group_rate.get((g, p), np.nan) for g, p in zip(res.group, res.period)]
    res['object_rate'] = res.period.map(object_rate)
    res['gdi_q'], res['gdi_studies'] = _gdi_by_season(gdi, daily[daily.period.isin(seasons)], res)
    return _compare(res, object_rate, group_rate, seasons)


def _gdi_by_season(gdi: pd.DataFrame | None, daily: pd.DataFrame, res: pd.DataFrame):
    """Медиана Q при общем ΔP² по надёжным исследованиям скважины в сезоне и число таких исследований."""
    q = pd.Series(np.nan, index=res.index)
    n = pd.Series(0, index=res.index)
    if gdi is None or gdi.empty:
        return q, n
    h = gdi[gdi.reliable & gdi.q_reference.notna()].assign(well=lambda x: x.well.astype(str))
    spans = daily.groupby('period').date.agg(['min', 'max'])
    for period, span in spans.iterrows():
        part = h[h.date.between(span['min'], span['max'])].groupby('well').q_reference
        mask = res.period.eq(period)
        q[mask] = res.loc[mask, 'well'].map(part.median()).to_numpy()
        n[mask] = res.loc[mask, 'well'].map(part.count()).fillna(0).astype(int).to_numpy()
    return q, n


def _with_grid(res: pd.DataFrame, seasons: list[str], groups: pd.Series) -> pd.DataFrame:
    """Все сезоны каждой скважины: сезон без записей — строка с пропусками и нулевой работой."""
    wells = list(dict.fromkeys(res.well))
    index = pd.MultiIndex.from_product([wells, seasons], names=['well', 'period'])
    res = res.set_index(['well', 'period']).reindex(index).reset_index()
    counts = ['gas_days', 'working_days', 'kru_days', 'high_days']
    res[counts] = res[counts].fillna(0).astype(int)
    res['group'] = res.well.map(groups).fillna('Без группы')
    return res


def _compare(res: pd.DataFrame, object_rate: dict, group_rate: dict, seasons: list[str]) -> pd.DataFrame:
    """Изменения к предыдущему сезону, в котором у скважины была работа; фон группы и объекта — за те же сезоны."""
    order = {p: i for i, p in enumerate(seasons)}
    res = res.assign(_order=res.period.map(order)).sort_values(['well', '_order']).reset_index(drop=True)
    res['prev_period'] = None
    for column in ('d_rate', 'd_high', 'd_group', 'd_object'):
        res[column] = np.nan
    last: dict = {}
    for i, r in res.iterrows():
        prev = last.get(r.well)
        if prev is not None:
            p = prev.period
            res.at[i, 'prev_period'] = p
            res.at[i, 'd_rate'] = _pct(r.mean_rate, prev.mean_rate)
            res.at[i, 'd_high'] = _pct(r.rate_high, prev.rate_high)
            res.at[i, 'd_group'] = _pct(group_rate.get((r.group, r.period), np.nan), group_rate.get((r.group, p), np.nan))
            res.at[i, 'd_object'] = _pct(object_rate.get(r.period, np.nan), object_rate.get(p, np.nan))
        if pd.notna(r.mean_rate):
            last[r.well] = r
    return res.drop(columns='_order')[COLUMNS]

"""Показатели динамики скважины для «Комплексного анализа продуктивности скважин».

Всё считается по суточным данным отбора за два последних сезона: накопленный расход на одинаковом отрезке сезона, согласованность
недельной динамики скважины с группой и объектом, отклик расхода на раскрытие КРУ (ЭЛПРО). Это подсказки с видимыми числами,
решение — за инженером. Сезон без данных — пропуск, не нуль.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._production import NEUTRAL_PREFIXES

METRIC_COLUMNS = ['cum_last', 'cum_prev', 'cum_days', 'cum_change', 'cum_group_change', 'cum_gap', 'sync_group', 'sync_obj', 'slope_well', 'slope_group',
                  'slope_obj', 'slope_gap_group', 'slope_gap_obj', 'open_last', 'open_prev', 'open_change', 'eff_last', 'eff_prev', 'eff_change', 'eff_gap', 'open_corr']
STEP_MIN = 3          # меньше трёх недельных шагов — совпадение динамики не оцениваем
DAYS_MIN = 14         # и короче двух недель ряда — тоже
FLAT = 0.01           # недельное изменение индекса меньше 1% считаем «без изменения»


def withdrawal_days(prod: pd.DataFrame) -> pd.DataFrame:
    """Дни отбора с расходом > 0 и названием сезона; столбец сезона — ``period``, ``hours`` — часы работы (NaN, если их нет в БД)."""
    if prod is None or prod.empty or 'q' not in prod:
        return pd.DataFrame(columns=['well', 'date', 'q', 'period', 'hours'])
    col = 'period' if 'period' in prod else 'season'
    df = prod[prod.kind.eq('withdrawal') & prod.q.gt(0) & prod[col].notna()].copy()
    df = df[~df[col].astype(str).str.startswith(NEUTRAL_PREFIXES) & df[col].astype(str).ne('')]
    df['period'] = df[col].astype(str)
    df['well'] = df.well.astype(str)
    df['date'] = pd.to_datetime(df.date).dt.normalize()
    df['hours'] = pd.to_numeric(df['hours'], errors='coerce') if 'hours' in df else np.nan       # часы работы из БД расходов (старт скважины)
    return df[['well', 'date', 'q', 'period', 'hours']]


def season_order(df: pd.DataFrame) -> list[str]:
    """Сезоны отбора по дате начала (от раннего к позднему)."""
    return [] if df.empty else df.groupby('period').date.min().sort_values().index.tolist()


def last_two(df: pd.DataFrame, base: str | None = None) -> tuple[str | None, str | None]:
    """Сезон анализа и предыдущий за ним. ``base`` — выбранный инженером сезон; не задан или без данных — самый поздний."""
    order = season_order(df)
    if not order:
        return None, None
    i = order.index(str(base)) if base is not None and str(base) in order else len(order) - 1
    return order[i], (order[i - 1] if i > 0 else None)


def _slope_pct(index: pd.Series) -> float:
    """Наклон индекса расхода, % от среднего за сезон на 30 суток."""
    days = (index.index - index.index[0]).days.to_numpy(dtype=float)
    return float(np.polyfit(days, index.to_numpy(dtype=float), 1)[0] * 30 * 100) if len(index) >= 2 and days.max() > 0 else np.nan


def _weekly_sync(a: pd.Series, b: pd.Series) -> float:
    """Доля недельных шагов, где скважина и эталон движутся в одну сторону (шаги без изменения не считаются), %."""
    wa, wb = a.resample('7D').mean().diff().dropna(), b.resample('7D').mean().diff().dropna()
    common = wa.index.intersection(wb.index)
    wa, wb = wa.loc[common], wb.loc[common]
    moving = (wa.abs() > FLAT) & (wb.abs() > FLAT)
    if moving.sum() < STEP_MIN:
        return np.nan
    return float((np.sign(wa[moving]) == np.sign(wb[moving])).mean() * 100)


def cumulative(days: pd.DataFrame, last: str | None, prev: str | None, group_of: dict[str, str]) -> pd.DataFrame:
    """Накопленный расход скважины (млн м³) за один и тот же отрезок от СТАРТА скважины в сезоне (первая дата с часами работы не 0, иначе с расходом):
    последний и предыдущий сезоны, изменение и отставание от группы. Длина отрезка у скважины одна для обоих сезонов: сезон мог ещё идти, а скважина стартовать позже начала сезона."""
    cols = ['well', 'cum_last', 'cum_prev', 'cum_days', 'cum_change', 'cum_group_change', 'cum_gap']
    if last is None:
        return pd.DataFrame(columns=cols)
    seasons = [p for p in (last, prev) if p is not None]
    begin, left = {}, {}
    for p in seasons:
        d = days[days.period.eq(p)]
        starts = work_starts(days, p)
        begin[p] = starts
        left[p] = (d.date.max() - starts).dt.days + 1                      # сколько суток есть у скважины от её старта до конца данных сезона
    wells = sorted(days.well.unique())
    n = pd.Series({w: min(int(left[p].get(w, 0)) for p in seasons) for w in wells})
    total = {}
    for p in seasons:
        d = days[days.period.eq(p)]
        lim = d.well.map(begin[p]) + pd.to_timedelta(d.well.map(n).fillna(0), unit='D')
        total[p] = d[d.date.lt(lim)].groupby('well').q.sum() / 1e3
    out = pd.DataFrame({'well': wells})
    out['cum_last'] = out.well.map(total[last])
    out['cum_prev'] = out.well.map(total[prev]) if prev is not None else np.nan
    out['cum_days'] = out.well.map(n)
    out['cum_change'] = (out.cum_last - out.cum_prev) / out.cum_prev * 100
    out['cum_group_change'] = out.assign(g=out.well.map(lambda w: group_of.get(w, ''))).groupby('g').cum_change.transform('median')
    out['cum_gap'] = out.cum_change - out.cum_group_change
    return out[cols]


def dynamics(days: pd.DataFrame, last: str | None, group_of: dict[str, str]) -> pd.DataFrame:
    """Согласованность динамики внутри последнего сезона: сутки каждой скважины делятся на её средний расход (индекс), затем
    индекс скважины сравнивается с индексом группы и объекта. ``sync_*`` — доля совпавших недельных шагов, %; ``slope_*`` — тренд, % на 30 суток;
    ``slope_gap_obj`` — тренд скважины минус тренд объекта (п.п.)."""
    cols = ['well', 'sync_group', 'sync_obj', 'slope_well', 'slope_group', 'slope_obj', 'slope_gap_group', 'slope_gap_obj']
    if last is None:
        return pd.DataFrame(columns=cols)
    d = days[days.period.eq(last)].copy()
    d['idx'] = d.q / d.groupby('well').q.transform('mean')
    d['group'] = d.well.map(lambda w: group_of.get(w, ''))
    wide = d.pivot_table(index='date', columns='well', values='idx', aggfunc='mean').sort_index()
    obj = wide.mean(axis=1)
    groups = {g: wide[list(ws)].mean(axis=1) for g, ws in d.groupby('group').well.unique().items()}
    s_obj = _slope_pct(obj)
    rows = []
    for w in wide.columns:
        s = wide[w].dropna()
        g = groups.get(group_of.get(w, ''), obj)
        if len(s) < DAYS_MIN:
            rows.append((w, np.nan, np.nan, np.nan, np.nan, s_obj, np.nan, np.nan))
            continue
        sw, sg = _slope_pct(s), _slope_pct(g)
        rows.append((w, _weekly_sync(s, g), _weekly_sync(s, obj), sw, sg, s_obj, sw - sg, sw - s_obj))
    return pd.DataFrame(rows, columns=cols)


def kru_response(elpro: pd.DataFrame | None, days: pd.DataFrame, last: str | None, prev: str | None, group_of: dict[str, str]) -> pd.DataFrame:
    """Раскрытие КРУ (ЭЛПРО, ``y``, %) и отклик расхода (расход — из БД суточных расходов, не из ЭЛПРО): среднее раскрытие по сезонам, «расход на 1% раскрытия», его изменение и отставание от медианы группы (расход от раскрытия нелинеен, поэтому сравнение с группой).
    Больше раскрытие — должен быть больше расход; если расход падает при том же или большем раскрытии, продуктивность снизилась."""
    cols = ['well', 'open_last', 'open_prev', 'open_change', 'eff_last', 'eff_prev', 'eff_change', 'eff_gap', 'open_corr']
    if elpro is None or elpro.empty or 'y' not in elpro or last is None:
        return pd.DataFrame(columns=cols)
    e = elpro[elpro.kind.eq('withdrawal')] if 'kind' in elpro else elpro
    e = e.assign(well=e.well.astype(str), date=pd.to_datetime(e.date).dt.normalize())
    e = e[e.y.gt(0)].drop_duplicates(['well', 'date'])[['well', 'date', 'y']]

    def window(p):
        """Дни сезона: расход — из нормированной БД суточных расходов (как в модуле производительности), раскрытие КРУ — из ЭЛПРО."""
        return days[days.period.eq(p)].merge(e, on=['well', 'date']) if p is not None else days.iloc[0:0].assign(y=np.nan)
    el, ep = window(last), window(prev)
    out = pd.DataFrame({'well': sorted(el.well.unique())})
    out['open_last'] = out.well.map(el.groupby('well').y.mean())
    out['open_prev'] = out.well.map(ep.groupby('well').y.mean()) if not ep.empty else np.nan
    out['open_change'] = (out.open_last - out.open_prev) / out.open_prev * 100
    out['eff_last'] = out.well.map(el.groupby('well').q.mean()) / 1e3 / out.open_last
    out['eff_prev'] = out.well.map(ep.groupby('well').q.mean()) / 1e3 / out.open_prev if not ep.empty else np.nan
    out['eff_change'] = (out.eff_last - out.eff_prev) / out.eff_prev * 100
    out['eff_gap'] = out.eff_change - out.assign(g=out.well.map(lambda w: group_of.get(w, ''))).groupby('g').eff_change.transform('median')
    corr = el.groupby('well').apply(lambda g: g.q.corr(g.y) if len(g) >= DAYS_MIN and g.y.nunique() > 1 else np.nan, include_groups=False)
    out['open_corr'] = out.well.map(corr)
    return out[cols]


BASE_DAYS = 14        # опорный уровень «скважина к объекту» — медиана первых двух недель сезона
OPEN_TOL = 0.05       # раскрытие КРУ считается не уменьшенным, если оно не ниже опорного больше чем на 5%


def _season_wide(days: pd.DataFrame, last: str | None) -> pd.DataFrame:
    """Индекс расхода (сутки / среднее скважины за сезон) по календарным дням последнего сезона; пропуск дня — NaN."""
    d = days[days.period.eq(last)]
    wide = d.assign(idx=d.q / d.groupby('well').q.transform('mean')).pivot_table(index='date', columns='well', values='idx', aggfunc='mean').sort_index()
    return wide.reindex(pd.date_range(wide.index.min(), wide.index.max()))


def _smooth(x: pd.DataFrame | pd.Series):
    return x.rolling(7, min_periods=3).mean()


def _open_wide(elpro: pd.DataFrame | None, index: pd.DatetimeIndex, last_days: pd.DataFrame) -> pd.DataFrame | None:
    """Раскрытие КРУ (``y``), нормированное на среднее скважины за сезон, на тех же днях; нет ЭЛПРО — None."""
    if elpro is None or elpro.empty or 'y' not in elpro:
        return None
    e = elpro[elpro.kind.eq('withdrawal')] if 'kind' in elpro else elpro
    e = e.assign(well=e.well.astype(str), date=pd.to_datetime(e.date).dt.normalize())
    e = e[e.y.gt(0) & e.date.between(index.min(), index.max())]
    if e.empty:
        return None
    e = e.assign(idx=e.y / e.groupby('well').y.transform('mean'))
    return e.pivot_table(index='date', columns='well', values='idx', aggfunc='mean').reindex(index)


def _runs(mask: pd.Series, min_days: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    out, start = [], None
    for day, on in mask.items():
        if on and start is None:
            start = day
        if not on and start is not None:
            if (day - start).days >= min_days:
                out.append((start, day - pd.Timedelta(days=1)))
            start = None
    if start is not None and (mask.index[-1] - start).days + 1 >= min_days:
        out.append((start, mask.index[-1]))
    return out


def work_starts(days: pd.DataFrame, last: str | None) -> pd.Series:
    """Старт работы скважины в сезоне: первая дата, когда часы работы из БД расходов не равны нулю; нет часов — первая дата с расходом."""
    d = days[days.period.eq(last)]
    any_day = d.groupby('well').date.min()
    return d[d.hours.fillna(0).gt(0)].groupby('well').date.min().reindex(any_day.index).fillna(any_day).rename('start')


def productivity_intervals(days: pd.DataFrame, last: str | None, elpro: pd.DataFrame | None, min_days: int = 14, drop: float = 15.0,
                           tail_days: int = 14, ramp_days: int = 7, low_share: float = 20.0, confirm: int = 2, need_open: bool = True) -> pd.DataFrame:
    """Интервалы последнего сезона, где продуктивность скважины, возможно, снизилась: расход (сглаженный за 7 суток) относительно объекта ниже
    опорного уровня первых двух недель больше чем на ``drop`` %, держится не меньше ``min_days`` суток, а раскрытие КРУ при этом не уменьшено.
    Чтобы не принимать за снижение переходные режимы, из ряда исключаются: дни до старта скважины (первые часы работы не равны нулю) и ``ramp_days`` суток после
    него (выход на режим), последние ``tail_days`` суток ряда (остановка, закрытие, конец сезона), дни с расходом ниже ``low_share`` % от медианы скважины.
    ``confirmed`` — интервал не короче ``confirm`` × ``min_days`` суток и (при ``need_open``) подтверждён данными раскрытия КРУ (иначе режим не сопоставим).
    Столбцы: well, start, end, days, depth (максимальное падение, %), confirmed, why (чего не хватает для подтверждения)."""
    cols = ['well', 'start', 'end', 'days', 'depth', 'confirmed', 'why']
    if last is None:
        return pd.DataFrame(columns=cols)
    wide = _season_wide(days, last)
    starts = work_starts(days, last)
    for w in wide.columns:                                                  # переходные режимы не участвуют ни в объекте, ни в скважине
        col = wide[w]
        valid = col.dropna()
        if valid.empty:
            continue
        begin = starts.get(w, valid.index[0]) + pd.Timedelta(days=int(ramp_days))
        finish = valid.index[-1] - pd.Timedelta(days=int(tail_days))
        keep = (col.index >= begin) & (col.index <= finish) & (col >= valid.median() * low_share / 100)
        wide[w] = col.where(keep)
    sm = _smooth(wide)
    obj = sm.mean(axis=1)
    opening = _open_wide(elpro, wide.index, days)
    rows = []
    for w in wide.columns:
        rel = (sm[w] / obj).where(sm[w].notna())
        base = rel.dropna().iloc[:BASE_DAYS].median()
        if not np.isfinite(base) or base <= 0:
            continue
        low = rel < base * (1 - drop / 100)
        has_open = opening is not None and w in opening and opening[w].notna().sum() >= BASE_DAYS
        if has_open:
            o = _smooth(opening[w])
            o_base = o.dropna().iloc[:BASE_DAYS].median()
            low &= ~(o < o_base * (1 - OPEN_TOL))       # раскрытие уменьшили — падение расхода объясняется режимом, не продуктивностью
        for start, end in _runs(low.fillna(False), int(min_days)):
            depth = (1 - (rel[start:end] / base).min()) * 100
            n = (end - start).days + 1
            why = []
            if n < int(confirm) * int(min_days):
                why.append(f'короче {int(confirm) * int(min_days)} сут')
            if need_open and not has_open:
                why.append('нет данных раскрытия КРУ: режим не сопоставлен')
            rows.append((w, start, end, n, float(depth), not why, '; '.join(why)))
    return pd.DataFrame(rows, columns=cols)


def well_curves(days: pd.DataFrame, last: str | None, elpro: pd.DataFrame | None, group_of: dict[str, str], well: str) -> pd.DataFrame:
    """Ряды для графика скважины за последний сезон по календарным дням (день без записи — 0, как в графиках производительности):
    q (расход скважины, тыс. м³/сут), grp_q и obj_q (суточный расход группы и всего объекта, тыс. м³/сут, настоящие суммы по БД расходов),
    cum_obj (накопленный отбор объекта с начала сезона, млн м³ — ось X «как в производительности»), p (давление ЭЛПРО, кгс/см² абс.),
    open (раскрытие КРУ, %)."""
    d = days[days.period.eq(last)]
    wide = d.pivot_table(index='date', columns='well', values='q', aggfunc='sum').sort_index()
    wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max())).fillna(0) / 1e3
    peers = [w for w in wide.columns if group_of.get(w, '') == group_of.get(well, '')] or list(wide.columns)
    obj = wide.sum(axis=1)
    out = pd.DataFrame({'q': wide[well] if well in wide else 0.0, 'grp_q': wide[peers].sum(axis=1), 'obj_q': obj, 'cum_obj': obj.cumsum() / 1e3})
    out['p'] = out['open'] = np.nan
    if elpro is not None and not elpro.empty:
        e = elpro[elpro.well.astype(str).eq(well)]
        e = e[e.kind.eq('withdrawal')] if 'kind' in e else e
        e = e.assign(date=pd.to_datetime(e.date).dt.normalize())
        for col, name in (('p', 'p'), ('y', 'open')):
            if col in e:
                out[name] = e.groupby('date')[col].mean().reindex(out.index).where(lambda s: s > 0)
    return out

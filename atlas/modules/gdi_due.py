"""Анализ скважин для включения в программу ГДИ: список скважин с видимыми причинами.

Скважина попадает в список по любому из признаков: нет надёжного исследования или оно старше порога; расход и накопленный отбор последнего сезона
упали заметнее, чем в среднем по группе; динамика внутри сезона расходится с объектом; отдача на раскрытие КРУ упала; динамика ГДИ показывает ухудшение (``gdi_trend``); срочный приоритет КР по ревизиям КРУ.
Программа только подсказывает: порядок и пороги задаёт инженер, любую скважину можно добавить в список или убрать из него вручную —
ручное решение главнее расчёта, причина расчёта остаётся в таблице. Математику ГДИ не пересчитываем: ``gdi_trend.histories/rating``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Axis, Chart, Series, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Source, Stat, Table
from ..domain import DatasetKind
from atlas.engine.core.config import COLORS
from ._gdi_due_metrics import METRIC_COLUMNS, productivity_intervals, well_curves, cumulative, dynamics, kru_response, last_two, withdrawal_days
from .gdi import well_key
from .gdi_trend import VERDICTS, histories, rating

GDI, PRODUCTION, PRIORITY_K, ELPRO = DatasetKind.GDI, DatasetKind.PRODUCTION, DatasetKind.KRS_PRIORITY, DatasetKind.ELPRO
SECTION = 'Критерии'
STATE_AUTO, STATE_ADDED, STATE_REMOVED = 'по расчёту', 'добавлена вручную', 'убрана вручную'
NOTE = ('Список — подсказка: причины видны в таблице, пороги задаёт инженер, любую скважину можно добавить вручную или убрать из списка '
        '(выбор сохраняется в параметрах раздела). Надёжное исследование — не меньше трёх режимов с разными расходами и R² не ниже порога. '
        'Сравнение расходов — только сезон отбора с сезоном отбора; сезон без данных не считается нулевым.')


def season_flows(prod: pd.DataFrame) -> pd.DataFrame:
    """Средний расход скважины в днях с расходом за два последних сезона отбора: well, last, prev (тыс. м³/сут), сезоны — в attrs."""
    cols = ['well', 'last', 'prev', 'last_period', 'prev_period']
    df = withdrawal_days(prod)
    if df.empty:
        return pd.DataFrame(columns=cols)
    last, prev = last_two(df)
    mean = df.groupby(['well', 'period']).q.mean() / 1e3
    out = pd.DataFrame({'well': sorted(df.well.unique(), key=well_key)})
    out['last'] = out.well.map(lambda w: mean.get((w, last), np.nan))
    out['prev'] = out.well.map(lambda w: mean.get((w, prev), np.nan)) if prev is not None else np.nan
    out['last_period'], out['prev_period'] = str(last), (str(prev) if prev is not None else '')
    return out


def relative_drop(flows: pd.DataFrame, group_of: dict[str, str]) -> pd.DataFrame:
    """Изменение расхода скважины между сезонами и медиана изменения по её группе; ``gap`` = изменение скважины − медиана группы (п.п.)."""
    out = flows.copy()
    out['group'] = out.well.map(lambda w: group_of.get(w, ''))
    out['change'] = (out['last'] - out['prev']) / out['prev'] * 100
    med = out.groupby('group').change.transform('median')
    out['group_change'] = med
    out['gap'] = out.change - med
    return out


def build(data: Data, params: dict[str, Any]) -> pd.DataFrame:
    """Таблица скважин с признаками и причинами (без ручных правок)."""
    gdi = data[GDI] if GDI in data else pd.DataFrame()
    prod = data[PRODUCTION] if PRODUCTION in data else pd.DataFrame()
    wells = set(data.wells or [])
    for frame in (gdi, prod):
        if not frame.empty and 'well' in frame:
            wells |= set(frame.well.astype(str))
    group_of = {w: (data.mapping.get(w, {}) or {}).get('group', '') for w in wells}
    table = pd.DataFrame({'well': sorted(wells, key=well_key)})
    table['group'] = table.well.map(group_of)
    # ГДИ: последнее надёжное исследование и вывод динамики
    hist = histories(gdi, params['threshold'], []) if not gdi.empty else pd.DataFrame()
    if hist.empty:
        table['last_gdi'], table['studies'], table['verdict'] = pd.NaT, 0, ''
    else:
        ok = hist[hist.reliable & hist.date.notna()]
        last = ok.groupby('well').date.max()
        table['last_gdi'] = table.well.map(last)
        table['studies'] = table.well.map(ok.groupby('well').size()).fillna(0).astype(int)
        trend = rating(hist, params['change'])
        down = trend[trend.verdict.eq(VERDICTS['down'])].drop_duplicates('well').set_index('well')
        table['verdict'] = table.well.map(lambda w: VERDICTS['down'] if w in down.index else '')
    today = pd.Timestamp(params.get('today') or pd.Timestamp.today().normalize())
    table['years'] = (today - pd.to_datetime(table.last_gdi)).dt.days / 365.25
    # расход относительно группы
    flows = relative_drop(season_flows(prod), group_of)
    keep = ['well', 'last', 'prev', 'change', 'group_change', 'gap', 'last_period', 'prev_period']
    table = table.merge(flows[keep] if not flows.empty else pd.DataFrame(columns=keep), on='well', how='left')
    # накопленный расход, динамика внутри сезона против группы и объекта, отклик на раскрытие КРУ
    days = withdrawal_days(prod)
    last_p, prev_p = last_two(days)
    elpro = data[ELPRO] if ELPRO in data else None
    for part in (cumulative(days, last_p, prev_p, group_of), dynamics(days, last_p, group_of), kru_response(elpro, days, last_p, prev_p, group_of)):
        table = table.merge(part, on='well', how='left')
    iv = productivity_intervals(days, last_p, elpro, int(params.get('min_days', 14)), float(params.get('interval_drop', 15)))
    table['int_count'] = table.well.map(iv.groupby('well').size()).fillna(0).astype(int)
    last_iv = iv.sort_values('end').drop_duplicates('well', keep='last').set_index('well') if not iv.empty else pd.DataFrame(columns=['start', 'end', 'days', 'depth'])
    for c in ('days', 'depth'):
        table['int_' + c] = table.well.map(last_iv[c]) if not iv.empty else np.nan
    table['int_last'] = table.well.map(lambda w: f"{last_iv.at[w, 'start']:%d.%m}–{last_iv.at[w, 'end']:%d.%m.%Y}" if w in last_iv.index else '')
    for c in METRIC_COLUMNS:
        if c not in table:
            table[c] = np.nan
    # приоритет КР
    prio = data[PRIORITY_K] if PRIORITY_K in data else pd.DataFrame()
    pmap = prio.assign(well=prio.well.astype(str)).set_index('well').priority if not prio.empty else pd.Series(dtype=float)
    table['kr_priority'] = table.well.map(pmap)
    table['f_age'] = table.last_gdi.isna() | table.years.ge(params['years'])
    table['f_flow'] = table.gap.le(-params['gap'])
    table['f_trend'] = table.verdict.eq(VERDICTS['down'])
    table['f_cum'] = table.cum_gap.le(-params.get('cum_gap', 15))
    table['f_sync'] = table.sync_obj.lt(params.get('sync', 50)) & table.slope_gap_obj.le(-params.get('slope', 5))
    table['f_open'] = table.eff_gap.le(-params.get('open_drop', 15))
    table['f_int'] = table.int_count.gt(0)
    table['f_kru'] = table.kr_priority.le(params['kru_priority']) & table.kr_priority.notna()
    table['score'] = table[['f_age', 'f_flow', 'f_trend', 'f_kru', 'f_cum', 'f_sync', 'f_open', 'f_int']].sum(axis=1).astype(int)
    table['reason'] = table.apply(lambda r: reasons(r, params), axis=1)
    return table


def reasons(r: pd.Series, params: dict[str, Any]) -> str:
    out = []
    if r.f_age:
        out.append('надёжного ГДИ нет' if pd.isna(r.last_gdi) else f'последнее надёжное ГДИ {r.years:.1f} лет назад')
    if r.f_flow:
        out.append(f'расход {r.last_period} упал на {-r.change:.0f}% при медиане группы {r.group_change:+.0f}%')
    if r.f_cum:
        out.append(f'накопленный отбор за {int(r.cum_days)} сут сезона {r.cum_change:+.0f}% при медиане группы {r.cum_group_change:+.0f}%')
    if r.f_sync:
        out.append(f'динамика внутри сезона не совпадает с объектом: совпало {r.sync_obj:.0f}% недельных шагов, тренд {r.slope_well:+.0f}% против {r.slope_obj:+.0f}% за 30 сут')
    if r.f_open:
        out.append(f'расход на 1% раскрытия КРУ {r.eff_change:+.0f}% при раскрытии {r.open_change:+.0f}%: на {-r.eff_gap:.0f} п.п. хуже медианы группы')
    if r.f_int:
        out.append(f'интервал снижения продуктивности {r.int_last} ({int(r.int_days)} сут): расход на {r.int_depth:.0f}% ниже относительно объекта при неуменьшенном раскрытии КРУ')
    if r.f_trend:
        out.append('динамика ГДИ: ухудшение отдачи')
    if r.f_kru:
        out.append(f'срочный приоритет КР ({int(r.kr_priority)})')
    return '; '.join(out)


def apply_manual(table: pd.DataFrame, add: list[str], remove: list[str]) -> pd.DataFrame:
    """Ручное решение главнее: «добавить» включает скважину даже без признаков, «убрать» — исключает; расчёт остаётся в таблице."""
    out = table.copy()
    add, remove = {str(w) for w in add}, {str(w) for w in remove}
    out['in_list'] = out.score.gt(0)
    out['state'] = STATE_AUTO
    out.loc[out.well.isin(add), ['in_list', 'state']] = [True, STATE_ADDED]
    out.loc[out.well.isin(remove), ['in_list', 'state']] = [False, STATE_REMOVED]
    out['_k'] = out.well.map(well_key)
    out = out.sort_values(['in_list', 'score', 'years', '_k'], ascending=[False, False, False, True], na_position='first', kind='stable')
    return out.drop(columns='_k').reset_index(drop=True)


def well_charts(data: Data, params: dict[str, Any], listed: pd.DataFrame) -> list[Chart]:
    """График на скважину: расход, динамика группы и объекта, накопленный отбор, раскрытие КРУ; красным — интервалы снижения продуктивности."""
    days = withdrawal_days(data[PRODUCTION] if PRODUCTION in data else pd.DataFrame())
    last, _ = last_two(days)
    if last is None:
        return []
    elpro = data[ELPRO] if ELPRO in data else None
    chosen = [str(w) for w in (params.get('show') or [])] or listed.well.astype(str).tolist()[:6]
    group_of = {w: (data.mapping.get(w, {}) or {}).get('group', '') for w in chosen}
    iv = productivity_intervals(days, last, elpro, int(params.get('min_days', 14)), float(params.get('interval_drop', 15)))
    charts = []
    for w in sorted(set(chosen) & set(days.well), key=well_key):
        c = well_curves(days, last, elpro, group_of | {x: (data.mapping.get(x, {}) or {}).get('group', '') for x in days.well.unique()}, w)
        x = c.index.to_numpy()
        chart = Chart(f'gdi-due-{w}', f'№ {w}: расход, накопленный отбор, раскрытие КРУ ({last})', Axis('Дата', scale='time'), Axis('Расход', 'тыс. м³/сут', from_zero=True),
                      y2=Axis('Накопленный отбор', 'млн м³', from_zero=True, color=COLORS[2]))
        chart.series += [
            Series('Скважина', x, c.q.to_numpy(float), 'line', group='Скважина', color=COLORS[0], width=2.2),
            Series('Объект (динамика, 7 сут)', x, c.obj_q.to_numpy(float), 'line', group='Объект', color='#7a8a90', dash='dash', width=1.8),
            Series('Группа (динамика, 7 сут)', x, c.grp_q.to_numpy(float), 'line', group='Группа', color=COLORS[3], dash='dot', width=1.8),
            Series('Накопленный отбор', x, c.cum.to_numpy(float), 'line', group='Накопленный', color=COLORS[2], width=1.8, axis='y2')]
        if c.open.notna().any():
            chart.y3 = Axis('Раскрытие КРУ', '%', from_zero=True, color=COLORS[4])
            chart.series.append(Series('Раскрытие КРУ', x, c.open.to_numpy(float), 'line', group='КРУ', color=COLORS[4], width=1.5, step=True, axis='y3'))
        mine = iv[iv.well.eq(w)]
        if not mine.empty:
            chart.style = {'annotations': [{'kind': 'vband', 'value': f'{r.start:%Y-%m-%d}', 'to': f'{r.end:%Y-%m-%d}', 'color': '#c0392b',
                                            'text': f'Снижение продуктивности, −{r.depth:.0f}%'} for r in mine.itertuples()]}
        charts.append(chart)
    return charts


def studies_calc(data: Data, params: dict[str, Any]) -> pd.DataFrame:
    """Все исследования скважин (любого качества) с коэффициентами a и b, посчитанными по точкам, а не взятыми из БД. Пусто — нет ГДИ."""
    gdi = data[GDI] if GDI in data else pd.DataFrame()
    h = histories(gdi, params['threshold'], []) if not gdi.empty else pd.DataFrame()
    if h.empty:
        return h
    for c in ('a_calc', 'b_calc', 'r2_calc', 'fit_points', 'distinct_q'):
        if c not in h:
            h[c] = np.nan
    h['reliable_calc'] = (h.r2_calc.ge(params['threshold']) & h.distinct_q.ge(3) & h.a_calc.ge(0) & h.b_calc.ge(0)).map({True: 'да', False: 'нет'})
    return h


def choose(table: pd.DataFrame, mask: pd.Series, add: list[str], remove: list[str]) -> pd.DataFrame:
    """Строки по признаку; ручное решение главнее: добавленные остаются в таблице всегда, убранные — внизу с пометкой."""
    out = table[mask | table.well.isin(add) | table.well.isin(remove)].copy()
    auto = mask.loc[out.index].astype(bool)
    out['in_table'] = (auto | out.well.isin(add)) & ~out.well.isin(remove)
    out['state'] = np.where(out.well.isin(remove), STATE_REMOVED, np.where(out.well.isin(add) & ~auto, STATE_ADDED, STATE_AUTO))
    return out.sort_values('in_table', ascending=False, kind='stable')


def stale_table(table: pd.DataFrame, studies: pd.DataFrame, gdi: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Скважины без ГДИ дольше порога: учитываются все исследования, даже плохие; a, b, R² — расчётные по последнему исследованию."""
    today = pd.Timestamp(params.get('today') or pd.Timestamp.today().normalize())
    out = table[['well', 'group']].copy()
    dates = pd.to_datetime(gdi.date) if not gdi.empty and 'date' in gdi else pd.Series(dtype='datetime64[ns]')
    last = dates.groupby(gdi.well.astype(str)).max() if len(dates) else pd.Series(dtype='datetime64[ns]')
    out['last_any'] = out.well.map(last) if len(last) else pd.NaT
    out['years_any'] = (today - out.last_any).dt.days / 365.25
    out['n_all'] = out.well.map(studies.groupby('well').size()).fillna(0).astype(int) if not studies.empty else 0
    cols = ['method', 'study', 'a_calc', 'b_calc', 'r2_calc', 'reliable_calc']
    if studies.empty:
        for c in cols:
            out[c] = np.nan
    else:
        pick = studies[studies.date.notna()].sort_values(['date', 'r2_calc']).drop_duplicates('well', keep='last').set_index('well')
        for c in cols:
            out[c] = out.well.map(pick[c])
    out['stale'] = out.last_any.isna() | out.years_any.ge(params['years'])
    return out


def drop_table(table: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Скважины со снижением продуктивности: интервал снижения или не меньше N совпавших сигналов динамики (расход к группе, накопленный, согласованность, КРУ, ГДИ)."""
    flags = ['f_flow', 'f_cum', 'f_sync', 'f_open', 'f_trend']
    out = table.copy()
    out['signals'] = out[flags].sum(axis=1).astype(int) + out.f_int.astype(int)
    out['flag'] = out.f_int | out.signals.ge(int(params.get('prod_signals', 2)))
    return out


class GdiDueModule(Module):
    spec = ModuleSpec(
        id='gdi_due',
        title='Анализ скважин для включения в программу ГДИ',
        group='Исследования скважин',
        description='Список скважин для планирования исследований: давность надёжного ГДИ, расход против группы, динамика ГДИ, приоритет КР; с причинами и ручной правкой.',
        needs=(),
        optional=(GDI, PRODUCTION, PRIORITY_K, ELPRO),
        order=36,
        params=(
            Param('years', 'Давность ГДИ', 'number', default=5.0, minimum=1, maximum=20, step=0.5, unit='лет', section=SECTION,
                  help='Скважина попадает в список, если надёжного исследования нет или оно старше.'),
            Param('gap', 'Отставание расхода от группы', 'number', default=15.0, minimum=1, maximum=80, step=1, unit='п.п.', section=SECTION,
                  help='Расход последнего сезона отбора по сравнению с предыдущим упал сильнее, чем медиана по группе, на столько процентных пунктов и больше.',
                  formula='отставание = изменение расхода скважины − медиана изменения по группе',
                  example='Скважина −25%, медиана группы −5%: отставание 20 п.п.; при пороге 15 — признак есть.'),
            Param('cum_gap', 'Отставание накопленного отбора', 'number', default=15.0, minimum=1, maximum=80, step=1, unit='п.п.', section=SECTION,
                  help='Накопленный отбор за одинаковый отрезок сезона (от его начала) упал сильнее медианы по группе на столько п.п. и больше.'),
            Param('sync', 'Совпадение динамики с объектом не ниже', 'number', default=50.0, minimum=0, maximum=100, step=5, unit='%', section=SECTION,
                  help='Доля недельных шагов внутри сезона, где расход скважины и объекта растёт или падает вместе. Ниже порога и при худшем тренде — признак.'),
            Param('slope', 'Тренд хуже объекта на', 'number', default=5.0, minimum=1, maximum=50, step=1, unit='п.п./30 сут', section=SECTION,
                  help='Наклон расхода скважины внутри сезона (в % от её среднего) хуже наклона объекта на столько и больше.'),
            Param('open_drop', 'Падение отдачи на раскрытие КРУ', 'number', default=15.0, minimum=1, maximum=80, step=1, unit='п.п.', section=SECTION,
                  help='Расход на 1% раскрытия КРУ (ЭЛПРО) изменился хуже медианы по группе на столько п.п. и больше: при большем раскрытии расход должен быть больше. Нужны данные ЭЛПРО.'),
            Param('min_days', 'Интервал снижения: не короче', 'number', default=14, minimum=7, maximum=90, step=1, unit='сут', section=SECTION,
                  help='Расход скважины относительно объекта держится ниже опорного уровня не меньше стольких суток подряд.'),
            Param('interval_drop', 'Интервал снижения: падение', 'number', default=15.0, minimum=5, maximum=80, step=1, unit='%', section=SECTION,
                  help='Расход скважины (сглаженный за 7 суток) относительно объекта ниже уровня первых двух недель сезона на столько процентов и больше. Если раскрытие КРУ уменьшили, интервал не отмечается.'),
            Param('prod_signals', 'Снижение продуктивности: сигналов не меньше', 'choice', default=2, section=SECTION,
                  options=(Option(1, '1'), Option(2, '2'), Option(3, '3'), Option(4, '4')),
                  help='Для второй таблицы: скважина попадает в неё при интервале снижения или при стольких совпавших сигналах: расход и накопленный отбор против группы, динамика против объекта, отдача на раскрытие КРУ, ГДИ.'),
            Param('show', 'Графики для скважин', 'multi', default=[], source=Source(GDI, 'well'), section='Графики', wells_picker=True, empty='первые 6 из списка',
                  help='Не выбрано ничего — графики для первых шести скважин списка. На графике: расход, динамика группы и объекта, накопленный отбор, раскрытие КРУ; красным подсвечены интервалы снижения продуктивности.'),
            Param('threshold', 'Порог R²', 'number', default=0.95, minimum=0.0, maximum=1.0, step=0.01, setting='r2_threshold', section=SECTION,
                  help='Общая настройка проекта: исследования с R² ниже порога не считаются надёжными.'),
            Param('change', 'Порог ухудшения ГДИ', 'number', default=10.0, minimum=1, maximum=80, step=1, unit='%', section=SECTION,
                  help='Снижение расхода при общем ΔP² на столько процентов и больше — ухудшение (как в «Динамике коэффициентов ГДИ»).'),
            Param('kru_priority', 'Приоритет КР не ниже', 'choice', default=2, section=SECTION,
                  options=(Option(0, 'Не учитывать'), Option(1, '1 — срочно'), Option(2, '1–2'), Option(3, '1–3')),
                  help='Скважины со срочным приоритетом КР (по ревизиям КРУ) получают признак. Нужны данные КРС в проекте.'),
            Param('add', 'Добавить вручную', 'multi', default=[], source=Source(GDI, 'well'), section='Ручное решение', wells_picker=True,
                  help='Скважины, которые инженер включает в список независимо от расчёта.'),
            Param('remove', 'Убрать вручную', 'multi', default=[], source=Source(GDI, 'well'), section='Ручное решение', wells_picker=True,
                  help='Скважины, которые инженер убирает из списка (например, ГДИ уже запланировано). Расчёт остаётся в таблице.'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        if not any(k in data and not data[k].empty for k in (GDI, PRODUCTION)):
            result.notes.append(Note('В проекте нет данных ГДИ и расходов: список построить не из чего. Загрузите данные во вкладке «Импорт».'))
            return result
        params = {**params, 'kru_priority': int(params.get('kru_priority', 2)) or -1}
        table = apply_manual(build(data, params), params.get('add') or [], params.get('remove') or [])
        listed = table[table.in_list]
        result.summary = [
            Stat('Скважин в проекте', str(len(table))),
            Stat('В списке на ГДИ', str(len(listed)), 'Есть признак по расчёту или добавлены вручную'),
            Stat('Без надёжного ГДИ', str(int(table.last_gdi.isna().sum()))),
            Stat(f'Старше {params["years"]:g} лет', str(int(table.years.ge(params['years']).sum()))),
            Stat('Изменено вручную', str(int(table.state.ne(STATE_AUTO).sum())))]
        result.notes.append(Note(NOTE))
        if GDI not in data or data[GDI].empty:
            result.notes.append(Note('Данных ГДИ в проекте нет: все скважины считаются без надёжного исследования.', 'warning'))
        if ELPRO not in data or data[ELPRO].empty:
            result.notes.append(Note('Данных ЭЛПРО нет: раскрытие КРУ в анализе не учитывается.'))
        if PRODUCTION not in data or data[PRODUCTION].empty or table.change.notna().sum() == 0:
            result.notes.append(Note('Сравнить расход с группой не удалось: нужны данные двух сезонов отбора.'))
        result.tables.append(Table('gdi-due', 'Скважины для планирования ГДИ', table, [
            Column('well', 'Скважина'), Column('group', 'Группа'), Column('state', 'Решение'),
            Column('score', 'Признаков', kind='number', decimals=0), Column('reason', 'Причины'),
            Column('last_gdi', 'Последнее надёжное ГДИ', kind='date'), Column('years', 'Лет назад', 'лет', 1, 'number'),
            Column('last', 'Расход, посл. сезон', 'тыс. м³/сут', 1, 'number'), Column('prev', 'Расход, пред. сезон', 'тыс. м³/сут', 1, 'number'),
            Column('change', 'Изменение', '%', 0, 'number'), Column('group_change', 'Медиана группы', '%', 0, 'number'),
            Column('gap', 'Отставание', 'п.п.', 0, 'number'), Column('verdict', 'Динамика ГДИ'),
            Column('kr_priority', 'Приоритет КР', kind='number', decimals=0),
            Column('cum_last', 'Накоплено, посл. сезон', 'млн м³', 2, 'number'), Column('cum_prev', 'Накоплено, пред. сезон', 'млн м³', 2, 'number'),
            Column('cum_change', 'Накопл.: изменение', '%', 0, 'number'), Column('cum_gap', 'Накопл.: отставание от группы', 'п.п.', 0, 'number'),
            Column('sync_group', 'Совпадение с группой', '%', 0, 'number'), Column('sync_obj', 'Совпадение с объектом', '%', 0, 'number'),
            Column('slope_well', 'Тренд скважины', '%/30 сут', 1, 'number'), Column('slope_obj', 'Тренд объекта', '%/30 сут', 1, 'number'),
            Column('open_last', 'Раскрытие КРУ, посл. сезон', '%', 0, 'number'), Column('open_change', 'Раскрытие КРУ: изменение', '%', 0, 'number'),
            Column('eff_change', 'Расход на 1% раскрытия: изменение', '%', 0, 'number'), Column('eff_gap', 'Отдача КРУ: отставание от группы', 'п.п.', 0, 'number')],
            note='Вверху — скважины в списке, затем по числу признаков и давности ГДИ. «Решение» показывает, правил ли список инженер.'))
        add, remove = [str(w) for w in params.get('add') or []], [str(w) for w in params.get('remove') or []]
        studies = studies_calc(data, params)
        st = stale_table(table, studies, data[GDI] if GDI in data else pd.DataFrame(), params)
        stale = choose(st, st.stale, add, remove)
        stale = stale.sort_values(['in_table', 'years_any'], ascending=[False, False], na_position='first', kind='stable')
        result.tables.append(Table('gdi-no-5y', f'ГДИ: скважины без исследований дольше {params["years"]:g} лет', stale, [
            Column('well', 'Скважина'), Column('group', 'Группа'), Column('state', 'Решение'),
            Column('last_any', 'Последнее ГДИ (любое)', kind='date'), Column('years_any', 'Лет назад', 'лет', 1, 'number'),
            Column('n_all', 'Исследований всего', kind='number', decimals=0), Column('method', 'Метод'), Column('study', 'Исследование'),
            Column('a_calc', 'a (расчёт)', decimals=5, kind='number'), Column('b_calc', 'b (расчёт)', decimals=5, kind='number'),
            Column('r2_calc', 'R² (расчёт)', decimals=4, kind='number'), Column('reliable_calc', 'Надёжное по расчёту')],
            note='Учитываются все исследования, в том числе плохие: инженер сам смотрит, какие были исследования, и делает вывод. '
                 'a, b и R² посчитаны по точкам последнего исследования, из БД не берутся. Нет ГДИ вообще — вверху. Список всех исследований — в таблице ниже.'))
        if not studies.empty:
            detail = studies[studies.well.isin(stale.well)].copy()
            detail['_k'] = detail.well.map(well_key)
            detail = detail.sort_values(['_k', 'date']).drop(columns='_k')
            result.tables.append(Table('gdi-no-5y-studies', 'Исследования скважин из таблицы выше', detail, [
                Column('well', 'Скважина'), Column('date', 'Дата', kind='date'), Column('method', 'Метод'), Column('study', 'Исследование'),
                Column('a_calc', 'a (расчёт)', decimals=5, kind='number'), Column('b_calc', 'b (расчёт)', decimals=5, kind='number'),
                Column('r2_calc', 'R² (расчёт)', decimals=4, kind='number'), Column('fit_points', 'Точек', kind='number', decimals=0),
                Column('reliable_calc', 'Надёжное по расчёту')], collapsed=True))
        dt = drop_table(table, params)
        drop = choose(dt, dt.flag, add, remove).sort_values(['in_table', 'signals'], ascending=[False, False], kind='stable')
        result.tables.append(Table('gdi-productivity', 'ГДИ: скважины со снижением продуктивности', drop, [
            Column('well', 'Скважина'), Column('group', 'Группа'), Column('state', 'Решение'),
            Column('signals', 'Сигналов', kind='number', decimals=0), Column('reason', 'Причины'), Column('int_last', 'Последний интервал снижения'),
            Column('cum_gap', 'Накопл.: отставание от группы', 'п.п.', 0, 'number'), Column('sync_obj', 'Совпадение с объектом', '%', 0, 'number'),
            Column('eff_gap', 'Отдача КРУ: отставание от группы', 'п.п.', 0, 'number'), Column('last_gdi', 'Последнее надёжное ГДИ', kind='date')],
            note='Скважины, где расход и накопленный отбор отстают от группы, динамика расходится с объектом, отдача на раскрытие КРУ упала или есть интервал снижения продуктивности (графики ниже). '
                 'Это подсказка: решение за инженером, добавить и убрать скважину можно вручную.'))
        result.charts.extend(well_charts(data, params, listed))
        return result

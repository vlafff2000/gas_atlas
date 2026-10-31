"""Кому пора на ГДИ: список скважин с видимыми причинами.

Скважина попадает в список по любому из признаков: нет надёжного исследования или оно старше порога; расход последнего сезона отбора
упал заметнее, чем в среднем по группе; динамика ГДИ показывает ухудшение (``gdi_trend``); срочный приоритет КР по ревизиям КРУ.
Программа только подсказывает: порядок и пороги задаёт инженер, любую скважину можно добавить в список или убрать из него вручную —
ручное решение главнее расчёта, причина расчёта остаётся в таблице. Математику ГДИ не пересчитываем: ``gdi_trend.histories/rating``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Source, Stat, Table
from ..domain import DatasetKind
from ._production import NEUTRAL_PREFIXES
from .gdi import well_key
from .gdi_trend import VERDICTS, histories, rating

GDI, PRODUCTION, PRIORITY_K = DatasetKind.GDI, DatasetKind.PRODUCTION, DatasetKind.KRS_PRIORITY
SECTION = 'Критерии'
STATE_AUTO, STATE_ADDED, STATE_REMOVED = 'по расчёту', 'добавлена вручную', 'убрана вручную'
NOTE = ('Список — подсказка: причины видны в таблице, пороги задаёт инженер, любую скважину можно добавить вручную или убрать из списка '
        '(выбор сохраняется в параметрах раздела). Надёжное исследование — не меньше трёх режимов с разными расходами и R² не ниже порога. '
        'Сравнение расходов — только сезон отбора с сезоном отбора; сезон без данных не считается нулевым.')


def season_flows(prod: pd.DataFrame) -> pd.DataFrame:
    """Средний расход скважины в днях с расходом за два последних сезона отбора: well, last, prev (тыс. м³/сут), сезоны — в attrs."""
    cols = ['well', 'last', 'prev', 'last_period', 'prev_period']
    if prod is None or prod.empty or 'q' not in prod:
        return pd.DataFrame(columns=cols)
    col = 'period' if 'period' in prod else 'season'
    df = prod[prod.kind.eq('withdrawal') & prod.q.gt(0) & prod[col].notna()]
    df = df[~df[col].astype(str).str.startswith(NEUTRAL_PREFIXES) & df[col].astype(str).ne('')]
    if df.empty:
        return pd.DataFrame(columns=cols)
    order = df.groupby(col).date.min().sort_values().index.tolist()
    last, prev = (order[-1], order[-2]) if len(order) > 1 else (order[-1], None)
    mean = df.assign(well=df.well.astype(str)).groupby(['well', col]).q.mean() / 1e3
    out = pd.DataFrame({'well': sorted(df.well.astype(str).unique(), key=well_key)})
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
    # приоритет КР
    prio = data[PRIORITY_K] if PRIORITY_K in data else pd.DataFrame()
    pmap = prio.assign(well=prio.well.astype(str)).set_index('well').priority if not prio.empty else pd.Series(dtype=float)
    table['kr_priority'] = table.well.map(pmap)
    table['f_age'] = table.last_gdi.isna() | table.years.ge(params['years'])
    table['f_flow'] = table.gap.le(-params['gap'])
    table['f_trend'] = table.verdict.eq(VERDICTS['down'])
    table['f_kru'] = table.kr_priority.le(params['kru_priority']) & table.kr_priority.notna()
    table['score'] = table[['f_age', 'f_flow', 'f_trend', 'f_kru']].sum(axis=1).astype(int)
    table['reason'] = table.apply(lambda r: reasons(r, params), axis=1)
    return table


def reasons(r: pd.Series, params: dict[str, Any]) -> str:
    out = []
    if r.f_age:
        out.append('надёжного ГДИ нет' if pd.isna(r.last_gdi) else f'последнее надёжное ГДИ {r.years:.1f} лет назад')
    if r.f_flow:
        out.append(f'расход {r.last_period} упал на {-r.change:.0f}% при медиане группы {r.group_change:+.0f}%')
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


class GdiDueModule(Module):
    spec = ModuleSpec(
        id='gdi_due',
        title='Кому пора на ГДИ',
        group='Исследования скважин',
        description='Список скважин для планирования исследований: давность надёжного ГДИ, расход против группы, динамика ГДИ, приоритет КР; с причинами и ручной правкой.',
        needs=(),
        optional=(GDI, PRODUCTION, PRIORITY_K),
        order=36,
        params=(
            Param('years', 'Давность ГДИ', 'number', default=5.0, minimum=1, maximum=20, step=0.5, unit='лет', section=SECTION,
                  help='Скважина попадает в список, если надёжного исследования нет или оно старше.'),
            Param('gap', 'Отставание расхода от группы', 'number', default=15.0, minimum=1, maximum=80, step=1, unit='п.п.', section=SECTION,
                  help='Расход последнего сезона отбора по сравнению с предыдущим упал сильнее, чем медиана по группе, на столько процентных пунктов и больше.',
                  formula='отставание = изменение расхода скважины − медиана изменения по группе',
                  example='Скважина −25%, медиана группы −5%: отставание 20 п.п.; при пороге 15 — признак есть.'),
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
        if PRODUCTION not in data or data[PRODUCTION].empty or table.change.notna().sum() == 0:
            result.notes.append(Note('Сравнить расход с группой не удалось: нужны данные двух сезонов отбора.'))
        result.tables.append(Table('gdi-due', 'Скважины для планирования ГДИ', table, [
            Column('well', 'Скважина'), Column('group', 'Группа'), Column('state', 'Решение'),
            Column('score', 'Признаков', kind='number', decimals=0), Column('reason', 'Причины'),
            Column('last_gdi', 'Последнее надёжное ГДИ', kind='date'), Column('years', 'Лет назад', 'лет', 1, 'number'),
            Column('last', 'Расход, посл. сезон', 'тыс. м³/сут', 1, 'number'), Column('prev', 'Расход, пред. сезон', 'тыс. м³/сут', 1, 'number'),
            Column('change', 'Изменение', '%', 0, 'number'), Column('group_change', 'Медиана группы', '%', 0, 'number'),
            Column('gap', 'Отставание', 'п.п.', 0, 'number'), Column('verdict', 'Динамика ГДИ'),
            Column('kr_priority', 'Приоритет КР', kind='number', decimals=0)],
            note='Вверху — скважины в списке, затем по числу признаков и давности ГДИ. «Решение» показывает, правил ли список инженер.'))
        return result

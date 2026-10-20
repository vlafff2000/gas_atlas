"""Суточный график скважины: расход и часы работы (БД расходов), КРУ, давление и температура (ЭЛПРО).

Правила суточных графиков расходов: день без записи и нулевой расход падают на ось X (ноль); исключённая точка —
разрыв линии. КРУ ограничивается диапазоном 0–100 %. Для ЭЛПРО пропущенный день — разрыв (давление и температура
нулём не заменяются).

Таблица «ЭЛПРО не видит расход»: скважина работает по БД расходов, но ЭЛПРО показывает расход ниже порога
чувствительности (или ноль), а температура газа в этот день совпадает с медианой по скважинам ЭЛПРО режима в пределах
допуска. Такие сутки — работа с малым расходом. КРУ в них сравнивается с КРУ в остальные рабочие сутки:
низкое КРУ при нормальной работе — штуцирование; низкое КРУ с низким расходом и температурой — ремонт.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from atlas.engine.core.config import ordered
from atlas.engine.core.loader import canonical_gsp

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Stat, Table
from ..domain import DatasetKind
from ._production import KINDS, group_of

PRODUCTION, ELPRO = DatasetKind.PRODUCTION, DatasetKind.ELPRO
SECTION = 'Выбор данных'
UNIT_Q = 'тыс. м³/сут'
THRESHOLD = 1.5          # тыс. м³/сут = 1500 м³/сут — нижняя граница порога чувствительности ЭЛПРО (уточнить по паспорту)
TOLERANCE = 1.0          # °C — допуск сравнения температуры с медианой
COLOR = {'q': '#1f4e8c', 'elpro': '#ff5a1f', 'hours': '#149ba5', 'cru': '#169b62', 'p': '#9955cc', 't': '#ed8b23',
         'median': '#8c8c8c', 'threshold': '#dc3545'}
NOTE = ('Расход и часы — из БД расходов, КРУ, давление и температура — из ЭЛПРО. Пропуск в БД расходов (нет записи) — '
        'ноль, пропуск в ЭЛПРО — разрыв. КРУ ограничено диапазоном 0–100 %.')
# Ряды, которые можно добавить к графику расхода: каждый на своей оси справа (до четырёх правых шкал графика).
EXTRAS = (('hours', 'Часы работы'), ('cru', 'КРУ, %'), ('p', 'Давление, кгс/см²'), ('t', 'Температура, °C'))
EXTRA_SERIES = {'hours': ('Часы работы', 'hours', {'dashed': True, 'color': COLOR['hours']}),
                'cru': ('КРУ', 'cru', {'width': 2, 'color': COLOR['cru']}),
                'p': ('Давление ЭЛПРО', 'p', {'color': COLOR['p']}),
                't': ('Температура газа', 't', {'width': 2, 'color': COLOR['t']})}
MAX_RIGHT_AXES = 4


def _day(values) -> pd.Series:
    return pd.to_datetime(values).dt.normalize()


def picked_extras(extras) -> list[str]:
    """Выбранные ряды без повторов и неизвестных ключей; у графика не больше ``MAX_RIGHT_AXES`` правых шкал."""
    return [e for e in dict.fromkeys(extras or []) if e in EXTRA_SERIES][:MAX_RIGHT_AXES]


def extra_axis(key: str) -> Axis:
    """Ось Y справа для ряда: своя шкала, единица и цвет ряда у каждого ряда."""
    if key == 'hours':
        return Axis('Часы работы', 'ч', from_zero=True, minimum=0, maximum=24, color=COLOR['hours'])
    if key == 'cru':
        return Axis('Степень открытия КРУ, %', '%', minimum=0, maximum=100, color=COLOR['cru'])
    if key == 'p':
        return Axis('Давление газа', 'кгс/см²', from_zero=True, color=COLOR['p'])
    return Axis('Температура газа, °C', color=COLOR['t'])


def classic_by_day(prod: pd.DataFrame, kind: str, well: str) -> pd.DataFrame:
    """БД расходов по суткам: q (тыс. м³/сут; NaN — исключённая точка), hours. Отсутствующей строки в таблице нет."""
    d = prod[prod['kind'].eq(kind) & prod['well'].astype(str).eq(well)]
    frame = pd.DataFrame({'date': _day(d['date']).to_numpy(), 'q': (d['q'] / 1000).to_numpy(),
                          'hours': d['hours'].to_numpy() if 'hours' in d else np.nan})
    return frame.groupby('date').agg(q=('q', lambda v: v.sum(min_count=1)), hours=('hours', lambda v: v.sum(min_count=1)))


def elpro_by_day(elpro: pd.DataFrame, kind: str, well: str | None = None) -> pd.DataFrame:
    """ЭЛПРО по суткам: elpro_q, t, p, cru (0–100). Без ``well`` — по всем скважинам (для медианы)."""
    d = elpro[elpro['kind'].eq(kind)]
    if well is not None:
        d = d[d['well'].astype(str).eq(well)]
    frame = pd.DataFrame({'date': _day(d['date']).to_numpy(), 'well': d['well'].astype(str).to_numpy(),
                          'elpro_q': d['q'].to_numpy(), 't': d['t'].to_numpy(), 'p': d['p'].to_numpy(),
                          'cru': d['y'].clip(0, 100).to_numpy()})
    return frame.groupby(['date', 'well']).agg(elpro_q=('elpro_q', lambda v: v.sum(min_count=1)), t=('t', 'mean'),
                                               p=('p', 'mean'), cru=('cru', 'mean')).reset_index()


def daily(prod: pd.DataFrame, elpro: pd.DataFrame, kind: str, well: str, start, end) -> pd.DataFrame:
    """Суточная таблица скважины на все сутки периода: q (день без записи = 0), hours, elpro_q, t, p, cru."""
    c = classic_by_day(prod, kind, well)
    e = elpro_by_day(elpro, kind, well).set_index('date').drop(columns='well')
    if start is None or end is None:
        dates = list(c.index) + list(e.index)
        if not dates:
            return pd.DataFrame()
        start = min(dates) if start is None else start
        end = max(dates) if end is None else end
    days = pd.date_range(start, end, freq='D')
    out = pd.DataFrame(index=days)
    out['q'] = np.where(days.isin(c.index), c['q'].reindex(days).to_numpy(), 0.0)
    # день без записи — ноль, как у расхода; исключённая точка (строка есть, часы пусты) — разрыв
    out['hours'] = np.where(days.isin(c.index), c['hours'].reindex(days).to_numpy(), 0.0)
    for col in ('elpro_q', 't', 'p', 'cru'):
        out[col] = e[col].reindex(days).to_numpy()
    return out


def median_by_day(e: pd.DataFrame) -> pd.Series:
    """Медиана температуры по скважинам ЭЛПРО режима за сутки; при одной скважине сравнивать не с чем — пусто."""
    grouped = e.dropna(subset=['t']).groupby('date').t
    return grouped.median().where(grouped.count() >= 2)


def others_median(e: pd.DataFrame) -> pd.Series:
    """Медиана температуры по остальным скважинам ЭЛПРО в ту же сутку (сама скважина не входит).
    Нужно не менее двух остальных скважин с температурой; иначе пусто."""
    out = pd.Series(np.nan, index=e.index)
    for _, grp in e.dropna(subset=['t']).groupby('date'):
        if len(grp) < 3:
            continue
        t = grp.t.to_numpy()
        for i, idx in enumerate(grp.index):
            out.at[idx] = np.median(np.delete(t, i))
    return out


def sensitivity(prod: pd.DataFrame, elpro: pd.DataFrame, kind: str, threshold: float, tol: float,
                start, end) -> pd.DataFrame:
    """По скважинам: сутки работы по БД расходов, сутки ниже порога ЭЛПРО, из них с температурой как у других."""
    c = prod[prod['kind'].eq(kind)]
    c = pd.DataFrame({'well': c['well'].astype(str).to_numpy(), 'date': _day(c['date']).to_numpy(),
                      'classic': (c['q'] / 1000).to_numpy()}).groupby(['well', 'date']).classic.sum(min_count=1).reset_index()
    e = elpro_by_day(elpro, kind)
    e['t_others'] = others_median(e)
    both = c.merge(e, on=['well', 'date'], how='outer')
    if start is not None:
        both = both[both.date >= start]
    if end is not None:
        both = both[both.date <= end]
    columns = ['well', 'days_work', 'days_low', 'days_hidden', 'volume_hidden', 'cru_hidden', 'cru_normal']
    if both.empty:
        return pd.DataFrame(columns=columns)
    # пустой расход в ЭЛПРО (пропуск) — не ноль: такие сутки не относятся ни к «ниже порога», ни к «нормально»
    has_q = both.elpro_q.notna()
    work = both.classic.fillna(0) > 0
    low = work & has_q & (both.elpro_q < threshold)
    hidden = low & ((both.t - both.t_others).abs() <= tol)
    normal = work & has_q & (both.elpro_q >= threshold)
    g = both.groupby('well')
    out = pd.DataFrame({
        'days_work': g.apply(lambda d: int((work[d.index]).sum()), include_groups=False),
        'days_low': g.apply(lambda d: int(low[d.index].sum()), include_groups=False),
        'days_hidden': g.apply(lambda d: int(hidden[d.index].sum()), include_groups=False),
        'volume_hidden': both[hidden].groupby('well').classic.sum(),
        'cru_hidden': both[hidden].groupby('well').cru.mean(),
        'cru_normal': both[normal].groupby('well').cru.mean(),
    }).reset_index()
    return out.fillna({'volume_hidden': 0.0})


class ElproDailyModule(Module):
    spec = ModuleSpec(
        id='elpro_daily',
        title='Суточный график скважины: ЭЛПРО и расход',
        group='Эксплуатация',
        description='Суточный расход и часы работы, КРУ, давление и температура; статистика работы ниже порога ЭЛПРО.',
        needs=(PRODUCTION, ELPRO),
        order=31,
        save_label='Сохранить вид',
        params=(
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section=SECTION),
            Param('well', 'Скважина', 'choice', default='', dynamic=True, auto='first:1', section=SECTION),
            Param('date_from', 'Период с', 'date', default=None, section=SECTION),
            Param('date_to', 'по', 'date', default=None, section=SECTION),
            Param('threshold', 'Порог ЭЛПРО по расходу', 'number', default=THRESHOLD, minimum=0, unit=UNIT_Q,
                  section=SECTION, help='Ниже порога ЭЛПРО расход не видит. По паспорту ЭЛПРО — 1500–3000 м³/сут.'),
            Param('tolerance', 'Допуск температуры', 'number', default=TOLERANCE, minimum=0, unit='°C', section=SECTION,
                  help='Температура скважины в пределах допуска от медианы по скважинам ЭЛПРО режима.'),
            Param('extras', 'Ряды на графике расхода', 'multi', default=['hours'],
                  options=tuple(Option(key, label) for key, label in EXTRAS), section=SECTION,
                  help='Каждый ряд — на своей оси справа, со смещением и цветом ряда.'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name != 'well':
            return super().options(name, data, params)
        if ELPRO not in data:
            return []
        return ordered(data[ELPRO][data[ELPRO]['kind'].eq(params.get('kind') or 'withdrawal')]['well'].astype(str).unique())

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        kind = params['kind']
        threshold = float(params['threshold'])
        tol = float(params['tolerance'])
        start = pd.Timestamp(params['date_from']) if params.get('date_from') else None
        end = pd.Timestamp(params['date_to']) if params.get('date_to') else None
        if not data[ELPRO]['kind'].eq(kind).any():
            result.notes.append(Note('В базе ЭЛПРО нет данных по выбранному режиму. Загрузите файлы ЭЛПРО через «Источники» '
                                     '(роль «ЭЛПРО»).', 'warning'))
            return result
        result.notes.append(Note(NOTE))
        stats = self.stats_table(data, kind, threshold, tol, start, end)
        result.tables.append(stats)
        well = params.get('well') or ''
        if not well:
            result.notes.append(Note('Выберите скважину для суточного графика.'))
            return result
        frame = daily(data[PRODUCTION], data[ELPRO], kind, well, start, end)
        if frame.empty or (frame.elpro_q.isna().all() and frame.hours.isna().all() and frame.q.eq(0).all()):
            result.notes.append(Note(f'По скважине {well} нет данных за выбранный период.', 'warning'))
            return result
        median = median_by_day(elpro_by_day(data[ELPRO], kind)).reindex(frame.index)
        extras = params.get('extras') or []
        result.charts += [self.flow_chart(frame, well, kind, threshold, extras), self.cru_chart(frame, well),
                          self.temp_chart(frame, well, median.to_numpy())]
        result.summary += [Stat('Суток с расходом по БД', f'{int(frame.q.gt(0).sum())}'),
                           Stat('Суток ЭЛПРО ниже порога', f'{int((frame.elpro_q.notna() & (frame.elpro_q < threshold) & frame.q.gt(0)).sum())}')]
        return result

    @staticmethod
    def stats_table(data: Data, kind: str, threshold: float, tol: float, start, end) -> Table:
        s = sensitivity(data[PRODUCTION], data[ELPRO], kind, threshold, tol, start, end)
        s['group'] = s.well.map(lambda w: group_of(data.mapping, w))
        s['group'] = canonical_gsp(s['group'].astype(str)).astype(str)
        s = s.sort_values('days_hidden', ascending=False)
        frame = pd.DataFrame({'Скважина': s.well.to_numpy(), 'Группа': s.group.to_numpy(),
                              'Суток работы': s.days_work.to_numpy(), 'Суток ниже порога ЭЛПРО': s.days_low.to_numpy(),
                              'из них T как у других': s.days_hidden.to_numpy(),
                              f'Объём в эти сутки, {UNIT_Q}': s.volume_hidden.to_numpy(),
                              'КРУ в эти сутки, %': s.cru_hidden.to_numpy(), 'КРУ в рабочие сутки, %': s.cru_normal.to_numpy()})
        columns = [Column('Скважина', 'Скважина'), Column('Группа', 'Группа'),
                   Column('Суток работы', 'Суток работы', '', 0, 'number'),
                   Column('Суток ниже порога ЭЛПРО', 'Суток ниже порога ЭЛПРО', '', 0, 'number'),
                   Column('из них T как у других', 'из них T как у других', '', 0, 'number'),
                   Column(f'Объём в эти сутки, {UNIT_Q}', f'Объём в эти сутки, {UNIT_Q}', '', 1, 'number'),
                   Column('КРУ в эти сутки, %', 'КРУ в эти сутки, %', '', 1, 'number'),
                   Column('КРУ в рабочие сутки, %', 'КРУ в рабочие сутки, %', '', 1, 'number')]
        return Table('elpro-sensitivity', 'ЭЛПРО не видит расход: работа ниже порога', frame, columns,
                     note=(f'Суток работы — по БД расходов (расход > 0). Ниже порога — ЭЛПРО видит меньше {threshold:g} {UNIT_Q} '
                           f'или не видит совсем. «T как у других» — температура в пределах ±{tol:g} °C от медианы по скважинам '
                           'ЭЛПРО режима. Низкое КРУ при этом — штуцирование; низкое КРУ с низкой температурой — ремонт.'))

    @staticmethod
    def flow_chart(frame: pd.DataFrame, well: str, kind: str, threshold: float, extras=('hours',)) -> Chart:
        x = frame.index.to_numpy()
        what = 'закачка' if kind == 'injection' else 'отбор'
        picked = picked_extras(extras)
        # каждый ряд — на своей правой шкале: y2 у графика, дальше y3, y4 (Chart.right_axes)
        scales = {f'y{n}': extra_axis(key) for n, key in enumerate(picked, start=2)}
        chart = Chart(f'elpro-flow-{well}', f'Скважина {well}: суточный расход ({what}) и ряды', Axis('Дата', scale='time'),
                      Axis(f'Расход, {UNIT_Q}', UNIT_Q, from_zero=True), crosshair=True, **scales)
        chart.series.append(Series('Расход, БД расходов', x, frame.q.to_numpy(), 'line', color=COLOR['q'], width=2))
        chart.series.append(Series('Расход, ЭЛПРО', x, frame.elpro_q.to_numpy(), 'line', color=COLOR['elpro']))
        chart.series.append(Series(f'Порог ЭЛПРО {threshold:g}', x, np.full(len(x), threshold), 'line', color=COLOR['threshold'],
                                   dashed=True, legend=True))
        for n, key in enumerate(picked):
            name, column, style = EXTRA_SERIES[key]
            chart.series.append(Series(name, x, frame[column].to_numpy(), 'line', axis=f'y{n + 2}', **style))
        return chart

    @staticmethod
    def cru_chart(frame: pd.DataFrame, well: str) -> Chart:
        x = frame.index.to_numpy()
        chart = Chart(f'elpro-cru-{well}', f'Скважина {well}: КРУ и давление', Axis('Дата', scale='time'),
                      Axis('Степень открытия КРУ, %', '%', minimum=0, maximum=100), crosshair=True,
                      y2=Axis('Давление газа', 'кгс/см²', from_zero=True))
        chart.series.append(Series('КРУ', x, frame.cru.to_numpy(), 'line', color=COLOR['cru'], width=2))
        chart.series.append(Series('Давление ЭЛПРО', x, frame.p.to_numpy(), 'line', color=COLOR['p'], axis='y2'))
        return chart

    @staticmethod
    def temp_chart(frame: pd.DataFrame, well: str, median: np.ndarray) -> Chart:
        x = frame.index.to_numpy()
        chart = Chart(f'elpro-temp-{well}', f'Скважина {well}: температура газа и медиана по скважинам ЭЛПРО',
                      Axis('Дата', scale='time'), Axis('Температура газа, °C'), crosshair=True)
        chart.series.append(Series(f'T, скв. {well}', x, frame.t.to_numpy(), 'line', color=COLOR['t'], width=2))
        chart.series.append(Series('Медиана по скважинам ЭЛПРО', x, median, 'line', color=COLOR['median'], dashed=True))
        return chart

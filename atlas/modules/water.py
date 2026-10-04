"""Вынос воды и водный фактор от объёма газа в пласте: линия на сезон отбора (рис. 1.3–1.5, табл. 1.6 отчёта АН).

Объём газа в пласте = стартовый объём + накопленная закачка − накопленный отбор по всему объекту (млн м³).
Вода — набор «Контроль воды» (объём за дату, м³; без него — расход воды на дату замера), суммируется по объекту.
Водный фактор — л воды на 1000 м³ газа (то же, что м³ на млн м³).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Stat, Table
from ..domain import DatasetKind
from ..thinning import screen_decimate
from ._group_charts import _valid
from ._production import PRODUCTION, legacy, periods_of

WATER, OPERATIONS = DatasetKind.WATER, DatasetKind.OPERATIONS
SECTION_DATA, SECTION_VIEW = 'Выбор данных', 'Вид'
WF_UNIT = 'л/тыс. м³'
SOURCES = (('water_volume_m3', 'объём воды за дату, м³'),
           ('water_rate', 'расход воды на дату замера, м³/сут; дни без замера не учитываются'))
METRICS = {'carry': 'Накопленный вынос воды', 'daily': 'Суточный водный фактор',
           'cumulative': 'Накопленный водный фактор'}
SPARSE = 60       # столько точек и меньше — рисуем с маркерами: это замеры, а не сплошной ряд


def water_by_date(data: Data) -> tuple[pd.Series, str]:
    """Вода по объекту: сумма по скважинам на дату (м³) и описание источника; пустой ряд, если воды нет."""
    frames = [(WATER, data[WATER] if WATER in data else None), (OPERATIONS, data[OPERATIONS] if OPERATIONS in data else None)]
    for kind, df in frames:
        if df is None or df.empty:
            continue
        for col, label in SOURCES:
            if col in df and pd.to_numeric(df[col], errors='coerce').notna().any():
                if kind == OPERATIONS and col != 'water_volume_m3':
                    continue
                v = df.assign(v=pd.to_numeric(df[col], errors='coerce'))
                v = v[v.v.notna() & (v.v >= 0)]
                return v.groupby(pd.to_datetime(v.date).dt.normalize()).v.sum(), f'«{kind.label}»: {label}'
    return pd.Series(dtype=float), ''


def gas_balance(df: pd.DataFrame, start: float) -> tuple[pd.DataFrame, pd.Series]:
    """По датам объекта: ``v`` — объём газа в пласте (млн м³), ``withdrawal`` — отбор за дату (м³); сезон по дате."""
    d = df.assign(q=_valid(df))
    day = d.pivot_table(index='date', columns='kind', values='q', aggfunc='sum').sort_index()
    for kind in ('withdrawal', 'injection'):
        if kind not in day:
            day[kind] = np.nan
    out = pd.DataFrame({'withdrawal': day.withdrawal})
    out['v'] = start + (day.injection.fillna(0) - day.withdrawal.fillna(0)).cumsum() / 1e6
    seasons = d[d.kind.eq('withdrawal')].drop_duplicates('date').set_index('date').period
    return out, seasons


def season_frame(balance: pd.DataFrame, seasons: pd.Series, water: pd.Series, period: str) -> pd.DataFrame:
    """Дни отбора сезона: газ, вода (NaN — не измерялась), накопленные вода и газ, факторы."""
    s = balance[seasons.reindex(balance.index).eq(period) & balance.withdrawal.notna()].copy()
    s['water'] = water.reindex(s.index)
    s['gas'] = s.withdrawal.clip(lower=0)
    s['cum_water'] = s.water.fillna(0).cumsum()
    s['cum_gas'] = s.gas.cumsum()
    s['daily'] = s.water / s.gas.where(s.gas > 0) * 1e6
    s['cumulative'] = s.cum_water / s.cum_gas.where(s.cum_gas > 0) * 1e6
    s.loc[~s.water.notna().cummax(), 'cumulative'] = np.nan     # до первого замера воды фактора нет, а не ноль
    return s.rename_axis('date').reset_index()


class WaterModule(Module):
    spec = ModuleSpec(
        id='water',
        title='Вынос воды и водный фактор',
        group='Эксплуатация',
        description='Вынос воды и водный фактор от объёма газа в пласте, по сезонам отбора.',
        needs=(PRODUCTION, WATER),
        optional=(OPERATIONS,),
        order=40,
        params=(
            Param('periods', 'Сезоны отбора', 'multi', default=[], dynamic=True, auto='last:5', empty='ничего',
                  section=SECTION_DATA),
            Param('start', 'Объём газа в пласте на начало данных', 'number', default=0.0, unit='млн м³', step=100,
                  section=SECTION_DATA,
                  help='Стартовый объём; при 0 по оси X — изменение объёма газа с начала загруженных данных'),
            Param('metric', 'График', 'choice', default='all', section=SECTION_VIEW, options=(
                Option('all', 'Все три'), *(Option(k, v) for k, v in METRICS.items()))),
            Param('inverse', 'Ось X справа налево (объём убывает)', 'boolean', default=True, section=SECTION_VIEW),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'periods':
            return periods_of(data[PRODUCTION], 'withdrawal')
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        df = data[PRODUCTION]
        water, source = water_by_date(data)
        if water.empty:
            result.notes.append(Note('В данных о воде нет объёма или расхода воды: загрузите «Контроль воды» с колонкой '
                                     'объёма (м³) или расхода воды.', 'warning'))
            return result
        available = periods_of(df, 'withdrawal')
        chosen = [p for p in available if p in set(params['periods'])]
        if not chosen:
            result.notes.append(Note('Выберите сезоны отбора.'))
            return result
        balance, seasons = gas_balance(df, float(params['start']))
        frames = {p: season_frame(balance, seasons, water, p) for p in chosen}
        frames = {p: f for p, f in frames.items() if not f.empty}
        measured = {p: int(f.water.notna().sum()) for p, f in frames.items()}
        if not any(measured.values()):
            result.notes.append(Note('В выбранных сезонах нет замеров воды.'))
            return result
        result.notes.append(Note(f'Вода: {source}. Объём газа в пласте = стартовый + закачка − отбор по объекту; '
                                 'пропущенные даты не считаются нулевыми. Накопленный вынос считает только измеренную воду: '
                                 'при редких замерах он занижен.'))
        wanted = list(METRICS) if params['metric'] == 'all' else [params['metric']]
        for metric in wanted:
            result.charts.append(self.chart(metric, frames, df, params))
        result.summary = [Stat('Сезонов', str(len(frames))), Stat('Дат с водой', str(sum(measured.values()))),
                          Stat('Старт, млн м³', f'{params["start"]:g}', 'Объём газа в пласте на начало данных')]
        result.tables.append(self.table(frames))
        return result

    @staticmethod
    def chart(metric: str, frames: dict[str, pd.DataFrame], df: pd.DataFrame, params: dict[str, Any]) -> Chart:
        y = {'carry': Axis('Накопленный вынос воды', 'м³', from_zero=True),
             'daily': Axis('Суточный водный фактор', WF_UNIT, from_zero=True),
             'cumulative': Axis('Накопленный водный фактор', WF_UNIT, from_zero=True)}[metric]
        chart = Chart(f'water-{metric}', METRICS[metric] + ' от объёма газа в пласте',
                      Axis('Объём газа в пласте', 'млн м³', inverse=bool(params['inverse'])), y)
        colors = legacy.period_colors(df, 'withdrawal')
        for period, f in frames.items():
            col = {'carry': 'cum_water', 'daily': 'daily', 'cumulative': 'cumulative'}[metric]
            part = f[['date', 'v', col]].rename(columns={col: 'value'}).dropna(subset=['v', 'value'])
            if part.empty:
                continue
            markers = len(part) <= SPARSE
            if not markers:
                part = screen_decimate(part, 'value')
            labels = part.date.dt.strftime('%d.%m.%Y').tolist()
            chart.series.append(Series(str(period), part.v.to_numpy(), part.value.to_numpy(), 'line', color=colors.get(period, ''),
                                       width=1.8, markers=markers, labels=labels,
                                       facets={'Сезон': str(period)}))
        return chart

    @staticmethod
    def table(frames: dict[str, pd.DataFrame]) -> Table:
        rows = []
        for period, f in frames.items():
            water, gas = float(f.water.sum()), float(f.gas.sum())
            rows.append({'period': period, 'start': f.date.min(), 'end': f.date.max(), 'days': int(f.water.notna().sum()),
                         'gas': gas / 1e6, 'water': water if f.water.notna().any() else np.nan,
                         'factor': water / gas * 1e6 if gas > 0 and f.water.notna().any() else np.nan,
                         'v_start': float(f.v.iloc[0]), 'v_end': float(f.v.iloc[-1])})
        t = pd.DataFrame(rows)
        return Table('seasons', 'Вынос воды по сезонам', t, [
            Column('period', 'Сезон'), Column('start', 'Начало', kind='date'), Column('end', 'Конец', kind='date'),
            Column('days', 'Дат с замером воды', kind='number'), Column('gas', 'Отбор газа', 'млн м³', 2, 'number'),
            Column('water', 'Вода', 'м³', 1, 'number'), Column('factor', 'Водный фактор', WF_UNIT, 2, 'number'),
            Column('v_start', 'Газ в пласте, начало', 'млн м³', 1, 'number'),
            Column('v_end', 'Газ в пласте, конец', 'млн м³', 1, 'number')],
            note='Водный фактор сезона = вода за сезон / отбор газа за сезон; по измеренной воде.')

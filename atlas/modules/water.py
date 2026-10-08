"""Вынос воды и водный фактор от объёма газа в пласте: линия на сезон отбора (рис. 1.3–1.5, табл. 1.6 отчёта АН).

Объём газа в пласте = стартовый объём + накопленная закачка − накопленный отбор по всему объекту (млн м³).
Вода — набор «Контроль воды» (объём за дату, м³; без него — расход воды на дату замера), суммируется по объекту.
Водный фактор — л воды на 1000 м³ газа (то же, что м³ на млн м³).

Новый вид данных — готовая таблица по объекту «Вынос воды по объекту» (дата, накопленный расход газа, водный фактор
нарастающий, накопленная вода, расход воды, водный фактор, объём газа в пласте): график строится по ней напрямую,
отбор и закачка не нужны. Прежний набор «Контроль воды» + отбор и закачка работает как раньше.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Stat, Table
from ..domain import DatasetKind
from ..thinning import screen_decimate
from ._group_charts import _valid
from ._production import COLORS, PRODUCTION, legacy, periods_of

WATER, OPERATIONS, FACTOR = DatasetKind.WATER, DatasetKind.OPERATIONS, DatasetKind.WATER_FACTOR
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


def factor_frames(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Таблица по объекту → сезоны отбора. Сезон — отрезок, где объём газа в пласте не растёт (рост — закачка, новый сезон)."""
    d = df.sort_values('date').reset_index(drop=True)
    d = d[d.date.notna() & d.gas_in_place.notna()].reset_index(drop=True)
    if d.empty:
        return {}
    for col in ('gas_cum', 'wf_cum', 'water_cum', 'water_day', 'wf'):
        if col not in d:
            d[col] = np.nan
    rising = d.gas_in_place.diff().gt(0)
    d['part'] = (rising & ~rising.shift(fill_value=False)).cumsum()      # закачка — отдельный отрезок
    frames: dict[str, pd.DataFrame] = {}
    for _, part in d.groupby('part', sort=True):
        if part.gas_in_place.diff().dropna().gt(0).all() and len(part) > 1:
            continue
        a, b = part.date.min(), part.date.max()
        label = f'{a.year}' if a.year == b.year else f'{a.year}–{b.year}'
        while label in frames:
            label += '′'
        cum_water = part.water_cum.where(part.water_cum.notna(), part.water_day.fillna(0).cumsum())
        frames[label] = pd.DataFrame({'date': part.date, 'v': part.gas_in_place, 'water': part.water_day,
                                      'gas': part.gas_cum.diff().mul(1e6), 'cum_water': cum_water,
                                      'cum_gas': part.gas_cum.mul(1e6), 'daily': part.wf, 'cumulative': part.wf_cum}).reset_index(drop=True)
    return frames


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
        needs=(),
        optional=(PRODUCTION, WATER, FACTOR, OPERATIONS),
        order=40,
        params=(
            Param('periods', 'Сезоны отбора', 'multi', default=[], dynamic=True, auto='last:5', empty='ничего',
                  section=SECTION_DATA),
            Param('start', 'Объём газа в пласте на начало данных', 'number', default=0.0, unit='млн м³', step=100,
                  section=SECTION_DATA,
                  help='Стартовый объём; при 0 по оси X — изменение объёма газа с начала загруженных данных'),
            Param('metric', 'График', 'choice', default='all', section=SECTION_VIEW, chart_kind=True, options=(
                Option('all', 'Все три'), *(Option(k, v) for k, v in METRICS.items()))),
            Param('xaxis', 'Ось X', 'choice', default='volume', section=SECTION_VIEW, options=(
                Option('volume', 'По объёму газа в пласте'), Option('cumulative', 'По накопленному отбору за сезон'))),
            Param('inverse', 'Ось X справа налево (объём убывает)', 'boolean', default=True, section=SECTION_VIEW,
                  help='Только для оси «по объёму газа в пласте»'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'periods':
            if FACTOR in data and not data[FACTOR].empty:
                return list(factor_frames(data[FACTOR]))
            return periods_of(data[PRODUCTION], 'withdrawal') if PRODUCTION in data else []
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        if FACTOR in data and not data[FACTOR].empty:
            return self.run_factor(data, params, result)
        if PRODUCTION not in data or data[PRODUCTION].empty:
            result.notes.append(Note('Загрузите «Вынос воды по объекту» (дата, объём газа в пласте, вода, водный фактор) либо '
                                     '«Отбор и закачка» вместе с «Контролем воды».', 'warning'))
            return result
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

    def run_factor(self, data: Data, params: dict[str, Any], result: Result) -> Result:
        """Готовая таблица по объекту: сезоны и графики прямо из её колонок."""
        all_frames = factor_frames(data[FACTOR])
        chosen = [p for p in all_frames if p in set(params['periods'])]
        if not all_frames:
            result.notes.append(Note('В таблице нет строк с датой и объёмом газа в пласте.', 'warning'))
            return result
        if not chosen:
            result.notes.append(Note('Выберите сезоны отбора.'))
            return result
        frames = {p: all_frames[p] for p in chosen}
        result.notes.append(Note('Данные: «Вынос воды по объекту» — готовые накопленная вода и водные факторы из загруженной таблицы; '
                                 'ось X — объём газа в пласте из неё же.'))
        wanted = list(METRICS) if params['metric'] == 'all' else [params['metric']]
        empty = pd.DataFrame(columns=['date', 'kind', 'period'])
        for metric in wanted:
            result.charts.append(self.chart(metric, frames, empty, params))
        result.summary = [Stat('Сезонов', str(len(frames))), Stat('Дат', str(sum(len(f) for f in frames.values())))]
        result.tables.append(self.table(frames))
        return result

    @staticmethod
    def chart(metric: str, frames: dict[str, pd.DataFrame], df: pd.DataFrame, params: dict[str, Any]) -> Chart:
        y = {'carry': Axis('Накопленный вынос воды', 'м³', from_zero=True),
             'daily': Axis('Суточный водный фактор', WF_UNIT, from_zero=True),
             'cumulative': Axis('Накопленный водный фактор', WF_UNIT, from_zero=True)}[metric]
        by_take = params.get('xaxis') == 'cumulative'
        x = (Axis('Накопленный отбор за сезон', 'млн м³', from_zero=True) if by_take
             else Axis('Объём газа в пласте', 'млн м³', inverse=bool(params['inverse'])))
        chart = Chart(f'water-{metric}', METRICS[metric] + (' от накопленного отбора за сезон' if by_take else ' от объёма газа в пласте'),
                      x, y)
        colors = legacy.period_colors(df, 'withdrawal') if not df.empty else {
            p: COLORS[i % len(COLORS)] for i, p in enumerate(reversed(list(frames)))}
        for period, f in frames.items():
            col = {'carry': 'cum_water', 'daily': 'daily', 'cumulative': 'cumulative'}[metric]
            part = f[['date', 'v', col]].rename(columns={col: 'value'})
            if by_take:
                take = f.cum_gas.astype(float) / 1e6
                part['v'] = take - (take.dropna().iloc[0] if take.notna().any() else 0)
            part = part.dropna(subset=['v', 'value'])
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
            water = float(f.cum_water.dropna().iloc[-1]) if f.cum_water.notna().any() and 'cum_gas' in f and f.cum_gas.notna().any() else float(f.water.sum())
            gas = float(f.gas.sum())
            rows.append({'period': period, 'start': f.date.min(), 'end': f.date.max(), 'days': int(f.water.notna().sum()),
                         'gas': gas / 1e6, 'water': water if f.water.notna().any() else np.nan,
                         'factor': (float(f.cumulative.dropna().iloc[-1]) if f.cumulative.notna().any() else
                                    water / gas * 1e6 if gas > 0 and f.water.notna().any() else np.nan),
                         'v_start': float(f.v.iloc[0]), 'v_end': float(f.v.iloc[-1])})
        t = pd.DataFrame(rows)
        return Table('seasons', 'Вынос воды по сезонам', t, [
            Column('period', 'Сезон'), Column('start', 'Начало', kind='date'), Column('end', 'Конец', kind='date'),
            Column('days', 'Дат с замером воды', kind='number'), Column('gas', 'Отбор газа', 'млн м³', 2, 'number'),
            Column('water', 'Вода', 'м³', 1, 'number'), Column('factor', 'Водный фактор', WF_UNIT, 2, 'number'),
            Column('v_start', 'Газ в пласте, начало', 'млн м³', 1, 'number'),
            Column('v_end', 'Газ в пласте, конец', 'млн м³', 1, 'number')],
            note='Водный фактор сезона = вода за сезон / отбор газа за сезон; по измеренной воде.')

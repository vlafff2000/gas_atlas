"""БД по учету газа: суточный отбор или закачка по объекту и вынос воды по месяцам.

Данные — «БД по учету газа» Базы ПХГ (роль «БД по учету газа» в «Источниках»). Значения по объекту приоритетны:
это основной источник суточных объёмов. Вынос воды считается только по суткам с замером; день без замера в фактор не
входит, пропуск не превращается в ноль. Водный фактор — Σ вынос (м³) / (Σ объём в дни замера, тыс. м³ / 1000).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Param, Result, Series, Table
from ..domain import DatasetKind
from ._production import KINDS

GAS_DB = DatasetKind.GAS_DB
SECTION = 'Выбор данных'
UNIT_Q = 'тыс. м³/сут'
WF_UNIT = 'м³/млн м³'
NOTE = ('Суточные объёмы и вынос воды — из «БД по учету газа» Базы ПХГ (приоритетный источник). День без записи в '
        'графике не показан; вынос воды по объекту — только в сутки с замером.')


def monthly(frame: pd.DataFrame) -> pd.DataFrame:
    """Итоги по месяцам для одного режима: суток, объём (млн м³), дни с замером выноса, вынос (м³), водный фактор."""
    d = frame.copy()
    d['gas'] = pd.to_numeric(d['gas'], errors='coerce').astype(float)
    d['water'] = pd.to_numeric(d['water'], errors='coerce').astype(float)
    d['month'] = d['date'].dt.to_period('M').astype(str)
    measured = d['water'].notna() & d['gas'].gt(0)
    d['gas_m'] = d['gas'].where(measured)
    g = d.groupby('month').agg(days=('date', 'count'), gas=('gas', 'sum'), water_days=('water', 'count'),
                               water=('water', 'sum'), gas_m=('gas_m', 'sum'))
    g['gas'] = g['gas'] / 1000.0                       # тыс. м³ → млн м³ за месяц
    g['factor'] = (g['water'] / (g['gas_m'] / 1000.0)).where(g['gas_m'] > 0)
    g['water'] = g['water'].where(g['water_days'] > 0)  # месяц без замера — пропуск, не ноль
    return g.drop(columns='gas_m').reset_index()


class GasAccountingModule(Module):
    spec = ModuleSpec(
        id='gas_accounting',
        title='БД по учету газа: суточный объём и вынос воды',
        group='Эксплуатация',
        description='Суточный отбор или закачка по объекту и вынос воды по месяцам из «БД по учету газа».',
        needs=(GAS_DB,),
        order=32,
        save_label='Сохранить вид',
        params=(
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section=SECTION),
            Param('date_from', 'Период с', 'date', default=None, section=SECTION),
            Param('date_to', 'по', 'date', default=None, section=SECTION),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        kind = params['kind']
        if GAS_DB not in data or not data[GAS_DB]['kind'].eq(kind).any():
            result.notes.append(Note('В данных нет «БД по учету газа» для выбранного режима. Загрузите файл через «Источники» '
                                     '(роль «БД по учету газа»).', 'warning'))
            return result
        result.notes.append(Note(NOTE))
        d = data[GAS_DB][data[GAS_DB]['kind'].eq(kind)].copy()
        if params.get('date_from'):
            d = d[d['date'] >= pd.Timestamp(params['date_from'])]
        if params.get('date_to'):
            d = d[d['date'] <= pd.Timestamp(params['date_to'])]
        d = d.sort_values('date')
        label = 'Отбор' if kind == 'withdrawal' else 'Закачка'
        chart = Chart('gas-daily', f'{label} по суткам, объект', Axis('Дата', scale='time'), Axis(label, unit=UNIT_Q, from_zero=True))
        chart.series.append(Series(label, d['date'].tolist(), d['gas'].tolist(), 'line', legend=True))
        result.charts.append(chart)
        months = monthly(d)
        result.tables.append(Table('gas-months', 'По месяцам', months, [
            Column('month', 'Месяц'), Column('days', 'Суток', kind='number'),
            Column('gas', f'{label}, за месяц', 'млн м³', 2, 'number'),
            Column('water_days', 'Дней с замером выноса', kind='number'),
            Column('water', 'Вынос воды', 'м³', 1, 'number'),
            Column('factor', 'Водный фактор', WF_UNIT, 2, 'number'),
        ], note='Водный фактор — только по суткам с замером выноса и положительным объёмом.'))
        return result

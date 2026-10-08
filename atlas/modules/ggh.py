"""ГГХ: газогидрохимические исследования — состав водорастворённого газа и газонасыщенность по скважине.

Новый раздел (в 5.8 его нет, паритета нет). Данные — набор «ГГХ» (импорт: «Импорт данных» → «ГГХ», формат — лист «Общий»
отчёта). По скважине — график во времени: слева «Содержание, %» (сумма УВ, He, H2, N2, O2, CO2), справа «Газонасыщенность,
см³/л»; под ним таблица значений по датам отбора. Оси и цвета — как в скрипте отчёта; выгрузка страниц в Word — раздел «Экспорт».
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from atlas.engine.core.config import ordered

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Source, Stat, Table
from ..domain import DatasetKind
from ._ggh import GAS, GAS_COLUMN, MIN_POINTS, PARAMS, TICKS, cell, gas_axis, rows_for, well_horizon, wells_of

GGH = DatasetKind.GGH
SECTION_DATA = 'Выбор данных'


class GghModule(Module):
    spec = ModuleSpec(
        id='ggh',
        title='ГГХ: газогидрохимия',
        group='Исследования скважин',
        description='Состав водорастворённого газа и газонасыщенность по скважине во времени; таблица значений под графиком.',
        needs=(GGH,),
        order=70,
        params=(
            Param('horizons', 'Водоносные горизонты', 'multi', default=[], dynamic=True, empty='все', section=SECTION_DATA),
            Param('wells', 'Скважины', 'multi', default=[], dynamic=True, depends=('horizons',), auto='first:3',
                  empty='ничего', section=SECTION_DATA),
            Param('start', 'С даты', 'date', default='', section=SECTION_DATA),
            Param('end', 'По дату', 'date', default='', section=SECTION_DATA),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        df = data[GGH]
        if name == 'horizons':
            return ordered(h for h in (well_horizon(df[df.well.astype(str) == w]) for w in df.well.astype(str).unique()) if h)
        if name == 'wells':
            return wells_of(df, params.get('horizons') or None)
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        df = data[GGH]
        d = pd.to_datetime(df.date)
        if params['start']:
            df = df[d >= pd.Timestamp(params['start'])]
            d = pd.to_datetime(df.date)
        if params['end']:
            df = df[d <= pd.Timestamp(params['end'])]
        wells = [w for w in wells_of(data[GGH], params['horizons'] or None, 1) if w in set(params['wells'])]   # одиночные замеры — в заметку
        if not wells:
            result.notes.append(Note('Выберите скважины.'))
            return result
        skipped = []
        for well in wells:
            part = df[df.well.astype(str) == well].sort_values('date')
            if len(part) < MIN_POINTS:
                skipped.append(well)
                continue
            horizon = well_horizon(data[GGH][data[GGH].well.astype(str) == well])
            result.charts.append(self.chart(well, part))
            result.tables.append(self.table(well, part, horizon))
        if skipped:
            result.notes.append(Note('Замеров меньше двух (график не строится): скважины ' + ', '.join(skipped) + '.'))
        result.summary = [Stat('Скважин', str(len(result.charts))),
                          Stat('Замеров', str(sum(len(df[df.well.astype(str) == w]) for w in wells)))]
        result.notes.append(Note('Левая шкала — состав газа, % об.; правая — газонасыщенность, см³/л. Число делений на обеих '
                                 'шкалах одинаковое; предел правой шкалы — максимум газонасыщенности, округлённый вверх до кратного 10.'))
        return result

    @staticmethod
    def chart(well: str, part: pd.DataFrame) -> Chart:
        title = f'Скважина №{well}'
        gas = pd.to_numeric(part.gas, errors='coerce')
        low, high = gas_axis(gas)
        chart = Chart(f'ggh-{well}', title, Axis('Год', scale='time'),
                      Axis('Содержание', '%', minimum=0, maximum=100, step=100 / (TICKS - 1)),
                      y2=Axis('Газонасыщенность', 'см³/л', minimum=low, maximum=high, step=(high - low) / (TICKS - 1)) if gas.notna().any() else None,
                      crosshair=True)
        dates = pd.to_datetime(part.date)
        for key, (label, color, symbol) in PARAMS.items():
            values = pd.to_numeric(part[key], errors='coerce')
            ok = values.notna()
            if ok.any():
                chart.series.append(Series(label, list(dates[ok]), values[ok].tolist(), 'line', color=color, symbol=symbol,
                                           width=1.5, markers=True, labels=[f'{v:g}' for v in values[ok]]))
        if gas.notna().any():
            ok = gas.notna()
            chart.series.append(Series(GAS[1], list(dates[ok]), gas[ok].tolist(), 'line', color=GAS[2], width=1.5, markers=True,
                                       axis='y2', labels=[f'{v:g}' for v in gas[ok]]))
        return chart

    @staticmethod
    def table(well: str, part: pd.DataFrame, horizon: str = '') -> Table:
        """Параметры — строки, даты отбора — колонки (как таблица под графиком в отчёте)."""
        dates = [pd.Timestamp(v).strftime('%m.%Y') for v in part.sort_values('date').date]
        keys = [f'd{i}' for i in range(len(dates))]
        rows = []
        for key, label, _, values in rows_for(part.sort_values('date')):
            rows.append({'p': label, **{k: cell(key, v) for k, v in zip(keys, values)}})
        frame = pd.DataFrame(rows, columns=['p'] + keys)
        return Table(f'ggh-{well}', f'Скважина №{well}' + (f' · {horizon}' if horizon else '') + ': значения по датам отбора', frame,
                     [Column('p', 'Параметр')] + [Column(k, d) for k, d in zip(keys, dates)],
                     note='Газонасыщенность — см³/л, остальное — % об.')

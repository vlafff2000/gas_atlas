"""ГИС и ГВК: динамика ГВК, hг эф и Кг ср.взв по скважинам и пачкам (данные — «База ГИС», таблица gis_packs).

На каждую скважину — три графика (ГВК а.о., hг эф, Кг ср.взв): линия на пачку, цвет пачки общий с легендой, весенние замеры
отмечены треугольником, осенние кругом. Свод по пачкам — ГВК всех выбранных скважин на одном графике. Таблица — изменение
ГВК от первого замера к последнему. Всё строится на общем ядре графиков (Series/Axis/Chart), как в остальных разделах.
Автоматических исключений нет: точки можно исключить по щелчку, как в других разделах (слово за инженером).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from atlas.engine.core.config import ordered

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Stat, Table
from ..domain import DatasetKind

GIS = DatasetKind.GIS_PACKS
SECTION = 'Выбор данных'
SPRING = 'весна'
# метрика → (колонка, подпись, единица, название графика)
METRICS = {
    'gvk': ('gvk_abs_m', 'ГВК а.о.', 'м', 'ГВК, абсолютная отметка'),
    'h_eff': ('h_eff_m', 'hг эф', 'м', 'Эффективная газонасыщенная толщина'),
    'kg': ('kg_avg', 'Кг ср.взв', 'д.ед.', 'Средневзвешенная газонасыщенность'),
}


def _packs(df: pd.DataFrame, wells: list[str], packs: list[str], start: str, end: str) -> pd.DataFrame:
    part = df[df['well'].astype(str).isin(wells)].copy()
    if packs:
        part = part[part['pack'].astype(str).isin(packs)]
    if start:
        part = part[part['date'] >= pd.Timestamp(start)]
    if end:
        part = part[part['date'] <= pd.Timestamp(end)]
    return part.sort_values(['well', 'pack', 'date'])


class GisModule(Module):
    spec = ModuleSpec(
        id='gis',
        title='ГИС и ГВК: динамика',
        group='Исследования скважин',
        description='Динамика ГВК, эффективной толщины и Кг ср.взв по скважинам и пачкам из «Базы ГИС».',
        needs=(GIS,),
        order=75,
        builder_layouts=True,    # макеты «Конструктора графиков» графиками после основных
        params=(
            Param('wells', 'Скважины', 'multi', default=[], dynamic=True, empty='ничего', auto='first:3', section=SECTION),
            Param('packs', 'Пачки', 'multi', default=[], dynamic=True, empty='все', section=SECTION),
            Param('view', 'График', 'choice', default='all', section='Вид', chart_kind=True, options=(
                Option('all', 'Все три'), *(Option(k, v[3]) for k, v in METRICS.items()),
                Option('combo', 'Кривые и столбцы: Кг и hэф'), Option('svod', 'Свод по пачкам, все скважины'))),
            Param('start', 'С даты', 'date', default='', section=SECTION),
            Param('end', 'По дату', 'date', default='', section=SECTION),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        df = data[GIS]
        if name == 'wells':
            return ordered(df['well'].astype(str).unique())
        if name == 'packs':
            return ordered(df['pack'].dropna().astype(str).unique())
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        if GIS not in data or data[GIS].empty:
            result.notes.append(Note('В данных нет «Базы ГИС». Загрузите таблицу пачек через «Источники» или «Импорт данных».'))
            return result
        wells = [w for w in params['wells'] if w in set(data[GIS]['well'].astype(str))]
        if not wells:
            result.notes.append(Note('Выберите скважины.'))
            return result
        part = _packs(data[GIS], wells, params['packs'], params['start'], params['end'])
        if part.empty:
            result.notes.append(Note('За выбранные скважины, пачки и даты замеров нет.'))
            return result
        for well in wells:
            frame = part[part['well'].astype(str) == well]
            if frame.empty:
                continue
            for key in [k for k in METRICS if params['view'] in ('all', k)]:
                result.charts.append(self.chart(well, frame, key))
            if params['view'] in ('all', 'combo'):
                for pack, pack_frame in frame.groupby('pack', sort=True):
                    result.charts.append(self.chart_combo(well, str(pack), pack_frame))
        if params['view'] in ('all', 'svod'):
            for key in METRICS:
                for pack in sorted(part['pack'].astype(str).unique()):
                    result.charts.append(self.chart_pack(key, pack, part))
        result.tables.append(self.change_table(part))
        names = params.get('builder_layouts') or []
        if names:
            from .. import builder_library
            builder_library.add_layout_charts(result, data, names, wells)
        result.summary = [Stat('Скважин', str(len(wells))), Stat('Замеров', str(len(part)))]
        result.notes.append(Note('Треугольник — весенний замер (после отбора), круг — осенний (после закачки). Замеры без сезона '
                                 'показаны кругом. Точку можно исключить щелчком, как в других разделах.'))
        return result

    @staticmethod
    def _series(frame: pd.DataFrame, column: str, label: str) -> list[Series]:
        """Линия на пачку, цвет по пачке; весенние точки поверх — треугольниками без линии."""
        out: list[Series] = []
        for pack, part in frame.groupby('pack', sort=True):
            part = part[part[column].notna()]
            if part.empty:
                continue
            ids = part['_point_id'].tolist() if '_point_id' in part else None
            out.append(Series(str(pack), list(part['date']), part[column].tolist(), 'line', group=str(pack), markers=True,
                              labels=[f'{v:g}' for v in part[column]], ids=ids, dataset=GIS if ids else None))
            spring = part[part['season'].astype(str) == SPRING]
            if len(spring):
                out.append(Series(f'{pack}: весна', list(spring['date']), spring[column].tolist(), 'points', group=str(pack),
                                  symbol='triangle', legend=False, labels=[f'{v:g}' for v in spring[column]],
                                  ids=spring['_point_id'].tolist() if '_point_id' in spring else None,
                                  dataset=GIS if '_point_id' in spring else None))
        return out

    @staticmethod
    def chart(well: str, frame: pd.DataFrame, key: str) -> Chart:
        column, label, unit, title = METRICS[key]
        chart = Chart(f'gis-{key}-{well}', f'Скважина №{well}: {title.lower()}', Axis('Дата', scale='time'),
                      Axis(label, unit), crosshair=True)
        chart.series = GisModule._series(frame, column, label)
        return chart

    @staticmethod
    def chart_pack(key: str, pack: str, part: pd.DataFrame) -> Chart:
        """Свод по пачке: метрика всех выбранных скважин на одном графике, цвет — скважина."""
        column, label, unit, title = METRICS[key]
        chart = Chart(f'gis-pack-{key}-{pack}', f'Пачка «{pack}», все скважины: {title.lower()}', Axis('Дата', scale='time'),
                      Axis(label, unit), crosshair=True)
        for well, frame in part[part['pack'].astype(str) == pack].groupby('well', sort=True):
            frame = frame[frame[column].notna()]
            if frame.empty:
                continue
            ids = frame['_point_id'].tolist() if '_point_id' in frame else None
            chart.series.append(Series(f'скв. {well}', list(frame['date']), frame[column].tolist(), 'line', group=str(well),
                                       markers=True, labels=[f'{v:g}' for v in frame[column]], ids=ids,
                                       dataset=GIS if ids else None))
        return chart

    @staticmethod
    def chart_combo(well: str, pack: str, frame: pd.DataFrame) -> Chart:
        """Кривые Кг ср.взв (слева) и hг эф (справа) по замерам пачки и столбцы — изменение к предыдущему замеру."""
        frame = frame.sort_values('date')
        chart = Chart(f'gis-combo-{well}-{pack}', f'Скважина №{well}, пачка «{pack}»: Кг ср.взв и hг эф с изменениями',
                      Axis('Дата', scale='time'), Axis('Кг ср.взв', 'д.ед.'), crosshair=True, y2=Axis('hг эф', 'м'))
        for key, axis in (('kg', 'y'), ('h_eff', 'y2')):
            column, label, unit, _ = METRICS[key]
            values = frame[frame[column].notna()]
            if values.empty:
                continue
            ids = values['_point_id'].tolist() if '_point_id' in values else None
            change = values[column].diff()
            moved = values[change.notna()]
            chart.series.append(Series(f'Δ {label}', list(moved['date']), change.dropna().tolist(), 'bar', group=key,
                                       axis=axis, legend=False, labels=[f'{v:+.2f}' for v in change.dropna()]))
            chart.series.append(Series(label, list(values['date']), values[column].tolist(), 'line', group=key, markers=True,
                                       axis=axis, labels=[f'{v:g}' for v in values[column]], ids=ids,
                                       dataset=GIS if ids else None))
        return chart

    @staticmethod
    def change_table(part: pd.DataFrame) -> Table:
        """Изменение ГВК от первого замера пачки к последнему; скорость — м/год по календарным годам."""
        rows = []
        for (well, pack), frame in part[part['gvk_abs_m'].notna()].groupby(['well', 'pack']):
            first, last = frame.iloc[0], frame.iloc[-1]
            years = (last['date'] - first['date']).days / 365.25
            delta = last['gvk_abs_m'] - first['gvk_abs_m']
            rows.append({'well': str(well), 'pack': str(pack), 'n': len(frame),
                         'd0': first['date'], 'g0': first['gvk_abs_m'], 'd1': last['date'], 'g1': last['gvk_abs_m'],
                         'delta': delta, 'rate': delta / years if years > 0 else float('nan')})
        frame = pd.DataFrame(rows, columns=['well', 'pack', 'n', 'd0', 'g0', 'd1', 'g1', 'delta', 'rate'])
        return Table('gis-change', 'Изменение ГВК от первого замера к последнему', frame,
                     [Column('well', 'Скважина'), Column('pack', 'Пачка'), Column('n', 'Замеров'),
                      Column('d0', 'Первый', kind='date'), Column('g0', 'ГВК первый, м', decimals=2),
                      Column('d1', 'Последний', kind='date'), Column('g1', 'ГВК последний, м', decimals=2),
                      Column('delta', 'Δ, м', decimals=2), Column('rate', 'м/год', decimals=2)],
                     note='Скорость — изменение, делённое на число лет между первым и последним замером пачки.')

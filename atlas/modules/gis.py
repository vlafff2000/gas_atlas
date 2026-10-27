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
from atlas.engine.modules import gis_hikg

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, ParamError, Result, Series, Stat, Table
from ..domain import DatasetKind
from . import gis_an_tables, gis_tiles

GIS = DatasetKind.GIS_PACKS
INTERVALS = DatasetKind.GIS_INTERVALS
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
    part['pack'] = part['pack'].astype(object).where(part['pack'].notna(), 'без пачки').astype(str)
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
        optional=(INTERVALS,),
        order=75,
        builder_layouts=True,    # макеты «Конструктора графиков» графиками после основных
        params=(
            Param('wells', 'Скважины', 'multi', default=[], dynamic=True, empty='ничего', auto='first:3', section=SECTION),
            Param('packs', 'Пачки', 'multi', default=[], dynamic=True, empty='все', section=SECTION),
            Param('seasons', 'Сезоны', 'multi', default=[], dynamic=True, empty='все', section=SECTION),
            Param('view', 'График', 'choice', default='all', section='Вид', chart_kind=True, options=(
                Option('all', 'Все три'), *(Option(k, v[3]) for k, v in METRICS.items()),
                Option('combo', 'Кривая hэф и столбцы Кг'), Option('svod', 'Свод по пачкам, все скважины'),
                Option('tile', 'Плитка ГНТ и Кг по скважинам'), Option('hikg', 'Σ hi × Кг по исследованиям'), Option('an', 'Таблицы главы 5 АН (5.4–5.8)'))),
            Param('an_base', 'Новый сезон', 'choice', default='', dynamic=True, auto='last:1', section='Таблицы АН', show_if={'view': 'an'},
                  help='Сезон, от которого смотрим данные: по нему подбираются сезоны таблиц и считаются подписи. '
                       'По умолчанию самый поздний сезон с замерами.'),
            Param('an_seasons', 'Сезоны в таблицах', 'multi', default=[], dynamic=True, empty='ничего', section='Таблицы АН',
                  show_if={'view': 'an'}, help='Любое число сезонов. Пусто — автоматически до четырёх сезонов, считая от нового; '
                  'отмеченные вручную берутся все, как отмечены.'),
            Param('an_wells', 'Скважины таблиц', 'multi', default=[], dynamic=True, empty='все', section='Таблицы АН',
                  show_if={'view': 'an'}),
            Param('an_last_two', 'Δ только для двух последних сезонов', 'boolean', default=True, section='Таблицы АН',
                  show_if={'view': 'an'}, help='Как в отчёте (табл. 5.6, 5.8). Выключите, чтобы Δ были у каждого сезона.'),
            Param('gnt_min', 'Ось ГНТ, м: от', 'text', default='', section='Оси плитки', show_if={'view': 'tile'},
                  help='Пусто — границы подбираются автоматически (подсказка), число — задаёте вы.'),
            Param('gnt_max', 'Ось ГНТ, м: до', 'text', default='', section='Оси плитки', show_if={'view': 'tile'}),
            Param('kg_min', 'Ось Кг, %: от', 'text', default='', section='Оси плитки', show_if={'view': 'tile'}),
            Param('kg_max', 'Ось Кг, %: до', 'text', default='', section='Оси плитки', show_if={'view': 'tile'}),
            Param('start', 'С даты', 'date', default='', section=SECTION),
            Param('end', 'По дату', 'date', default='', section=SECTION),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name in ('an_base', 'an_seasons'):
            return gis_an_tables.available(data.get(GIS), data.get(INTERVALS))
        if name == 'an_wells':
            return ordered(df_w for df_w in data[GIS]['well'].astype(str).unique()) if GIS in data else []
        if name == 'seasons':
            if params.get('view') == 'tile':
                return gis_an_tables.available(data.get(GIS), keep=True)
            if INTERVALS not in data or data[INTERVALS].empty:
                return []
            return gis_hikg.season_order(gis_hikg.prepare(data[INTERVALS])['season'].dropna().astype(str).unique())
        df = data[GIS]
        if name == 'wells':
            return ordered(df['well'].astype(str).unique())
        if name == 'packs':
            return ordered(df['pack'].dropna().astype(str).unique())
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        if params['view'] == 'an':
            return self.run_an(data, params)
        if params['view'] == 'tile':
            return self.run_tile(data, params)
        if params['view'] == 'hikg':
            return self.run_hikg(data, params)
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
    def run_an(data: Data, params: dict[str, Any]) -> Result:
        """Таблицы 5.4–5.8 главы 5 «Авторского надзора» (``gis_an_tables``): сезоны подписываются от нового сезона."""
        result = Result()
        if GIS not in data or data[GIS].empty:
            result.notes.append(Note('В данных нет «Базы ГИС». Загрузите таблицу пачек через «Источники» или «Импорт данных».'))
            return result
        tables, labels, base, notes = gis_an_tables.build({'packs': data[GIS], 'intervals': data.get(INTERVALS)}, params)
        result.tables.extend(tables)
        result.notes.extend(Note(n, level='warning') for n in notes)
        if labels:
            result.summary = [Stat('Новый сезон', gis_an_tables.name_of(base)), Stat('Сезонов', str(len(labels)))]
            result.notes.append(Note('Сезоны таблиц: ' + '; '.join(gis_an_tables.name_of(x) for x in labels)
                                     + '. Список — подсказка: отметьте нужные сезоны вручную, и в таблицах будут именно они.'))
        return result

    @staticmethod
    def run_tile(data: Data, params: dict[str, Any]) -> Result:
        """Плитка «ГНТ и Кг»: график на скважину и пачку и таблица с Δ. Расчёт — ``gis_tiles``."""
        result = Result()
        if GIS not in data or data[GIS].empty:
            result.notes.append(Note('В данных нет «Базы ГИС». Загрузите таблицу пачек через «Источники» или «Импорт данных».'))
            return result
        wells = [w for w in params['wells'] if w in set(data[GIS]['well'].astype(str))]
        if not wells:
            result.notes.append(Note('Выберите скважины.'))
            return result
        labels = gis_an_tables.order(params['seasons']) if params['seasons'] else gis_an_tables.available(data[GIS], keep=True)
        if not labels:
            result.notes.append(Note('В базе ГИС нет замеров с сезоном (осень — после закачки, весна — после отбора).'))
            return result
        try:
            for prefix, label in (('gnt', 'ГНТ'), ('kg', 'Кг')):
                gis_tiles.axis_range(params, prefix, label)
        except ValueError as exc:
            raise ParamError(str(exc)) from None
        values = gis_tiles.season_values(data[GIS], wells, params['packs'], labels)
        if values.empty:
            result.notes.append(Note('За выбранные скважины, пачки и сезоны замеров нет.'))
            return result
        comments = dict(data.settings.get(gis_tiles.COMMENTS_KEY) or {}) if hasattr(data, 'settings') else {}
        for (well, pack), frame in values.groupby(['well', 'pack'], sort=True):
            result.charts.append(gis_tiles.chart(str(well), str(pack), frame, labels, params, comments))
        result.tables.append(gis_tiles.table(values, labels))
        gaps = gis_tiles.comment_rows(values, labels, comments)
        if len(gaps):
            result.tables.append(gis_tiles.comments_table(gaps))
        result.summary = [Stat('Скважин', str(values['well'].nunique())), Stat('Сезонов', str(len(labels)))]
        result.notes.append(Note('Столбцы: голубой — закачка (замер после закачки), красный — отбор (после отбора). В сезоне берётся '
                                 'последний замер пачки. Границы осей: пусто — автоматически, число — вручную.'))
        return result

    @staticmethod
    def run_hikg(data: Data, params: dict[str, Any]) -> Result:
        """Σ(hi × Кг) по каждому исследованию и пачке: таблица и график по скважинам. Расчёт — atlas/engine/modules/gis_hikg.py."""
        result = Result()
        if INTERVALS not in data or data[INTERVALS].empty:
            result.notes.append(Note('Нет интервалов ГИС: загрузите таблицу интервалов через «Импорт данных» («База ГИС»).'))
            return result
        raw = data[INTERVALS]
        wells = [w for w in params['wells'] if w in set(raw['well'].astype(str))]
        if not wells:
            result.notes.append(Note('Выберите скважины.'))
            return result
        prepared = gis_hikg.prepare(raw)
        part = prepared[prepared['well'].astype(str).isin(wells)]
        if params['packs']:
            part = part[part['pack'].astype(str).isin(params['packs'])]
        if params['seasons']:
            part = part[part['season'].isin(params['seasons'])]
        if params['start']:
            part = part[part['date'] >= pd.Timestamp(params['start'])]
        if params['end']:
            part = part[part['date'] <= pd.Timestamp(params['end'])]
        if part.empty:
            result.notes.append(Note('За выбранные скважины, сезоны и даты интервалов нет.'))
            return result
        table = gis_hikg.sums(part)
        result.tables.append(GisModule.hikg_table(table))
        changes = gis_hikg.season_changes(table)
        if not changes.empty:
            result.tables.append(GisModule.hikg_changes_table(changes))
        for well, frame in table.groupby(table['well'].astype(str), sort=True):
            result.charts.append(GisModule.hikg_chart(well, frame))
        missed = gis_hikg.skipped(part)
        if missed:
            result.notes.append(Note(f'Не вошли в расчёт интервалы без hi или Кг: {missed}. Их можно посмотреть в «Импорт данных».',
                                     level='warning'))
        result.notes.append(Note('Σ hi × Кг: по каждому интервалу с Кг выше нуля (в том числе 0,25 и ниже), сумма по пачке и '
                                 'исследованию. Точку можно исключить щелчком, как в других разделах.'))
        result.summary = [Stat('Скважин', str(len(wells))), Stat('Исследований', str(table[['well', 'date']].drop_duplicates().shape[0]))]
        return result

    @staticmethod
    def hikg_table(table: pd.DataFrame) -> Table:
        return Table('gis-hikg', 'Σ(hi × Кг) по исследованиям и пачкам', table,
                     [Column('well', 'Скважина'), Column('season', 'Сезон'), Column('date', 'Дата', kind='date'),
                      Column('investigation', 'Исследование'), Column('pack', 'Пачка'), Column('intervals', 'Интервалов'),
                      Column('hikg', 'Σ hi×Кг, м', decimals=2)],
                     note='Интервалы с Кг выше нуля: hi × Кг, сумма по пачке и исследованию.')

    @staticmethod
    def hikg_changes_table(changes: pd.DataFrame) -> Table:
        return Table('gis-hikg-changes', 'Изменение Σ hi × Кг между соседними сезонами', changes,
                     [Column('well', 'Скважина'), Column('pack', 'Пачка'), Column('from', 'Сезон было'),
                      Column('to', 'Сезон стало'), Column('v_from', 'Σ было', decimals=2), Column('v_to', 'Σ стало', decimals=2),
                      Column('delta', 'Δ, м', decimals=2), Column('pct', 'Δ, %', decimals=1)],
                     note='Значение сезона — среднее по его исследованиям. Δ — разность соседних сезонов по времени.')

    @staticmethod
    def hikg_chart(well: str, frame: pd.DataFrame) -> Chart:
        chart = Chart(f'gis-hikg-{well}', f'Скважина №{well}: Σ hi × Кг по исследованиям', Axis('Дата', scale='time'),
                      Axis('Σ hi × Кг', 'м'), crosshair=True)
        for pack, part in frame.groupby(frame['pack'].astype(str), sort=True):
            chart.series.append(Series(pack, list(part['date']), part['hikg'].tolist(), 'line', group=pack, markers=True,
                                       labels=[f'{v:.2f}' for v in part['hikg']]))
        return chart

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
            spring = part[part['season'].astype(str) == SPRING] if 'season' in part else part.iloc[0:0]
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
        """Кг ср.взв столбцами по замерам пачки (слева) и hг эф кривой (справа)."""
        frame = frame.sort_values('date')
        chart = Chart(f'gis-combo-{well}-{pack}', f'Скважина №{well}, пачка «{pack}»: Кг ср.взв (столбцы) и hг эф (кривая)',
                      Axis('Дата', scale='time'), Axis('Кг ср.взв', 'д.ед.'), crosshair=True, y2=Axis('hг эф', 'м'))
        kg = frame[frame['kg_avg'].notna()]
        if len(kg):
            chart.series.append(Series('Кг ср.взв', list(kg['date']), kg['kg_avg'].tolist(), 'bar', axis='y',
                                       labels=[f'{v:g}' for v in kg['kg_avg']]))
        heff = frame[frame['h_eff_m'].notna()]
        if len(heff):
            ids = heff['_point_id'].tolist() if '_point_id' in heff else None
            chart.series.append(Series('hг эф', list(heff['date']), heff['h_eff_m'].tolist(), 'line', markers=True,
                                       axis='y2', labels=[f'{v:g}' for v in heff['h_eff_m']], ids=ids,
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

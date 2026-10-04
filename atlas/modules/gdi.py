"""ГДИ: индикаторные диаграммы, коэффициенты, сравнения, выбросы, ручной фильтр точек.

Математика не переписана: подбор a, b, R², Qсв, сравнения и подсказки выбросов — ``app.modules.gdi`` из 5.8.
Здесь только выбор данных и представление. Полный перечень функций раздела — docs/parity/gdi.md.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from app.core.config import COLORS, natural_key
from app.modules import gdi as legacy

from ..contract import (Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Source,
                        Stat, Table, TableAction)
from ..domain import UNITS, DatasetKind

GDI = DatasetKind.GDI
CURVE_POINTS = 80
SYMBOLS = ('circle', 'square', 'diamond', 'triangle')
EXCLUDED_COLOR = '#969da5'

QUALITY_NOTE = ('Qmax наблюд. — максимальный измеренный расход. Qсв — формальная экстраполяция при Рзаб = 0 '
                'в принятой системе давлений, не допустимый режим эксплуатации. Он не выводится без Рпл или при плохом '
                'качестве подбора. Две точки не дают независимой проверки качества модели.')
COMPARISON_NOTE = ('Сравнение по точкам выполняется в общем диапазоне расходов при совпадающем методе и номере '
                   'исследования. Порог изменения ΔP² — 10 %. Причины изменения по этим данным автоматически не устанавливаются.')
OUTLIER_NOTE = ('Кривая по остальным точкам сравнивается с проверяемой точкой. Это рекомендация для проверки инженером; '
                'исключение применяется только после вашего подтверждения.')
PRODUCTIVITY_NOTE = ('Для каждого исследования берутся коэффициенты a и b (БД или расчет, как в таблице выше) и считается расход Q '
                     'при одном опорном ΔP² — наибольшем, достигнутом во всех исследованиях скважины, поэтому без экстраполяции. '
                     'Рост Q при том же ΔP² означает рост продуктивности. Метод, номер исследования и число точек не требуются: '
                     'нужны только давления и расходы, достаточно двух разных расходов на исследование.')
FILTER_NOTE = 'Отметьте «Исключить» и примените изменения. Исходные значения сохраняются; снятый флажок восстанавливает точку.'


def select(df: pd.DataFrame, wells: list[str], seasons: list[str], last_n: int) -> pd.DataFrame:
    """То же, что ``legacy.select_studies``, но пустой список скважин означает «все»."""
    d = legacy.prepare(df[df.well.isin(wells)] if wells else df)
    if seasons:
        d = d[d.season.isin(seasons)]
    if last_n:
        # Последние N дат по скважине; разные методы и исследования этих дат остаются раздельными.
        chosen = d[['well', 'date']].drop_duplicates().sort_values('date').groupby('well').tail(last_n)
        d = d.merge(chosen, on=['well', 'date'], how='inner')
    return d


def comparison_hints(chosen: pd.DataFrame, no_pairs: bool, no_triples: bool, last_n: int, by_seasons: bool) -> list[Note]:
    """Почему таблицы сравнения пусты. Сравниваются только даты с одним и тем же методом и номером исследования."""
    if not (no_pairs or no_triples):
        return []
    d = legacy.prepare(chosen)
    longest = d.groupby(['well', 'method', 'study'], dropna=False).date.nunique()
    dates = d.groupby('well').date.nunique()
    notes = []
    if no_pairs:
        if dates.max() < 2:
            hint = []
            if last_n and last_n < 2:
                hint.append('«Последние даты исследований» не меньше 2')
            if by_seasons:
                hint.append('снимите или расширьте выбор сезонов')
            notes.append(Note('Сравнивать не с чем: по каждой скважине выбрана одна дата исследования. '
                              + (f'Выберите {" и ".join(hint)}.' if hint else 'В данных нет более ранних исследований.'),
                              'warning'))
        else:
            split = int(((dates >= 2) & (longest.groupby('well').max() < 2)).sum())
            notes.append(Note('Сравнение с предыдущим исследованием пусто: даты скважины различаются методом или номером '
                              f'исследования (скважин: {split}), а сравниваются только исследования с совпадающими методом и номером. '
                              'Проверьте колонки «Метод» и «Исследование» в исходном файле.', 'warning'))
    if no_triples and not no_pairs:
        why = 'выбрано меньше трех дат' if last_n and last_n < 3 else 'нужно не менее трех дат с одним методом и номером исследования'
        notes.append(Note(f'Динамика трех последних исследований пуста: {why}.'))
    elif no_triples and dates.max() >= 3:
        notes.append(Note('Динамика трех последних исследований пуста: нужно не менее трех дат с одним методом и номером исследования.'))
    return notes


def study_label(date, method: str = '', study: str = '') -> str:
    label = pd.Timestamp(date).strftime('%d.%m.%Y')
    for part in (method, study):
        if part:
            label += f', {part}'
    return label


def well_key(well) -> tuple:
    return tuple((0, p, '') if isinstance(p, int) else (1, 0, p) for p in natural_key(well))


def natural_order(table: pd.DataFrame, by=('date', 'method', 'study'), ascending=True) -> pd.DataFrame:
    """Скважины в естественном порядке (31, 45, 132), внутри — по ``by``."""
    if table.empty:
        return table.reset_index(drop=True)
    by = [c for c in by if c in table]
    return (table.assign(_k=table.well.map(well_key))
            .sort_values(['_k', *by], ascending=[True, *[ascending] * len(by)], kind='stable')
            .drop(columns='_k').reset_index(drop=True))


def coefficient_columns() -> list[Column]:
    q, p = UNITS['q_gdi'], UNITS['pressure']
    return [
        Column('well', 'Скважина'), Column('date', 'Дата', kind='date'),
        Column('method', 'Метод'), Column('study', 'Исследование'),
        Column('a', 'a', decimals=5, kind='number'), Column('b', 'b', decimals=7, kind='number'),
        Column('r2', 'R²', decimals=4, kind='number'), Column('source', 'Выбрано'),
        Column('a_calc', 'a расчет', decimals=5, kind='number'), Column('b_calc', 'b расчет', decimals=7, kind='number'),
        Column('r2_calc', 'R² расчет', decimals=4, kind='number'),
        Column('a_db', 'a БД', decimals=5, kind='number'), Column('b_db', 'b БД', decimals=7, kind='number'),
        Column('r2_db', 'R² БД', decimals=4, kind='number'),
        Column('points', 'Всего точек', kind='number'), Column('fit_points', 'Точек подбора', kind='number'),
        Column('q_observed', 'Qmax наблюд.', q, 1, 'number'), Column('q_free', 'Qсв при Рзаб=0', q, 1, 'number'),
        Column('p_res', 'Рпл', p, 2, 'number'), Column('note', 'Замечания'),
    ]


class GdiModule(Module):
    history_action = 'Расчет ГДИ'
    spec = ModuleSpec(
        id='gdi',
        title='Газодинамические исследования',
        group='Исследования скважин',
        description='ΔP² = Рпл² − Рзаб² = aQ + bQ². Коэффициенты БД и расчетные значения доступны для сравнения.',
        needs=(GDI,),
        order=30,
        save_label='Сохранить расчет в историю',
        params=(
            Param('wells', 'Скважины', 'multi', default=[], source=Source(GDI, 'well'), section='Выбор данных'),
            Param('last_n', 'Последние даты исследований', 'choice', default=3, section='Выбор данных',
                  options=(Option(1, '1'), Option(2, '2'), Option(3, '3'), Option(0, 'Все'))),
            Param('seasons', 'Сезоны из исходного файла', 'multi', default=[], source=Source(GDI, 'season'),
                  section='Выбор данных'),
            Param('threshold', 'Порог R²', 'number', default=0.95, minimum=0.0, maximum=1.0, step=0.01,
                  setting='r2_threshold', section='Выбор данных',
                  help='Общая настройка проекта: действует во всех разделах и в версии 5.8'),
            Param('orientation', 'Оси', 'choice', default='standard', section='Вид', options=(
                Option('standard', 'X = Q, Y = ΔP²'), Option('swapped', 'X = ΔP², Y = Q'))),
            Param('curves', 'Расчетные кривые', 'boolean', default=True, section='Вид'),
            Param('db_curves', 'Кривые по коэффициентам БД', 'boolean', default=True, section='Вид'),
            Param('crosshair', 'Перекрестная линейка', 'boolean', default=True, section='Вид'),
            Param('show_excluded', 'Показывать исключенные точки', 'boolean', default=True, section='Вид'),
            Param('outliers', 'Искать возможные выбросы', 'boolean', default=False, section='Проверка точек'),
            Param('outlier_threshold', 'Порог отклонения', 'number', default=15, minimum=5, maximum=100, step=5,
                  unit='%', section='Проверка точек'),
        ),
    )

    # --- расчёт ---
    def run(self, data: Data, params: dict[str, Any]) -> Result:
        wells, seasons, n = params['wells'], params['seasons'], int(params['last_n'])
        chosen = select(data[GDI], wells, seasons, n)
        original = select(data.raw[GDI], wells, seasons, n)
        result = Result()
        if chosen.empty:
            result.notes.append(Note('Под выбранные условия не попало ни одного исследования. Выберите скважины с данными.',
                                     'warning'))
        else:
            table = natural_order(legacy.analyze(chosen, params['threshold']))
            for well in sorted(chosen.well.unique(), key=well_key):
                result.charts.append(self.chart(chosen[chosen.well.eq(well)], table[table.well.eq(well)],
                                                original[original.well.eq(well)], well, params))
            result.tables.append(Table('studies', 'Коэффициенты и качество', table, coefficient_columns(),
                                       note=QUALITY_NOTE))
            weak = int((table.r2.isna() | (table.r2 < params['threshold'])).sum())
            excluded = int(original['_point_id'].isin(data.excluded).sum()) if '_point_id' in original else 0
            result.summary = [
                Stat('Скважин', str(chosen.well.nunique())), Stat('Исследований', str(len(table))),
                Stat('Точек', str(len(chosen))),
                Stat('Период', f'{chosen.date.min():%d.%m.%Y} – {chosen.date.max():%d.%m.%Y}'),
                Stat(f'R² ниже {params["threshold"]:g}', str(weak), 'Или без подбора коэффициентов'),
                Stat('Исключено точек', str(excluded), 'В выбранных исследованиях')]
            if weak:
                result.notes.append(Note(f'Исследований с R² ниже {params["threshold"]:g} или без подбора: '
                                         f'{weak} из {len(table)}.', 'warning'))
            self.productivity(result, chosen, table)
            self.comparisons(result, chosen, int(params['last_n']), bool(params['seasons']))
            if params['outliers']:
                self.outliers(result, chosen, params['outlier_threshold'])
        if not original.empty:
            result.tables.append(self.point_table(original, data.excluded))
        return result

    @staticmethod
    def productivity(result: Result, chosen: pd.DataFrame, studies: pd.DataFrame) -> None:
        """Динамика продуктивности по зависимостям ΔP² = aQ + bQ² всех выбранных исследований скважины.

        Метод и номер исследования не нужны: исследования идут по датам. Без числа точек и общего диапазона —
        сравнивается расход при одном опорном ΔP² (наибольшем, достигнутом во всех исследованиях скважины).
        """
        d = legacy.prepare(chosen)
        valid = d[d.q.gt(0) & d.dp2.gt(0) & np.isfinite(d.q) & np.isfinite(d.dp2)]
        top = valid.groupby(legacy.KEYS, dropna=False).dp2.max().rename('dp2_max').reset_index()
        t = studies.merge(top, on=legacy.KEYS, how='left')
        t['fit'] = t.a.notna() & t.b.notna()
        rows = []
        for well in sorted(t.well.unique(), key=well_key):
            g = t[t.well.eq(well)].sort_values(['date', 'method', 'study'], kind='stable')
            usable = g[g.fit & g.dp2_max.notna()]
            ref = float(usable.dp2_max.min()) if len(usable) else None
            first = previous = None
            for r in g.itertuples(index=False):
                q = legacy.free_flow(r.a, r.b, np.sqrt(ref)) if ref and r.fit else None
                change_prev = (q / previous - 1) * 100 if q is not None and previous else None
                change_first = (q / first - 1) * 100 if q is not None and first else None
                if q is not None:
                    previous = q
                    first = q if first is None else first
                rows.append({'well': well, 'date': r.date, 'method': r.method, 'study': r.study, 'ref': ref, 'q_ref': q,
                             'to_previous': change_prev, 'to_first': change_first, 'source': r.source,
                             'mode': 'нет коэффициентов' if not r.fit else ''})
        table = pd.DataFrame(rows)
        result.tables.append(Table('productivity', 'Динамика продуктивности по исследованиям', table, [
            Column('well', 'Скважина'), Column('date', 'Дата', kind='date'),
            Column('method', 'Метод'), Column('study', 'Исследование'),
            Column('ref', 'Опорный ΔP²', UNITS['dp2'], 1, 'number'),
            Column('q_ref', 'Q при опорном ΔP²', UNITS['q_gdi'], 1, 'number'),
            Column('to_previous', 'К предыдущему', '%', 1, 'number'), Column('to_first', 'К первому', '%', 1, 'number'),
            Column('source', 'Коэффициенты'), Column('mode', 'Замечание'),
        ], note=PRODUCTIVITY_NOTE))
        last = table.dropna(subset=['to_first']).groupby('well').tail(1)
        if len(last):
            summary = [Stat('Продуктивность выросла', str(int(last.to_first.gt(1).sum())), 'Скважин: последнее исследование выше первого более чем на 1 %'),
                       Stat('Продуктивность снизилась', str(int(last.to_first.lt(-1).sum())), 'Скважин: последнее исследование ниже первого более чем на 1 %')]
            result.summary += summary

    @staticmethod
    def comparisons(result: Result, chosen: pd.DataFrame, last_n: int = 0, by_seasons: bool = False) -> None:
        compare = legacy.comparisons(chosen)
        compare = natural_order(compare.rename(columns={'Скважина': 'well'}), by=('Метод', 'Исследование'))
        if compare.empty:
            compare = pd.DataFrame(columns=['well', 'Метод', 'Исследование', 'Новое', 'Предыдущее',
                                            'Изменение ΔP², %', 'Результат'])
        result.tables.append(Table('comparison', 'Сравнение с предыдущим исследованием', compare, [
            Column('well', 'Скважина'), Column('Метод', 'Метод'), Column('Исследование', 'Исследование'),
            Column('Новое', 'Новое', kind='date'), Column('Предыдущее', 'Предыдущее', kind='date'),
            Column('Изменение ΔP², %', 'Изменение ΔP²', '%', 1, 'number'), Column('Результат', 'Результат'),
        ], note=COMPARISON_NOTE))
        three = legacy.compare_three(chosen)
        three = natural_order(three.rename(columns={'Скважина': 'well'}), by=('Метод', 'Исследование'))
        names = ['Метод', 'Исследование', 'Раннее', 'Среднее', 'Последнее', 'Последнее / среднее',
                 'Среднее / раннее', 'Последнее / раннее', 'Динамика']
        if three.empty:
            three = pd.DataFrame(columns=['well', *names])
        result.tables.append(Table('compare_three', 'Динамика трех последних исследований', three, [
            Column('well', 'Скважина'),
            *(Column(c, c, kind='date' if c in ('Раннее', 'Среднее', 'Последнее') else 'text') for c in names)],
            collapsed=not three.empty))
        if not compare.empty:
            counts = compare['Результат'].value_counts()
            result.summary += [Stat('Улучшение ΔP²', str(int(counts.get('Улучшение', 0))), 'Сравнение с предыдущим исследованием'),
                               Stat('Ухудшение ΔP²', str(int(counts.get('Ухудшение', 0))), 'Рост ΔP² более чем на 10 %')]
        result.notes += comparison_hints(chosen, compare.empty, three.empty, last_n, by_seasons)

    @staticmethod
    def outliers(result: Result, chosen: pd.DataFrame, threshold: float) -> None:
        found = legacy.outlier_suggestions(chosen, threshold)
        if found.empty:
            result.notes.append(Note('Точек, соответствующих критериям подсказки выбросов, не найдено.'))
            return
        found = natural_order(found, by=('date', 'q'))
        result.tables.append(Table('outliers', 'Подсказки выбросов', found, [
            Column('well', 'Скважина'), Column('date', 'Дата', kind='date'),
            Column('method', 'Метод'), Column('study', 'Исследование'),
            Column('q', 'Q', UNITS['q_gdi'], 3, 'number'), Column('dp2', 'ΔP²', decimals=3, kind='number'),
            Column('expected_dp2', 'ΔP² по остальным точкам', decimals=3, kind='number'),
            Column('deviation_percent', 'Отклонение', '%', 1, 'number'),
            Column('r2_without_point', 'R² без точки', decimals=4, kind='number'),
        ], note=OUTLIER_NOTE, action=TableAction('exclude', GDI, 'id', 'Исключить подтвержденные точки',
                                                  reason='Подсказка выброса подтверждена инженером',
                                                  reason_editable=False)))

    @staticmethod
    def point_table(original: pd.DataFrame, excluded: Mapping[str, dict]) -> Table:
        """Как ручной фильтр 5.8: новые даты сверху, внутри даты — скважины по порядку."""
        d = original.assign(_excluded=original['_point_id'].isin(excluded),
                            _reason=original['_point_id'].map(lambda i: (excluded.get(i) or {}).get('reason', '')),
                            _k=original.well.map(well_key))
        d = d.sort_values(['date', '_k'], ascending=[False, True], kind='stable').drop(columns='_k').reset_index(drop=True)
        columns = [Column('well', 'Скважина'), Column('date', 'Дата', kind='date'), Column('method', 'Метод'),
                   Column('study', 'Исследование'), Column('q', 'Q', UNITS['q_gdi'], 3, 'number'),
                   Column('dp2', 'ΔP²', decimals=3, kind='number')]
        for key, label, unit, decimals, kind in (('p_res', 'Рпл', UNITS['pressure'], 2, 'number'),
                                                 ('p_bh', 'Рзаб', UNITS['pressure'], 2, 'number'),
                                                 ('file', 'Файл', '', None, 'text'), ('sheet', 'Лист', '', None, 'text'),
                                                 ('_row', 'Строка', '', None, 'number')):
            if key in d:
                columns.append(Column(key, label, unit, decimals, kind))
        columns.append(Column('_reason', 'Причина исключения'))
        return Table('points', 'Ручной фильтр точек', d, columns, note=FILTER_NOTE, collapsed=True,
                     action=TableAction('exclude', GDI, '_point_id', 'Применить ручной фильтр',
                                        checked_column='_excluded'))

    @staticmethod
    def chart(points: pd.DataFrame, studies: pd.DataFrame, original: pd.DataFrame, well: str, params) -> Chart:
        """Как ``app.modules.charts.gdi_chart``: цвет по дате (последняя — красная), маркер по исследованию."""
        swapped = params['orientation'] == 'swapped'
        q_axis = Axis('Q', UNITS['q_gdi'], from_zero=True)
        dp_axis = Axis('ΔP²', UNITS['dp2'], from_zero=True)
        chart = Chart(f'gdi-{well}', f'Скважина {well}', *(dp_axis, q_axis) if swapped else (q_axis, dp_axis),
                      crosshair=params['crosshair'])
        dates = sorted(points.date.unique(), reverse=True)
        palette = {d: COLORS[i % len(COLORS)] for i, d in enumerate(dates)}
        coefficients = {(r.date, r.method, r.study): r for r in studies.itertuples(index=False)}

        def xy(q, y):
            return (y, q) if swapped else (q, y)

        for i, (key, g) in enumerate(points.groupby(legacy.KEYS, sort=False, dropna=False)):
            _, date, method, study = key
            row = coefficients[(date, method, study)]
            label = study_label(date)
            color = palette[date]
            chart.series.append(Series(label, *xy(g.q.to_numpy(float), g.dp2.to_numpy(float)), 'points', group=label,
                                       color=color, symbol=SYMBOLS[i % len(SYMBOLS)],
                                       ids=g['_point_id'].tolist() if '_point_id' in g else None, dataset=GDI))
            grid = np.linspace(0, max(float(g.q.max()), 1.0) * 1.05, CURVE_POINTS)
            curves = []
            if params['curves']:
                curves.append(('расчет', row.a_calc, row.b_calc, row.r2_calc, False))
            if params['db_curves']:
                curves.append(('БД', row.a_db, row.b_db, row.r2_db, True))
            for suffix, a, b, r2, dashed in curves:
                if a is None or b is None or not np.isfinite(a + b):
                    continue
                tip = f'a = {a:.6g}, b = {b:.6g}' + (f', R² = {r2:.4f}' if r2 is not None and np.isfinite(r2) else '')
                chart.series.append(Series(f'{label}, {suffix}', *xy(grid, a * grid + b * grid * grid), 'line',
                                           group=label, color=color, dashed=dashed, legend=False, tooltip=tip))
        if params['show_excluded'] and '_point_id' in original and '_point_id' in points:
            gone = original[~original['_point_id'].isin(points['_point_id'])]
            if not gone.empty:
                chart.series.append(Series('Исключенные точки', *xy(gone.q.to_numpy(float), gone.dp2.to_numpy(float)),
                                           'points', color=EXCLUDED_COLOR, hollow=True,
                                           tooltip='Исключено из расчета'))
        return chart

    # --- сохранённые параметры: формат 5.8 (settings.panels.gdi и событие «Расчет ГДИ») ---
    def save_state(self, params: dict[str, Any], data: Data) -> dict[str, Any]:
        wells = params['wells'] or sorted(data.raw[GDI].well.dropna().astype(str).unique(), key=natural_key)
        return {'wells': wells, 'n': int(params['last_n']), 'orientation': params['orientation'],
                'curves': params['curves'], 'db_curves': params['db_curves'], 'crosshair': params['crosshair'],
                'seasons': params['seasons'], 'show_excluded': params['show_excluded'], 'threshold': params['threshold']}

    def load_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        mapping = (('wells', 'wells'), ('n', 'last_n'), ('orientation', 'orientation'), ('curves', 'curves'),
                   ('db_curves', 'db_curves'), ('crosshair', 'crosshair'), ('seasons', 'seasons'),
                   ('show_excluded', 'show_excluded'))
        return {new: state[old] for old, new in mapping if state.get(old) is not None}

"""Сезонные показатели: накопленный объём газа за сезон отдельно по закачке и по отбору, по объекту и по группам.

Границы сезонов — те же, что в остальных разделах (автоопределение или «Расписание периодов» в «Настройках»);
исключённые точки не учитываются. Источник объёма: эталон узла учёта («БД по учету газа»), если он есть, иначе сумма по скважинам.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Stat, Table
from ..domain import DatasetKind
from . import _seasonal as S
from ._production import PRODUCTION, group_of, groups_of, periods_of, visible_periods

GAS_DB = DatasetKind.GAS_DB
SECTION = 'Выбор данных'
Q_UNIT = 'тыс. м³/сут'
NOTE = ('Сезон — период закачки или отбора по границам, принятым в проекте (автоопределение или «Расписание периодов» в '
        '«Настройках»: там же границы правятся вручную). Объём — сумма суточных расходов объекта в границах сезона, '
        'средний расход — по суткам с положительным расходом. Δ — к предыдущему сезону того же вида. '
        'Цикл — год: закачка этого года и отбор, начавшийся с июля этого года.')


def _cols(prefix: str = '') -> list[Column]:
    return [Column(f'{prefix}period', 'Сезон'), Column(f'{prefix}start', 'Начало', kind='date'),
            Column(f'{prefix}end', 'Конец', kind='date'), Column(f'{prefix}days', 'Суток с расходом', kind='number'),
            Column(f'{prefix}volume', 'Объём', 'млн м³', 2, 'number'),
            Column(f'{prefix}mean', 'Средний расход', Q_UNIT, 1, 'number'),
            Column(f'{prefix}max', 'Максимальный расход', Q_UNIT, 1, 'number'),
            Column(f'{prefix}delta', 'Δ к прошлому сезону', 'млн м³', 2, 'number'),
            Column(f'{prefix}delta_pct', 'Δ к прошлому сезону', '%', 1, 'number')]


class SeasonalModule(Module):
    spec = ModuleSpec(
        id='seasonal',
        title='Сезонные показатели',
        group='Эксплуатация',
        description='Накопленный объём газа за сезон отдельно по закачке и отбору: объект, группы, сравнение сезонов.',
        needs=(PRODUCTION,),
        optional=(GAS_DB,),
        order=12,
        params=(
            Param('source', 'Источник объёма', 'choice', default=S.SOURCE_AUTO, section=SECTION, options=(
                Option(S.SOURCE_AUTO, 'Автоматически: узел учёта, если есть'), Option(S.SOURCE_REF, 'Эталон узла учёта'),
                Option(S.SOURCE_WELLS, 'Сумма по скважинам')),
                help='Эталон — «БД по учету газа». Автоматически он берётся, если покрывает не менее 80 % суток сезона; '
                     'расхождение с суммой по скважинам показано в таблице'),
            Param('periods', 'Сезоны', 'multi', default=[], dynamic=True, empty='все', section=SECTION,
                  help='Пусто — все сезоны закачки и отбора'),
            Param('month_periods', 'Сезоны на графиках по месяцам', 'multi', default=[], dynamic=True, empty='ничего', section=SECTION,
                  help='Сравнение месяцев внутри сезонов. Пусто — последние три сезона каждого вида. Таблица по месяцам содержит все сезоны'),
            Param('groups', 'Группы', 'multi', default=[], dynamic=True, empty='все', section=SECTION,
                  help='Для таблицы и графиков по группам; пусто — все группы'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        df = data[PRODUCTION]
        if name in ('periods', 'month_periods'):
            return visible_periods(sorted(set(periods_of(df, 'injection')) | set(periods_of(df, 'withdrawal'))), data.settings)
        if name == 'groups':
            return groups_of(df, data.mapping)
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        df = data[PRODUCTION]
        ref = data[GAS_DB] if GAS_DB in data else None
        seasons = S.season_table(df, ref, params.get('source') or S.SOURCE_AUTO, params.get('periods') or None)
        if seasons.empty:
            result.notes.append(Note('Нет сезонов с расходом по выбранным условиям.', 'warning'))
            return result
        result.notes.append(Note(NOTE))
        mapping = {str(w): group_of(data.mapping, w) for w in df.well.unique()}
        by_group = S.group_table(df, seasons, mapping, params.get('groups') or None)
        months = S.month_table(df, seasons, ref)
        by_month_group = S.month_group_table(df, seasons, mapping, params.get('groups') or None)
        result.summary = self.summary(seasons)
        result.charts += self.charts(seasons, by_group)
        result.charts += self.month_charts(months, by_month_group, params.get('month_periods') or [])
        result.tables += self.tables(seasons, by_group)
        result.tables += self.month_tables(months, by_month_group)
        if seasons.source.eq(S.SOURCE_LABEL[S.SOURCE_REF]).any():
            far = seasons[seasons.diff_pct.abs() > 5]
            if len(far):
                result.notes.append(Note('Узел учёта и сумма по скважинам расходятся больше чем на 5 %: ' + '; '.join(
                    f'{S.KIND_LABEL[r.kind].lower()} {r.period} ({r.diff_pct:+.1f} %)' for r in far.itertuples()) + '.', 'warning'))
        return result

    @staticmethod
    def summary(seasons: pd.DataFrame) -> list[Stat]:
        out = []
        for kind in S.KINDS:
            part = seasons[seasons.kind.eq(kind)]
            if part.empty:
                continue
            last = part.iloc[-1]
            out.append(Stat(f'{S.KIND_LABEL[kind]}: сезонов', str(len(part))))
            out.append(Stat(f'{S.KIND_LABEL[kind]}, последний сезон', f'{last.volume:.2f} млн м³',
                            f'Сезон {last.period}; источник: {last.source}'))
            out.append(Stat(f'{S.KIND_LABEL[kind]}, всего', f'{part.volume.sum():.2f} млн м³', 'Сумма по показанным сезонам'))
        return out

    @staticmethod
    def charts(seasons: pd.DataFrame, by_group: pd.DataFrame) -> list[Chart]:
        cycles = S.cycles_table(seasons)
        cats = [str(c) for c in cycles.cycle]
        chart = Chart('seasonal-volume', 'Объём газа за сезон: закачка и отбор', Axis('Цикл (год)', scale='category', categories=cats),
                      Axis('Объём за сезон', 'млн м³', from_zero=True))
        for kind, tag in (('injection', 'i'), ('withdrawal', 'w')):
            if cycles[f'{tag}_volume'].notna().any():
                labels = [f'сезон {p}, {int(d)} сут' if isinstance(p, str) else '' for p, d in zip(cycles[f'{tag}_period'], cycles[f'{tag}_days'].fillna(0))]
                chart.series.append(Series(S.KIND_LABEL[kind], cats, cycles[f'{tag}_volume'].to_numpy(float), 'bar', group=kind, labels=labels))
        out = [chart]
        for kind in S.KINDS:
            part = by_group[by_group.kind.eq(kind)]
            if part.empty:
                continue
            periods = list(dict.fromkeys(part.period))
            c = Chart(f'seasonal-groups-{kind}', f'{S.KIND_LABEL[kind]}: объём по группам',
                      Axis('Сезон', scale='category', categories=periods), Axis('Объём за сезон', 'млн м³', from_zero=True))
            for name, rows in part.groupby('group', sort=True):
                by = rows.set_index('period').volume
                c.series.append(Series(str(name), periods, np.array([by.get(p, np.nan) for p in periods], float), 'bar',
                                       group=str(name), stack='groups'))
            out.append(c)
        return out

    @staticmethod
    def tables(seasons: pd.DataFrame, by_group: pd.DataFrame) -> list[Table]:
        cycles = S.cycles_table(seasons)
        side = Table('seasonal-cycles', 'Все сезоны: закачка и отбор', cycles,
                     [Column('cycle', 'Цикл', kind='number')] + _cols('i_') + _cols('w_'),
                     note='Δ — разница с предыдущим сезоном того же вида: млн м³ и % от него.',
                     header=[[('', 1), ('Закачка', 9), ('Отбор', 9)]])
        detail = Table('seasonal-sources', 'Источник объёма и расхождение', seasons[['kind', 'period', 'source', 'volume', 'volume_wells', 'volume_ref', 'diff_pct', 'delta', 'delta_pct', 'wells']]
                       .assign(kind=lambda f: f.kind.map(S.KIND_LABEL)), [
            Column('kind', 'Вид'), Column('period', 'Сезон'), Column('source', 'Взят источник'),
            Column('volume', 'Объём в расчёте', 'млн м³', 2, 'number'), Column('volume_wells', 'Сумма по скважинам', 'млн м³', 2, 'number'),
            Column('volume_ref', 'Узел учёта', 'млн м³', 2, 'number'), Column('diff_pct', 'Узел учёта к скважинам', '%', 1, 'number'),
            Column('delta', 'Δ к прошлому сезону', 'млн м³', 2, 'number'), Column('delta_pct', 'Δ к прошлому сезону', '%', 1, 'number'),
            Column('wells', 'Скважин работало', kind='number')],
            note='Расхождение — (узел учёта − сумма по скважинам) / сумма по скважинам. Пусто — эталона узла учёта за сезон нет. '
                 'В выгрузке в Excel расхождение и Δ записаны формулами, объёмы можно править руками.',
            formulas={'diff_pct': 'IF(AND(ISNUMBER({volume_ref}),{volume_wells}>0),({volume_ref}-{volume_wells})/{volume_wells}*100,"")',
                      'delta': 'IF({kind}={kind@prev},{volume}-{volume@prev},"")',
                      'delta_pct': 'IF(AND({kind}={kind@prev},{volume@prev}>0),({volume}-{volume@prev})/{volume@prev}*100,"")'})
        out = [side, detail]
        if not by_group.empty:
            out.append(Table('seasonal-by-group', 'Сезоны по группам', by_group.assign(kind=lambda f: f.kind.map(S.KIND_LABEL)), [
                Column('kind', 'Вид'), Column('period', 'Сезон'), Column('group', 'Группа'),
                Column('days', 'Суток с расходом', kind='number'), Column('volume', 'Объём', 'млн м³', 2, 'number'),
                Column('share', 'Доля в сумме групп', '%', 1, 'number'), Column('mean', 'Средний расход', Q_UNIT, 1, 'number'),
                Column('max', 'Максимальный расход', Q_UNIT, 1, 'number')],
                note='Группы — по схеме проекта; доля считается от суммы выбранных групп сезона. Объём групп всегда по скважинам.'))
        return out

    @staticmethod
    def month_charts(months: pd.DataFrame, by_group: pd.DataFrame, chosen: list[str]) -> list[Chart]:
        """Столбцы по месяцам, ряд — сезон; для последнего выбранного сезона вида — ещё стопка по группам."""
        out: list[Chart] = []
        for kind in S.KINDS:
            part = months[months.kind.eq(kind)]
            if part.empty:
                continue
            periods = [p for p in dict.fromkeys(part.sort_values('no').period) if p in chosen] if chosen else \
                list(dict.fromkeys(part.sort_values('no').period))[-3:]
            if not periods:
                continue
            first = part[part.period.eq(periods[0])].sort_values('month').moy.tolist()
            order = first + sorted({m for m in part.moy if m not in first}, key=lambda m: (m - first[0]) % 12)
            cats = [S.MONTHS[m - 1] for m in order]
            noun = S.KIND_LABEL[kind]
            c = Chart(f'seasonal-months-{kind}', f'{noun}: объём по месяцам сезонов', Axis('Месяц', scale='category', categories=cats),
                      Axis('Объём за месяц', 'млн м³', from_zero=True))
            for period in periods:
                rows = part[part.period.eq(period)].set_index('moy')
                c.series.append(Series(period, cats, np.array([rows.volume.get(m, np.nan) for m in order], float), 'bar', group=period,
                                       labels=[f'{int(rows.days[m])} сут' + (', неполный месяц' if rows.partial[m] else '') if m in rows.index else ''
                                               for m in order]))
            out.append(c)
            g = by_group[by_group.kind.eq(kind) & by_group.period.eq(periods[-1])]
            if not g.empty:
                months_g = sorted(g.month.unique())
                cats_g = [S.month_name(m) for m in months_g]
                cg = Chart(f'seasonal-months-groups-{kind}', f'{noun}: объём по месяцам и группам · {periods[-1]}',
                           Axis('Месяц', scale='category', categories=cats_g), Axis('Объём за месяц', 'млн м³', from_zero=True))
                for name, rows in g.groupby('group', sort=True):
                    by = rows.set_index('month').volume
                    cg.series.append(Series(str(name), cats_g, np.array([by.get(m, np.nan) for m in months_g], float), 'bar',
                                            group=str(name), stack='groups'))
                out.append(cg)
        return out

    @staticmethod
    def month_tables(months: pd.DataFrame, by_group: pd.DataFrame) -> list[Table]:
        if months.empty:
            return []
        frame = months.assign(kind=lambda f: f.kind.map(S.KIND_LABEL), month=lambda f: f.month.map(S.month_name),
                              partial=lambda f: f.partial.map({True: 'неполный', False: ''}))
        prev = lambda col: f'SUMIFS({{{col}@col}},{{kind@col}},{{kind}},{{moy@col}},{{moy}},{{no@col}},{{no}}-1)'  # noqa: E731
        has = 'COUNTIFS({kind@col},{kind},{moy@col},{moy},{no@col},{no}-1)=0'
        out = [Table('seasonal-months', 'Месяцы сезонов', frame[['kind', 'period', 'no', 'month', 'moy', 'partial', 'days', 'volume', 'mean',
                                                                   'max', 'delta', 'delta_pct']], [
            Column('kind', 'Вид'), Column('period', 'Сезон'), Column('no', '№ сезона вида', kind='number'), Column('month', 'Месяц'),
            Column('moy', 'Номер месяца', kind='number'), Column('partial', 'Месяц сезона'),
            Column('days', 'Суток с расходом', kind='number'), Column('volume', 'Объём', 'млн м³', 2, 'number'),
            Column('mean', 'Средний расход', Q_UNIT, 1, 'number'), Column('max', 'Максимальный расход', Q_UNIT, 1, 'number'),
            Column('delta', 'Δ к тому же месяцу прошлого сезона', 'млн м³', 2, 'number'),
            Column('delta_pct', 'Δ к тому же месяцу прошлого сезона', '%', 1, 'number')],
            note='Месяцы календарные. «Неполный» — сезон начался позже 1-го числа или закончился раньше конца месяца: объём такого месяца '
                 'нельзя сравнивать с полным. Δ — к тому же календарному месяцу предыдущего сезона того же вида (в Excel — формулами).',
            formulas={'delta': f'IF({has},"",{{volume}}-{prev("volume")})',
                      'delta_pct': f'IF(OR({has},{prev("volume")}<=0),"",({{volume}}-{prev("volume")})/{prev("volume")}*100)'})]
        if not by_group.empty:
            out.append(Table('seasonal-months-groups', 'Месяцы сезонов по группам', by_group.assign(
                kind=lambda f: f.kind.map(S.KIND_LABEL), month=lambda f: f.month.map(S.month_name),
                partial=lambda f: f.partial.map({True: 'неполный', False: ''}))[['kind', 'period', 'group', 'month', 'partial', 'days', 'volume', 'mean', 'max']], [
                Column('kind', 'Вид'), Column('period', 'Сезон'), Column('group', 'Группа'), Column('month', 'Месяц'),
                Column('partial', 'Месяц сезона'), Column('days', 'Суток с расходом', kind='number'),
                Column('volume', 'Объём', 'млн м³', 2, 'number'), Column('mean', 'Средний расход', Q_UNIT, 1, 'number'),
                Column('max', 'Максимальный расход', Q_UNIT, 1, 'number')], note='Группы — по скважинам проекта, суммы групп за месяц.'))
        return out

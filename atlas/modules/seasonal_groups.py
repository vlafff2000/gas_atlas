"""Сезонные показатели по группам: участие группы в сезонах, объёмы, баланс закачки и отбора, скважины и простои.

Продолжает «Сезонные показатели»: те же сезоны и границы, те же правила исключений и пропусков. Всё по скважинам.
Подсказки (дисбаланс, мало работала, простаивала) показаны с причиной — итоговое решение за инженером.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Param, Result, Series, Stat, Table
from . import _seasonal as S
from . import _seasonal_groups as G
from ..domain import DatasetKind
from ._production import PRODUCTION, group_of, groups_of

GAS_DB = DatasetKind.GAS_DB
SECTION = 'Выбор данных'
SECTION_RULES = 'Пороги подсказок'
NOTE = ('Сезоны — как в «Сезонных показателях». Доля — от суммы всех групп сезона; Δ доли — в процентных пунктах к прошлому сезону того же вида. '
        'Баланс — отбор и закачка группы за цикл (год): подсказка, если разница больше порога. Простой — сутки с нулевым расходом; '
        'пропуски («нет данных») не считаются. Подсказки — не выводы: решение о дисбалансе и простое за инженером.')


class SeasonalGroupsModule(Module):
    spec = ModuleSpec(
        id='seasonal_groups',
        title='Сезонные показатели по группам',
        group='Эксплуатация',
        description='Участие групп и скважин в сезонах: доли и их динамика, объёмы закачки и отбора, баланс по группам, простои.',
        needs=(PRODUCTION,),
        optional=(GAS_DB,),
        order=13,
        params=(
            Param('groups', 'Группы', 'multi', default=[], dynamic=True, empty='все', section=SECTION,
                  help='Для таблиц и графика по группам; пусто — все группы'),
            Param('balance_tol', 'Порог дисбаланса', 'number', default=10.0, minimum=0, maximum=100, unit='%', section=SECTION_RULES,
                  help='Подсказка в балансе, если отбор отличается от закачки за цикл больше чем на эту долю'),
            Param('work_low', 'Порог малой работы', 'number', default=50.0, minimum=0, maximum=100, unit='%', section=SECTION_RULES,
                  help='Подсказка «мало работала», если скважина дала расход меньше чем в этой доле суток сезона'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'groups':
            return groups_of(data[PRODUCTION], data.mapping)
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        df = data[PRODUCTION]
        ref = data[GAS_DB] if GAS_DB in data else None
        seasons = S.season_table(df, ref, S.SOURCE_AUTO)
        if seasons.empty:
            result.notes.append(Note('Нет сезонов с расходом: сначала загрузите эксплуатацию и проверьте границы сезонов.', 'warning'))
            return result
        result.notes.append(Note(NOTE))
        mapping = {str(w): group_of(data.mapping, w) for w in df.well.unique()}
        groups = params.get('groups') or None
        wells = G.well_table(df, seasons, mapping, float(params.get('work_low', 50.0)))
        all_groups = G.group_table(wells, seasons)
        by_group = G.group_table(wells, seasons, groups)
        if by_group.empty:
            result.notes.append(Note('Выбранные группы не работали в сезонах.', 'warning'))
            return result
        balance = G.balance_table(all_groups, groups, float(params.get('balance_tol', 10.0)))
        shown = wells[wells.group.isin(groups)] if groups else wells
        result.summary = self.summary(by_group, balance)
        result.charts += self.share_charts(by_group, seasons)
        result.charts += self.balance_charts(balance)
        result.tables += self.tables(by_group, balance, shown)
        return result

    @staticmethod
    def summary(by_group: pd.DataFrame, balance: pd.DataFrame) -> list[Stat]:
        out = [Stat('Групп', str(by_group.group.nunique())), Stat('Сезонов', str(by_group.period.nunique()))]
        hints = int((balance.hint.ne('') & balance.group.ne('Итого')).sum()) if not balance.empty else 0
        out.append(Stat('Дисбаланс: подсказок', str(hints), 'Циклы, где отбор и закачка группы расходятся больше порога'))
        idle = int(by_group.wells_idle.sum())
        out.append(Stat('Простаивало скважин', str(idle), 'Сумма по группам и сезонам: скважина без единых суток расхода в сезоне'))
        return out

    @staticmethod
    def share_charts(by_group: pd.DataFrame, seasons: pd.DataFrame) -> list[Chart]:
        out: list[Chart] = []
        for kind in S.KINDS:
            part = by_group[by_group.kind.eq(kind)]
            if part.empty:
                continue
            order = seasons[seasons.kind.eq(kind)].sort_values('start').period.tolist()
            periods = [p for p in order if p in set(part.period)]
            c = Chart(f'seasonal-groups-share-{kind}', f'{S.KIND_LABEL[kind]}: доля группы в сезоне',
                      Axis('Сезон', scale='category', categories=periods), Axis('Доля в сумме групп', '%', from_zero=True))
            for name, rows in part.groupby('group', sort=True):
                by = rows.set_index('period').share
                c.series.append(Series(str(name), periods, np.array([by.get(p, np.nan) for p in periods], float), 'line',
                                       group=str(name), markers=True))
            out.append(c)
        return out

    @staticmethod
    def balance_charts(balance: pd.DataFrame) -> list[Chart]:
        part = balance[balance.group.ne('Итого')]
        if part.empty:
            return []
        keys = sorted(part.cycle.unique())
        c = Chart('seasonal-groups-balance', 'Баланс по группам: отбор минус закачка за цикл',
                  Axis('Цикл (год)', scale='category', categories=[str(k) for k in keys]), Axis('Отбор − закачка', 'млн м³'))
        for name, rows in part.groupby('group', sort=True):
            by = rows.set_index('cycle')['diff']
            c.series.append(Series(str(name), [str(k) for k in keys], np.array([by.get(k, np.nan) for k in keys], float), 'bar',
                                   group=str(name)))
        return [c]

    @staticmethod
    def tables(by_group: pd.DataFrame, balance: pd.DataFrame, wells: pd.DataFrame) -> list[Table]:
        out = [Table('seasonal-groups-share', 'Группы по сезонам', by_group.assign(kind=lambda f: f.kind.map(S.KIND_LABEL)), [
            Column('kind', 'Вид'), Column('period', 'Сезон'), Column('group', 'Группа'),
            Column('volume', 'Объём', 'млн м³', 2, 'number'), Column('share', 'Доля в сумме групп', '%', 1, 'number'),
            Column('delta_share', 'Δ доли к прошлому сезону', 'п. п.', 1, 'number'),
            Column('wells', 'Скважин с данными', kind='number'), Column('wells_work', 'Работало', kind='number'),
            Column('wells_idle', 'Простаивало целиком', kind='number'),
            Column('idle_days', 'Суток простоя (нулевой расход)', kind='number')],
            note='Доля и Δ считаются от суммы всех групп сезона, даже если в таблице выбраны не все. Простаивало — скважина без единых '
                 'суток расхода в сезоне; сутки простоя — строки с нулевым расходом.')]
        if not balance.empty:
            frame = balance.assign(hint=balance.hint.where(balance.hint.ne(''), '—'))
            out.append(Table('seasonal-groups-balance', 'Баланс закачки и отбора по группам', frame, [
                Column('cycle', 'Цикл', kind='number'), Column('group', 'Группа'),
                Column('injection', 'Закачка', 'млн м³', 2, 'number'), Column('withdrawal', 'Отбор', 'млн м³', 2, 'number'),
                Column('diff', 'Отбор − закачка', 'млн м³', 2, 'number'), Column('ratio', 'Отбор к закачке', '%', 1, 'number'),
                Column('hint', 'Подсказка (причина)')],
                note='Подсказка показывает, почему цикл выглядит подозрительно; это не вывод. Пороги — в параметрах раздела.'))
        if not wells.empty:
            frame = wells.assign(kind=lambda f: f.kind.map(S.KIND_LABEL), status=lambda f: f.status.where(f.status.ne(''), '—'),
                                 work_pct=lambda f: f.work_pct.round(1))
            out.append(Table('seasonal-groups-wells', 'Скважины в сезонах', frame, [
                Column('kind', 'Вид'), Column('period', 'Сезон'), Column('group', 'Группа'), Column('well', 'Скважина'),
                Column('span', 'Суток в сезоне', kind='number'), Column('flow_days', 'Суток с расходом', kind='number'),
                Column('idle_days', 'Суток простоя', kind='number'), Column('work_pct', 'Работа от суток сезона', '%', 1, 'number'),
                Column('volume', 'Объём', 'млн м³', 2, 'number'), Column('share', 'Доля в группе сезона', '%', 1, 'number'),
                Column('status', 'Подсказка (причина)')],
                note='Работа — доля суток сезона с расходом. Скважины без записей в сезоне не показаны: пропуск — не простой.'))
        return out

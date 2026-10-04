"""Группы и подгруппы скважин: ручное назначение и автоматические подгруппы по среднему дебиту.

Математика не переписана: подгруппы — ``app.modules.production.partitions`` из 5.8, предпросмотр —
та же гистограмма средних, что в разделе «Гистограммы». Назначения пишутся в проект (``manifest.groups``)
через ``POST /api/projects/{id}/groups`` — тот же формат, что у 5.8. Перечень функций — docs/parity/groups.md.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd

from app.modules import production as legacy

from ..contract import Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Table, TableAction
from .fund import program_wells
from ._production import KINDS, PRODUCTION, group_of, histogram_charts, periods_of

SECTION_AUTO = 'Автоматические подгруппы'
SECTION_BULK = 'Массовое назначение'
SORTS = (Option('desc', 'По убыванию дебита'), Option('asc', 'По возрастанию дебита'), Option('number', 'По номеру'))

ASSIGN_NOTE = ('Впишите группу и подгруппу в ячейках и сохраните. Пустая группа — «Без группы». '
               'Назначения общие с версией 5.8 и действуют во всех разделах.')
AUTO_NOTE = ('Скважины каждой группы упорядочены по среднему дебиту за выбранные периоды и разбиты по заданному числу. '
             'Применение меняет только подгруппы; группы остаются прежними.')


def subgroup_of(mapping, well: str) -> str:
    return mapping.get(well, {}).get('subgroup', '')


class GroupsModule(Module):
    spec = ModuleSpec(
        id='groups',
        title='Группы и подгруппы',
        group='Фонд скважин',
        description='Назначьте состав вручную или распределите скважины по среднему дебиту внутри каждой группы.',
        optional=(PRODUCTION,),
        order=50,
        save_label='Сохранить параметры подгрупп',
        params=(
            Param('bulk_wells', 'Номера скважин', 'text', default='', section=SECTION_BULK,
                  help='Через пробел, запятую, «;» или перенос строки: 74, 89, 190'),
            Param('bulk_group', 'Группа для них', 'text', default='', section=SECTION_BULK,
                  help='Название группы; пусто — «Без группы»'),
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section=SECTION_AUTO),
            Param('size', 'Скважин в подгруппе', 'integer', default=8, minimum=1, maximum=100, section=SECTION_AUTO),
            Param('direction', 'Сортировка', 'choice', default='desc', options=SORTS, section=SECTION_AUTO),
            Param('periods', 'Периоды расчета', 'multi', default=[], dynamic=True, depends=('kind',), auto='all',
                  empty='ничего', section=SECTION_AUTO),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'periods':
            if PRODUCTION not in data or data[PRODUCTION].empty:
                return []
            return periods_of(data[PRODUCTION], params.get('kind') or 'withdrawal')
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        wells = list(data.wells)
        if not wells:
            result.notes.append(Note('Сначала загрузите данные: скважины появятся здесь после импорта.'))
            return result
        result.tables.append(self.assignments(data, wells))
        self.bulk(result, data, wells, params)
        if PRODUCTION not in data or data[PRODUCTION].empty:
            result.notes.append(Note('Автоматические подгруппы считаются по данным эксплуатации. Загрузите отбор и закачку, '
                                     'чтобы распределять скважины по дебиту.'))
            return result
        self.auto(result, data, wells, params)
        return result

    @staticmethod
    def assignments(data: Data, wells: list[str]) -> Table:
        frame = pd.DataFrame({'well': wells,
                              'group': [group_of(data.mapping, w) for w in wells],
                              'subgroup': [subgroup_of(data.mapping, w) for w in wells]})
        return Table('assignments', 'Назначения', frame,
                     [Column('well', 'Скважина'), Column('group', 'Группа'), Column('subgroup', 'Подгруппа')],
                     note=ASSIGN_NOTE,
                     action=TableAction('assign', None, 'well', 'Сохранить назначения', fields=('group', 'subgroup'),
                                        editable=('group', 'subgroup'), journal='Назначение групп'))

    @staticmethod
    def bulk(result: Result, data: Data, wells: list[str], params: dict[str, Any]) -> None:
        """Массовое назначение: скважины по номерам из списка получают одну группу; не найденные — в отчёте."""
        wanted = program_wells(params['bulk_wells'])
        if not wanted:
            return
        found = [w for w in wanted if w in set(wells)]
        missing = [w for w in wanted if w not in set(wells)]
        group = params['bulk_group'].strip() or 'Без группы'
        result.notes.append(Note('Массовое назначение в группу «{}»: найдено {}, не найдено {}{}.'.format(
            group, len(found), len(missing), ': ' + ', '.join(missing[:20]) if missing else ''),
            'warning' if missing else 'info'))
        if not found:
            return
        frame = pd.DataFrame({'well': found, 'current': [group_of(data.mapping, w) for w in found], 'group': group})
        result.tables.append(Table('bulk', 'Массовое назначение', frame,
                                   [Column('well', 'Скважина'), Column('current', 'Группа сейчас'),
                                    Column('group', 'Новая группа')],
                                   note='Кнопка записывает «Новую группу» всем скважинам списка; подгруппы не меняются.',
                                   action=TableAction('assign', None, 'well', 'Назначить группу списку', fields=('group',),
                                                      submit='all', journal='Назначение групп')))

    @staticmethod
    def auto(result: Result, data: Data, wells: list[str], params: dict[str, Any]) -> None:
        df, kind = data[PRODUCTION], params['kind']
        ps = [p for p in params['periods'] if p in periods_of(df, kind)]
        parts = legacy.partitions(df, data.mapping, kind, ps, wells, 'auto', int(params['size']), params['direction'])
        rows = [{'label': label, 'well': w, 'group': group_of(data.mapping, w), 'current': subgroup_of(data.mapping, w),
                 'subgroup': label.rsplit(' / ', 1)[1]} for label, ws in parts.items() for w in ws]
        frame = pd.DataFrame(rows, columns=['label', 'well', 'group', 'current', 'subgroup'])
        summary = pd.DataFrame([{'label': k, 'wells': ', '.join(ws)} for k, ws in parts.items()], columns=['label', 'wells'])
        result.tables.append(Table('auto-summary', 'Автоматические подгруппы', summary,
                                   [Column('label', 'Подгруппа'), Column('wells', 'Скважины')], note=AUTO_NOTE))
        if not ps:
            result.notes.append(Note('Выберите периоды расчета, чтобы применить автоматические подгруппы.'))
            return
        result.tables.append(Table('auto-apply', 'Применение автоматических подгрупп', frame,
                                   [Column('label', 'Подгруппа'), Column('well', 'Скважина'), Column('group', 'Группа'),
                                    Column('current', 'Подгруппа сейчас'), Column('subgroup', 'Новая подгруппа')],
                                   note='Кнопка записывает «Новую подгруппу» всем скважинам таблицы.',
                                   action=TableAction('assign', None, 'well', 'Применить автоматические подгруппы',
                                                      fields=('subgroup',), submit='all',
                                                      journal='Автоматические подгруппы')))
        if parts:
            first = next(iter(parts))
            sel = SimpleNamespace(df=df, kind=kind, periods=ps)
            chart = histogram_charts(sel, parts[first], 'well', max(1, len(parts[first])), 'groups')[0]
            chart.id, chart.title = 'groups-preview', first
            result.charts.append(chart)

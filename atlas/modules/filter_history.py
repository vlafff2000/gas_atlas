"""История фильтра: состояния исключений до и после каждого изменения и параметры ГДИ до/после.

В 5.8 — страница «История фильтра» (``app/ui/extras.py::render_extra``). Записи — журнал проекта 5.8 с
``before_exclusions``/``after_exclusions`` (их пишут ручной фильтр, исключение кликом и восстановление);
сравнение ГДИ — ``atlas.engine.core.history.comparison``. Восстановление состояния — ``POST exclusions/state``
(atlas/api_exclusions.py), действие «Восстановление фильтра», как в 5.8. Перечень функций — docs/parity/filter_history.md.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from atlas.engine.core.history import comparison

from ..contract import Column, Command, Data, Module, ModuleSpec, Note, Option, Param, Result, Table
from . import _journal

EMPTY = 'История начнет заполняться при исключении или восстановлении точек.'
SIDES = {'before': ('До изменения', 'before_exclusions'), 'after': ('После изменения', 'after_exclusions')}


def records_table(records) -> pd.DataFrame:
    rows = []
    for i, (row, details) in enumerate(records, 1):
        rows.append({'n': i, 'date': row['Дата'], 'action': row['Действие'],
                     'added': len(details.get('added_ids', [])), 'removed': len(details.get('removed_ids', [])),
                     'before': len(details.get('before_exclusions', {})), 'after': len(details.get('after_exclusions', {}))})
    return pd.DataFrame(rows)


def gdi_table(details: dict[str, Any]) -> pd.DataFrame:
    """``comparison`` 5.8; даты — датами для показа."""
    d = comparison(details)
    if not d.empty:
        d['Дата'] = pd.to_datetime(d['Дата'], errors='coerce')
    return d


GDI_COLUMNS = [Column('Состояние', 'Состояние'), Column('Скважина', 'Скважина'), Column('Дата', 'Дата', kind='date'),
               Column('Метод', 'Метод'), Column('Исследование', 'Исследование'),
               Column('a', 'a', decimals=5, kind='number'), Column('b', 'b', decimals=7, kind='number'),
               Column('R²', 'R²', decimals=4, kind='number'), Column('Qmax', 'Qmax', 'тыс. м³/сут', 1, 'number'),
               Column('Точек', 'Точек', kind='number')]


class FilterHistoryModule(Module):
    spec = ModuleSpec(
        id='filter_history',
        title='История фильтра',
        group='Проект',
        description='Состояния исключений и расчетные параметры ГДИ до и после изменения.',
        order=91,
        save_label='',
        params=(
            Param('record', 'Изменение №', 'integer', default=1, minimum=1, step=1, section='Изменение',
                  help='Номер из таблицы «Изменения фильтра»; 1 — последнее'),
            Param('state', 'Состояние для восстановления', 'choice', default='before', section='Изменение',
                  options=tuple(Option(k, v[0]) for k, v in SIDES.items())),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        info = data.project
        if info is None:
            return Result(notes=[Note('Сведения о проекте недоступны. Обновите страницу.', 'warning')])
        records = _journal.filter_records(info.history())
        if not records:
            return Result(notes=[Note(EMPTY)])
        result = Result()
        result.tables.append(Table('records', 'Изменения фильтра', records_table(records), [
            Column('n', '№', kind='number'), Column('date', 'Дата', kind='date'), Column('action', 'Действие'),
            Column('added', 'Добавлено исключений', kind='number'), Column('removed', 'Восстановлено', kind='number'),
            Column('before', 'Исключено до', kind='number'), Column('after', 'Исключено после', kind='number')],
            note='Время — UTC; новые изменения сверху. Номер изменения выбирается на панели.'))
        n = int(params['record'])
        if n > len(records):
            result.notes.append(Note(f'Изменения № {n} нет: в истории {len(records)}. Выберите номер из таблицы.', 'warning'))
            return result
        row, details = records[n - 1]
        label, field = SIDES[params['state']]
        result.notes.append(Note(f'Изменение № {n} · {row["Действие"]}. Добавлено исключений: '
                                 f'{len(details.get("added_ids", []))}, восстановлено: {len(details.get("removed_ids", []))}.'))

        gdi = gdi_table(details)
        if not gdi.empty:
            result.tables.append(Table('gdi', 'Параметры ГДИ до и после изменения', gdi, GDI_COLUMNS))

        target = details.get(field, {})
        current = data.excluded
        excluded_more = sum(1 for k in target if k not in current)
        returned = sum(1 for k in current if k not in target)
        result.notes.append(Note(f'В выбранном состоянии («{label.lower()}») исключено показателей: {len(target)}. '
                                 f'По сравнению с текущим фильтром будет исключено {excluded_more}, возвращено {returned}.'))
        if target:
            frame, columns = _journal.table(_journal.journal(target))
            result.tables.append(Table('state', f'Исключения в состоянии «{label.lower()}»', frame, columns, collapsed=True))
        result.commands.append(Command(
            'Восстановить выбранное состояние фильтра', 'exclusions/state',
            {'at': str(row['Дата']), 'side': params['state'], 'revision': data.revision},
            confirm=f'Заменить текущий фильтр состоянием «{label.lower()}» изменения № {n}?',
            done='Фильтр восстановлен. Данные и кривые пересчитаны.', primary=True))
        return result

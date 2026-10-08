"""Исключенные точки: журнал всех исключений проекта, восстановление выбранных и всех.

В 5.8 — страница «Исключенные точки» (``PointControls.manager``). Журнал общий с 5.8 (``settings.excluded_points``),
восстановление пишет в историю то же действие «Ручной фильтр точек». Перечень функций — docs/parity/exclusions.md.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from atlas.engine.core.config import ordered

from ..contract import Command, Data, Module, ModuleSpec, Note, Option, Param, Result, Table, TableAction
from ..domain import DatasetKind
from . import _journal

EMPTY = ('Исключенных точек нет. Включите «Исключать точки кликом» на панели раздела с графиками '
         'или используйте ручной фильтр под его таблицами.')
RESTORE_NOTE = ('Снимите флажок «Исключено» у показателей, которые нужно вернуть в расчеты, и нажмите '
                '«Восстановить выбранные». Исходные значения не менялись: точки возвращаются как были.')
SECTION = 'Отбор исключений'


def chosen(data: Data, params: dict[str, Any], skip: str = '') -> pd.DataFrame:
    """Журнал по выбору модулей, скважин, горизонтов и причин (``skip`` — параметр, варианты которого считаются)."""
    d = _journal.journal(data.excluded)
    if d.empty:
        return d
    for name, column in (('modules', 'module'), ('wells', 'well'), ('horizons', 'horizon'), ('reasons', 'reason')):
        if name == skip or not params.get(name):
            continue
        d = d[d[column].astype(str).isin(params[name])] if column in d else d.iloc[0:0]
    return d


class ExclusionsModule(Module):
    spec = ModuleSpec(
        id='exclusions',
        title='Исключенные точки',
        group='Проект',
        description='Восстановите выбранные показатели, отмените последнее исключение или верните весь исходный набор.',
        order=90,
        save_label='',
        params=(
            Param('modules', 'Модуль исключений', 'multi', default=[], section=SECTION,
                  options=tuple(Option(k.value, _journal.module_label(k.value)) for k in DatasetKind)),
            Param('wells', 'Скважины', 'multi', default=[], section=SECTION, dynamic=True, depends=('modules',),
                  prefix='№ '),
            Param('horizons', 'Горизонты', 'multi', default=[], section=SECTION, dynamic=True, depends=('modules',)),
            Param('reasons', 'Причины', 'multi', default=[], section=SECTION, dynamic=True, depends=('modules',)),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        column = {'wells': 'well', 'horizons': 'horizon', 'reasons': 'reason'}.get(name)
        if column is None:
            return super().options(name, data, params)
        d = chosen(data, {'modules': params.get('modules', [])})
        return ordered(d[column].dropna().astype(str).loc[lambda s: s.ne('')]) if column in d else []

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        everything = _journal.journal(data.excluded)
        if everything.empty:
            return Result(notes=[Note(EMPTY)])
        result = Result(notes=[Note(f'Исключенных показателей: {len(everything)}. '
                                    'Исходные значения сохранены; изменения сразу видны и в версии 5.8.')])
        any_module = DatasetKind(str(everything['module'].iloc[0]))
        # «Восстановить все» — весь журнал, как в 5.8, независимо от отбора.
        result.commands.append(Command(
            'Восстановить все', 'exclusions',
            {'dataset': any_module.value, 'remove': everything['id'].astype(str).tolist(), 'add': []},
            confirm=f'Вернуть в расчеты все исключенные показатели ({len(everything)})?',
            done='Все исключенные показатели возвращены в расчеты.'))
        d = chosen(data, params)
        if d.empty:
            result.notes.append(Note('По выбранным условиям исключений нет. Очистите отбор, чтобы увидеть весь журнал.',
                                     'warning'))
            return result
        frame, columns = _journal.table(d)
        frame['_excluded'] = True
        result.tables.append(Table(
            'journal', 'Журнал исключений', frame, columns, note=RESTORE_NOTE,
            action=TableAction('exclude', any_module, 'id', 'Восстановить выбранные', reason='',
                               checked_column='_excluded', reason_editable=False, column='Исключено')))
        if len(d) < len(everything):
            result.notes.append(Note(f'По выбору показано {len(d)} из {len(everything)}.'))
        return result

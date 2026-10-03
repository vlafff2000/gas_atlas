"""Обзор проекта: основные показатели, состав наборов данных, история действий, рабочие правила.

В 5.8 — страница «Обзор» (``app/main.py``). Состав считается тем же ``Project.catalog`` 5.8, журнал — ``Store.history``.
Перечень функций — docs/parity/overview.md.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from ..contract import Column, Data, Module, ModuleSpec, Note, Result, Table
from . import _journal

RULES = ('Последний период — красный, предыдущие — синий, зеленый и оранжевый.',
         'Средний дебит учитывает дни с положительным расходом. Накопленный объем считается по всему объекту.',
         'Уровень жидкости отображается с перевернутой осью глубины.')
DETAILS_LIMIT = 300
# Большие поля записей фильтра (полные состояния до и после) в журнале заменяются числом.
BULKY = ('before_exclusions', 'after_exclusions', 'gdi_before', 'gdi_after', 'added_ids', 'removed_ids')


def metrics(info) -> pd.DataFrame:
    """Четыре показателя шапки «Обзора» 5.8 (``metrics`` в app/main.py)."""
    catalog, tables = info.catalog(), info.tables
    return pd.DataFrame([{'wells': len(catalog['wells']), 'production': tables.get('production', 0),
                          'gdi': tables.get('gdi', 0), 'response': tables.get('response', 0)}])


def composition(info) -> pd.DataFrame:
    """«Состав проекта» 5.8: модуль, строк, скважин, с, по."""
    rows = [{'module': _journal.module_label(mod), 'rows': entry['rows'], 'wells': len(entry['wells']),
             'start': entry['start'], 'end': entry['end']} for mod, entry in info.catalog()['modules'].items()]
    return pd.DataFrame(rows, columns=['module', 'rows', 'wells', 'start', 'end'])


def summary(text: Any) -> str:
    """«Подробности» записи кратко: состояния фильтра — числом, остальное — JSON, не длиннее DETAILS_LIMIT."""
    details = _journal.details_of(text)
    if not details:
        return '' if text in (None, '{}') else str(text)[:DETAILS_LIMIT]
    short = {k: v for k, v in details.items() if k not in BULKY and k != 'rows'}
    if 'added_ids' in details or 'removed_ids' in details:
        short = {'исключено': len(details.get('added_ids', [])), 'возвращено': len(details.get('removed_ids', [])),
                 'всего исключено': len(details.get('after_exclusions', {})), **short}
    out = json.dumps(short, ensure_ascii=False, default=str)
    return out if len(out) <= DETAILS_LIMIT else out[:DETAILS_LIMIT - 1] + '…'


class OverviewModule(Module):
    spec = ModuleSpec(
        id='overview',
        title='Обзор',
        group='Проект',
        description='Единый проект: исходные файлы, расчеты и настройки сохраняются на вашем компьютере.',
        order=0,
        save_label='',
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        info = data.project
        if info is None:
            return Result(notes=[Note('Сведения о проекте недоступны. Обновите страницу.', 'warning')])
        result = Result()
        if info.demo:
            result.notes.append(Note('ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ. Для рабочих файлов создайте отдельный проект.', 'warning'))
        result.notes.append(Note(f'Проект «{info.name}».'))
        result.tables.append(Table('metrics', 'Основные показатели', metrics(info), [
            Column('wells', 'Скважин', kind='number'), Column('production', 'Динамика', kind='number'),
            Column('gdi', 'Точек ГДИ', kind='number'), Column('response', 'Замеров уровней', kind='number')]))

        parts = composition(info)
        if parts.empty:
            result.notes.append(Note('Данных пока нет. Загрузите книгу Excel или текстовую таблицу в разделе «Импорт данных» '
                                     'версии 5.8: проекты у обеих версий общие.'))
        else:
            result.tables.append(Table('composition', 'Состав проекта', parts, [
                Column('module', 'Модуль'), Column('rows', 'Строк', kind='number'),
                Column('wells', 'Скважин', kind='number'), Column('start', 'С', kind='date'),
                Column('end', 'По', kind='date')]))

        excluded = len(data.excluded)
        if excluded:
            result.notes.append(Note(f'Ручной фильтр: исключено {excluded} показателей. Исходные значения сохранены; '
                                     'восстановление — в разделе «Исключенные точки».'))

        history = info.history()
        if not history.empty:
            shown = pd.DataFrame({'date': history['Дата'], 'action': history['Действие'],
                                  'details': history['Подробности'].map(summary)})
            note = 'Время — UTC. Показаны последние 500 действий; полные состояния фильтра — в разделе «История фильтра».'
            result.tables.append(Table('history', 'История действий', shown, [
                Column('date', 'Дата', kind='date'), Column('action', 'Действие'), Column('details', 'Подробности')],
                note=note))
            calcs = int(history['Действие'].eq('Расчет ГДИ').sum())
            if calcs:
                result.notes.append(Note(f'Сохраненных расчетов ГДИ: {calcs}. Открыть расчет — в разделе ГДИ, '
                                         'список «Сохраненный расчет».'))

        result.notes.append(Note('Рабочие правила. ' + ' '.join(RULES)))
        return result

"""Проверка данных: сомнительные значения в таблицах проекта.

Нового в 5.8 нет. Поиск — ``atlas.quality`` (только находки: ничего не исключается само). Из таблицы находку можно
отметить и исключить, как точку на графике: отметка ложится в тот же журнал исключений, что и в 5.8.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .. import quality
from ..contract import Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Stat, Table, TableAction
from ..domain import DatasetKind

SETS = {'production': (DatasetKind.PRODUCTION, 'Эксплуатация'), 'gdi': (DatasetKind.GDI, 'ГДИ'),
        'response': (DatasetKind.RESPONSE, 'Реагирование')}
LEVELS = (Option('all', 'Все находки'), Option('error', 'Только ошибки'))


class QualityModule(Module):
    spec = ModuleSpec(
        id='quality',
        title='Проверка данных',
        group='Проект',
        description='Сомнительные значения: Рзаб выше Рпл, скачки дебита, нули в отборе, повторы, пропуски, не те единицы давления.',
        optional=tuple(k for k, _ in SETS.values()),
        order=5,
        params=(
            Param('level', 'Показывать', 'choice', default='all', options=LEVELS, section='Проверка'),
            Param('jump', 'Скачок дебита, раз', 'number', default=3.0, minimum=1.5, maximum=20, step=0.5, section='Проверка',
                  help='Расход отличается от соседних дней не менее чем в столько раз: находка «Скачок дебита».',
                  formula='отношение = Q дня / медиана Q трёх предыдущих и трёх следующих дней',
                  example='Соседние дни около 60, в этот день 600: отношение 10 — при пороге 3 это находка.'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        frames = {name: data.raw[kind] for name, (kind, _) in SETS.items() if kind in data.raw}
        if not frames:
            return Result(notes=[Note('В проекте нет данных для проверки. Загрузите таблицы в разделе «Импорт данных».')])
        found = quality.scan(frames, quality.Limits(jump=float(params['jump'])))
        if params['level'] == 'error':
            found = found[found.level.eq('ошибка')]
        result = Result()
        if found.empty:
            result.notes.append(Note('Сомнительных значений не найдено. Проверены: ' +
                                     ', '.join(label for name, (_, label) in SETS.items() if name in frames) + '.'))
            self._open_without_flow(frames.get('production'), result)
            return result
        errors = int(found.level.eq('ошибка').sum())
        result.summary = [Stat('Находок', str(len(found))), Stat('Ошибок', str(errors), 'Точки, которые расчёт не использует или считает неверно'),
                          Stat('Требуют внимания', str(len(found) - errors), 'Могут быть реальными событиями')]
        result.notes.append(Note('Это подсказки, а не приговор: скачок дебита может быть остановкой, ноль — настоящей остановкой. '
                                 'Подтверждённые точки отметьте флажками и исключите: исходные значения сохраняются, '
                                 'вернуть их можно в разделе «Исключенные точки».'))
        brief = quality.summary(found)
        result.tables.append(Table('summary', 'Сводка по проверкам', pd.DataFrame({
            'dataset': brief.dataset.map(lambda n: SETS[n][1]), 'check': brief.check, 'level': brief.level, 'count': brief['count']}), [
            Column('dataset', 'Набор'), Column('check', 'Проверка'), Column('level', 'Уровень'),
            Column('count', 'Находок', kind='number')]))
        for name, (kind, label) in SETS.items():
            part = found[found.dataset.eq(name)]
            if part.empty:
                continue
            part = part.drop(columns=['dataset']).reset_index(drop=True)
            marked = part['id'].astype(str).str.len().gt(0)
            columns = [Column('well', 'Скважина'), Column('date', 'Дата', kind='date'), Column('check', 'Проверка'),
                       Column('level', 'Уровень'), Column('value', 'Значение'), Column('details', 'Пояснение')]
            if (~marked).any():       # находки по набору в целом (например, единицы давления): исключать нечего
                result.tables.append(Table(f'general_{name}', f'{label}: общие замечания', part[~marked].drop(columns=['id']), columns))
            part = part[marked].reset_index(drop=True)
            if part.empty:
                continue
            part['_excluded'] = part['id'].isin(data.excluded)
            result.tables.append(Table(
                f'found_{name}', f'{label}: находки', part.rename(columns={'id': '_point_id'}), columns,
                note=f'Показаны первые {quality.LIMIT} находок каждой проверки.' if len(part) >= quality.LIMIT else '',
                action=TableAction('exclude', kind, '_point_id', 'Исключить отмеченные точки', reason='Проверка данных',
                                   checked_column='_excluded')))
        self._open_without_flow(frames.get('production'), result)
        return result

    @staticmethod
    def _open_without_flow(production, result: Result) -> None:
        """Статистика «скважина открыта, расхода нет»: строки сохраняются, закономерности выносятся отдельно."""
        stats = quality.open_without_flow(production)
        if stats is None:
            return
        if not stats['zero_days']:
            result.notes.append(Note('Суток «скважина открыта, расхода нет» в данных нет.'))
            return
        share = stats['zero_days'] / stats['open_days'] * 100
        result.summary.append(Stat('Открыта, расхода нет', f"{stats['zero_days']:,}".replace(',', '\u00a0'),
                                   f'{share:.1f} % рабочих суток. Строки сохранены и в расчётах участвуют как нулевой расход'))
        result.notes.append(Note(
            'Сутки с временем работы больше нуля и нулевым расходом — не ошибка и не пропуск: скважина открыта, но газ не '
            'идёт или не измеряется. Если такие сутки есть у одной скважины сериями — смотрите скважину (пробка, '
            'обводнение, арматура). Если сразу у многих скважин одной группы — смотрите замерный узел и систему сбора.'))
        result.tables.append(Table('open_no_flow_wells', 'Открыта, расхода нет: по скважинам', stats['wells'], [
            Column('well', 'Скважина'), Column('group', 'Группа'), Column('kind', 'Режим'),
            Column('open_days', 'Рабочих суток', kind='number', decimals=0),
            Column('zero_days', 'Без расхода, сут', kind='number', decimals=0),
            Column('share', 'Доля', unit='%', kind='number', decimals=1),
            Column('episodes', 'Серий подряд', kind='number', decimals=0),
            Column('longest', 'Самая длинная, сут', kind='number', decimals=0),
            Column('first', 'Впервые', kind='date'), Column('last', 'Последний раз', kind='date')],
            note='Режим: withdrawal — отбор, injection — закачка. Серия — подряд идущие сутки.'))
        result.tables.append(Table('open_no_flow_groups', 'Открыта, расхода нет: по группам (замерный узел)', stats['groups'], [
            Column('group', 'Группа'), Column('kind', 'Режим'),
            Column('days', 'Суток с открытыми скважинами', kind='number', decimals=0),
            Column('mass_days', 'Суток, когда без расхода половина и более', kind='number', decimals=0),
            Column('mass_longest', 'Самая длинная серия, сут', kind='number', decimals=0),
            Column('max_share', 'Наибольшая доля за сутки', unit='%', kind='number', decimals=0),
            Column('last', 'Последний раз', kind='date')],
            note='Сутки считаются «массовыми», если открыто не менее трёх скважин группы и расхода нет у половины и более.',
            collapsed=True))
        result.tables.append(Table('open_no_flow_months', 'Открыта, расхода нет: по месяцам', stats['months'], [
            Column('month', 'Месяц', kind='date'), Column('kind', 'Режим'),
            Column('open_days', 'Рабочих суток', kind='number', decimals=0),
            Column('zero_days', 'Без расхода, сут', kind='number', decimals=0),
            Column('share', 'Доля', unit='%', kind='number', decimals=1)], collapsed=True))

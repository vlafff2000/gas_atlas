"""Аналитика фонда: состав проекта, рейтинг динамики, качество последних ГДИ, выполнение программы ГДИ.

Математика не переписана: рейтинг и проверка программы — ``atlas.engine.modules.group_analysis.ranking / program``,
качество ГДИ — ``atlas.engine.modules.gdi.analyze`` из 5.8. Перечень функций — docs/parity/groups.md.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pandas as pd

from atlas.engine.core.config import ordered
from atlas.engine.modules import gdi as legacy_gdi
from atlas.engine.modules import group_analysis

from ..contract import Column, Data, Module, ModuleSpec, Note, Param, Result, Table
from ..domain import DatasetKind
from ._production import KINDS, PRODUCTION, periods_of, visible_periods

GDI, RESPONSE = DatasetKind.GDI, DatasetKind.RESPONSE
SECTION_RANK, SECTION_PROGRAM = 'Рейтинг динамики', 'Проверка выполнения программы ГДИ'

RANK_NOTE = 'Рейтинг по среднему дебиту за дни с положительным расходом; объем — по всем записям выбранных периодов.'


def program_wells(text: str) -> list[str]:
    """Номера скважин программы: через пробел, запятую, точку с запятой или перенос строки (как в 5.8)."""
    text = (text or '').strip()
    return ordered(w for w in re.split(r'[\s,;]+', text) if w)   # 5.8 оставлял пустой номер от «;» в конце


def program_span(start: str | None, end: str | None, today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """По умолчанию — с 1 января текущего года по сегодня, как в 5.8."""
    today = today or dt.date.today()
    return (dt.date.fromisoformat(start) if start else today.replace(month=1, day=1),
            dt.date.fromisoformat(end) if end else today)


class FundModule(Module):
    spec = ModuleSpec(
        id='fund',
        title='Аналитика фонда',
        group='Фонд скважин',
        description='Сводные показатели по выбранным данным. Рейтинг динамики взвешен по числу активных дней.',
        optional=(PRODUCTION, GDI, RESPONSE),
        order=51,
        params=(
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section=SECTION_RANK),
            Param('periods', 'Периоды', 'multi', default=[], dynamic=True, depends=('kind',), auto='all',
                  empty='ничего', section=SECTION_RANK),
            Param('program', 'Номера скважин программы', 'text', default='', section=SECTION_PROGRAM,
                  help='Через пробел, запятую или перенос строки'),
            Param('start', 'Начало периода программы', 'date', default=None, section=SECTION_PROGRAM,
                  help='Пусто — 1 января текущего года'),
            Param('end', 'Конец периода программы', 'date', default=None, section=SECTION_PROGRAM,
                  help='Пусто — сегодня'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'periods':
            if PRODUCTION not in data or data[PRODUCTION].empty:
                return []
            return visible_periods(periods_of(data[PRODUCTION], params.get('kind') or 'withdrawal'), data.settings)
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        result.tables.append(self.composition(data))
        has = lambda kind: kind in data and not data[kind].empty
        if has(PRODUCTION):
            self.ranking(result, data, params)
        if has(GDI):
            self.gdi_quality(result, data)
            self.program(result, data, params)
        if not has(PRODUCTION) and not has(GDI):
            result.notes.append(Note('Рейтинг и качество ГДИ появятся после загрузки эксплуатации и ГДИ в разделе импорта.'))
        return result

    @staticmethod
    def composition(data: Data) -> Table:
        """Плашки «Скважин / Динамика / Точек ГДИ / Замеров уровней» 5.8."""
        rows = lambda kind: len(data.raw[kind]) if kind in data.raw else 0
        frame = pd.DataFrame([{'what': 'Скважин', 'value': len(data.wells)},
                              {'what': 'Динамика', 'value': rows(PRODUCTION)},
                              {'what': 'Точек ГДИ', 'value': rows(GDI)},
                              {'what': 'Замеров уровней', 'value': rows(RESPONSE)}])
        return Table('composition', 'Состав данных', frame, [Column('what', 'Показатель'), Column('value', 'Количество', kind='number')])

    @staticmethod
    def ranking(result: Result, data: Data, params: dict[str, Any]) -> None:
        d, kind = data[PRODUCTION], params['kind']
        ps = [p for p in params['periods'] if p in periods_of(d, kind)]
        f = d[d.kind.eq(kind) & d.period.isin(ps)]
        if f.empty:
            result.notes.append(Note('Для рейтинга выберите периоды с данными эксплуатации.'))
            return
        stats = group_analysis.ranking(f, data.mapping)
        result.tables.append(Table('ranking', 'Рейтинг динамики', stats, [
            Column('Скважина', 'Скважина'), Column('Группа', 'Группа'),
            Column('Средний_тыс_м3_сут', 'Средний расход', 'тыс. м³/сут', 2, 'number'),
            Column('Объем_млн_м3', 'Объем', 'млн м³', 3, 'number'),
            Column('Активных_дней', 'Активных дней', decimals=0, kind='number'),
            Column('Записей', 'Записей', kind='number'), Column('Нулевых', 'Нулевых записей', kind='number')],
            note=RANK_NOTE))

    @staticmethod
    def gdi_quality(result: Result, data: Data) -> None:
        g = data[GDI]
        latest = legacy_gdi.analyze(legacy_gdi.select_studies(g, ordered(g.well), 1), data.settings.get('r2_threshold', .95))
        if latest.empty:
            return
        frame = latest[['well', 'date', 'points', 'r2', 'source', 'note']]
        result.tables.append(Table('gdi-quality', 'Качество последних ГДИ', frame, [
            Column('well', 'Скважина'), Column('date', 'Дата', kind='date'), Column('points', 'Точек', kind='number'),
            Column('r2', 'R²', decimals=4, kind='number'), Column('source', 'Выбрано'), Column('note', 'Замечания')]))

    @staticmethod
    def program(result: Result, data: Data, params: dict[str, Any]) -> None:
        ws = program_wells(params['program'])
        if not ws:
            return
        start, end = program_span(params['start'], params['end'])
        if start > end:
            result.notes.append(Note('Начало периода программы позже конца. Поменяйте даты местами.', 'warning'))
            return
        table = group_analysis.program(data[GDI], ws, start, end)
        done = int(table['Статус'].eq('Проведено').sum())
        result.tables.append(Table('program', f'Выполнение программы · {start:%d.%m.%Y}–{end:%d.%m.%Y}', table, [
            Column('Скважина', 'Скважина'), Column('Дат исследований', 'Дат исследований', kind='number'),
            Column('Статус', 'Статус')], note=f'Проведено {done} из {len(ws)}.'))

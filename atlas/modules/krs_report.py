"""КРС: таблица 7.1 «информация о проведённых ремонтах» отчёта авторского надзора (и такая же для текущего ремонта ТР).

Вход — набор ``krs_plan`` (лист «План КР» книги КРС_для_Атласа.xlsx, собранный из справки о выполнении плана КР). Только выбор данных и
представление: таблица собирается по правилу «Ремонт будет / В таблицу 7.1», которое подсказывает скрипт (статус «Утвержден» — ремонт
ещё будет, другой статус — скважины в плане уже нет), а инженер переписывает вручную в книге или исключает строку в проекте.
Даты — фактические, пустая дата окончания — ремонт ещё идёт.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..contract import Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Stat, Table
from ..domain import DatasetKind
from .gdi import well_key

PLAN_K = DatasetKind.KRS_PLAN
EMPTY_HINT = ('Плана КР в проекте нет: соберите лист «План КР» скриптом «Состояние скважин и приоритет КР» из справки о выполнении плана '
              '(параметр «справка») и загрузите книгу КРС_для_Атласа.xlsx во вкладке «Импорт».')
NOTE = ('Таблица собрана из справки о выполнении плана КР: в неё входят скважины, по которым ремонт выполнен, идёт или ещё будет '
        '(статус «Утвержден»). Скважины с другим статусом и красные в справке (не делают) показываются только в режиме «Все строки справки». '
        'Состояние берётся по цвету справки и датам; расхождения вынесены в столбец «Проверить». Решает инженер: «Ремонт будет» и '
        '«В таблицу 7.1» можно переписать в книге вручную, ручное значение не затирается при пересчёте.')
COLUMNS = [Column('well', '№ скважины'), Column('well_type', 'Тип скважины'), Column('start', 'Дата начала ремонта', kind='date'),
           Column('end', 'Дата окончания ремонта', kind='date'), Column('works', 'Виды КР'), Column('state', 'Состояние'),
           Column('quarter', 'Квартал плана'), Column('status', 'Статус справки'), Column('check', 'Проверить')]


def select(plan: pd.DataFrame, scope: str, year: int | None) -> pd.DataFrame:
    df = plan.copy()
    if year:
        df = df[df.year.eq(year)]
    if scope != 'all':
        df = df[df.in_table.eq('Да')]
    df = df.assign(_k=df.well.map(well_key), _t=df.kind.eq('ТР'))
    return df.sort_values(['_k', 'start'], kind='stable')


class KrsReportModule(Module):
    spec = ModuleSpec(
        id='krs_report',
        title='КРС: таблица 7.1 (проведённые ремонты)',
        group='Авторский надзор',
        description='Таблица ремонтов года по справке о выполнении плана КР: скважина, тип, фактические даты начала и конца, шифры работ; '
                    'отдельно текущий ремонт ТР. Статус «Утвержден» — ремонт ещё будет, другой статус — в плане уже нет.',
        needs=(PLAN_K,),
        order=117,
        params=(
            Param('year', 'Год плана', 'number', default=0, minimum=0, maximum=2100, step=1, section='Выбор данных',
                  help='0 — все годы справки.'),
            Param('scope', 'Какие строки', 'choice', default='table', section='Выбор данных',
                  options=(Option('table', 'Для таблицы 7.1 (в плане)'), Option('all', 'Все строки справки')),
                  help='«Для таблицы 7.1» — ремонт выполнен, идёт или ещё будет; скважины со статусом, отличным от «Утвержден», и красные не входят.'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        if PLAN_K not in data or data[PLAN_K].empty:
            result.notes.append(Note(EMPTY_HINT))
            return result
        year = int(params['year']) or None
        df = select(data[PLAN_K], str(params['scope']), year)
        kr, tr = df[~df._t], df[df._t]
        result.summary = [Stat('Ремонтов в таблице', str(len(df))), Stat('Выполнено', str(int(df.state.eq('Выполнено').sum()))),
                          Stat('В процессе', str(int(df.state.eq('В процессе').sum())), 'Есть дата начала, даты окончания пока нет'),
                          Stat('К проверке', str(int(df.check.ne('').sum())), 'Расхождения цвета, дат и статуса в справке')]
        result.notes.append(Note(NOTE))
        result.tables.append(Table('krs-table-7-1', 'Таблица 7.1 — информация о проведённых ремонтах', kr[[c.key for c in COLUMNS]], COLUMNS,
                                   note='Капитальный ремонт и исследования (КР, ИС).'))
        if not tr.empty:
            result.tables.append(Table('krs-table-tr', 'Текущий ремонт (ТР)', tr[[c.key for c in COLUMNS]], COLUMNS))
        return result

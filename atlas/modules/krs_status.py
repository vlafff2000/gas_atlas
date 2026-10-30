"""КРС: техническое состояние скважин, приоритет капремонта и динамика ГДИ.

Вход — таблицы проекта ``krs_works`` и ``krs_priority``: книгу ``КРС_для_Атласа.xlsx`` (модуль «Состояние скважин и приоритет КР»
программы «Работа с исходными данными») загружают один раз во вкладке «Импорт», выбирать файл здесь не нужно. Приоритет там — подсказка
(1 — срочно) по ревизиям КРУ с видимой причиной; ручное значение главнее расчёта. Здесь к нему добавлена динамика ГДИ:
ухудшение отдачи (расчёт ``gdi_trend``) — признак для ремонта. Приоритет по ГДИ не пересчитывается, показывается подсказка рядом:
решает инженер.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from atlas.engine.core.config import COLORS

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Stat, Table
from ..domain import DatasetKind
from atlas.engine.core.krs_import import PRIORITY_SOURCE
from .gdi import select, well_key
from .gdi_trend import VERDICTS, histories, rating

GDI = DatasetKind.GDI
WORKS_K, PRIORITY_K = DatasetKind.KRS_WORKS, DatasetKind.KRS_PRIORITY
SECTION = 'Выбор данных'
EMPTY_HINT = 'Данных КРС в проекте нет: импортируйте книгу КРС_для_Атласа.xlsx во вкладке «Импорт».'
TYPE_COLORS = {'Замена фильтра': '#d9822b', 'Колтюбинг без СКО': '#3a9ad9', 'Колтюбинг с СКО / СКО': '#e0c341',
               'Армирование ПЗП': '#2f4f9f', 'Тип не определён': '#999999'}
HINT_BOTH = 'Песок и ухудшение ГДИ: основание повысить приоритет'
HINT_GDI = 'Только ГДИ: отдача упала, проверьте исследования; возможен ремонт'
HINT_NONE = ''
NOTE = ('Приоритет КР (1 — срочно) — подсказка по ревизиям КРУ: первая ревизия с песком после ремонта даёт 3, каждая следующая на единицу ниже; '
        'промывка и СКО счёт не сбрасывают, замена фильтра и армирование сбрасывают. «Приоритет вручную» из книги главнее расчёта. '
        'Ухудшение ГДИ — признак для ремонта, сам приоритет оно не меняет: решение за инженером.')


def from_project(data: Data) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Таблицы проекта в привычных названиях столбцов книги: (приоритет, ремонты); нет обеих — None."""
    prio, works = data.get(PRIORITY_K), data.get(WORKS_K)
    if (prio is None or prio.empty) and (works is None or works.empty):
        return None
    if prio is None or prio.empty:
        prio = pd.DataFrame(columns=list(PRIORITY_SOURCE.values()))
    prio = prio.rename(columns={v: k for k, v in PRIORITY_SOURCE.items()})
    prio['Скважина'] = prio['Скважина'].astype(str)
    if works is None or works.empty:
        works = pd.DataFrame(columns=['well', 'year', 'work_type', 'detail'])
    works = works.rename(columns={'well': 'Скважина', 'year': 'Год', 'work_type': 'Тип ремонта', 'detail': 'Подробности'})
    works = works.dropna(subset=['Год']).assign(Год=lambda d: d['Год'].astype(int))
    return prio.reset_index(drop=True), works.reset_index(drop=True)


def gdi_flags(gdi: pd.DataFrame, threshold: float, change: float, last_n: int) -> pd.DataFrame:
    """По скважине: вывод ГДИ (ухудшение / улучшение / …) и изменение расхода при общем ΔP² — по расчёту «Динамики ГДИ»."""
    sel = select(gdi, [], [], last_n)
    hist = histories(sel, threshold, []) if not sel.empty else pd.DataFrame()
    if hist.empty:
        return pd.DataFrame(columns=['well', 'verdict', 'change', 'first', 'last'])
    table = rating(hist, change)
    # у скважины может быть несколько методов: берём самое сильное ухудшение (строки уже отсортированы по изменению)
    return table.drop_duplicates('well', keep='first')[['well', 'verdict', 'change', 'first', 'last']]


def combine(priority: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    out = priority.copy()
    out['well'] = out['Скважина'].astype(str)
    flags = flags.assign(well=flags.well.astype(str))
    out = out.merge(flags, on='well', how='left')
    down = out.verdict.eq(VERDICTS['down'])
    has_p = out['Приоритет итог'].notna()
    out['hint'] = np.where(down & has_p, HINT_BOTH, np.where(down, HINT_GDI, HINT_NONE))
    out['_k'] = out.well.map(well_key)
    out = out.sort_values(['Приоритет итог', 'change', '_k'], na_position='last', kind='stable').drop(columns='_k')
    return out.reset_index(drop=True)


def works_chart(works: pd.DataFrame) -> Chart | None:
    if works.empty:
        return None
    years = sorted(works['Год'].astype(int).unique())
    cats = [str(y) for y in years]
    chart = Chart('krs-works', 'Проведённые КР по годам и типам', Axis('Год', scale='category', categories=cats), Axis('КР', 'шт.', from_zero=True))
    for kind in [k for k in TYPE_COLORS if k in set(works['Тип ремонта'])]:
        counts = [int(((works['Год'] == y) & (works['Тип ремонта'] == kind)).sum()) for y in years]
        chart.series.append(Series(kind, cats, [float(c) for c in counts], 'bar', stack='works', color=TYPE_COLORS[kind],
                                   segments=[str(c) if c else '' for c in counts], labels=[f'{c} шт.' for c in counts]))
    return chart


class KrsStatusModule(Module):
    spec = ModuleSpec(
        id='krs_status',
        title='КРС: приоритет ремонта и динамика ГДИ',
        group='Авторский надзор',
        description='Проведённые КР, статистика, потребность в ремонте и приоритет скважин; ухудшение ГДИ как признак для ремонта.',
        needs=(),
        optional=(GDI, WORKS_K, PRIORITY_K),
        order=118,
        params=(
            Param('gdi_last', 'Последние даты ГДИ', 'choice', default=6, section=SECTION,
                  options=(Option(3, '3'), Option(6, '6'), Option(10, '10'), Option(0, 'Все')),
                  help='Сколько последних дат исследований брать по скважине для динамики ГДИ.'),
            Param('threshold', 'Порог R²', 'number', default=0.95, minimum=0.0, maximum=1.0, step=0.01, setting='r2_threshold', section=SECTION,
                  help='Исследования с R² ниже порога в динамику не попадают.'),
            Param('change', 'Порог ухудшения ГДИ', 'number', default=10.0, minimum=1, maximum=80, step=1, unit='%', section=SECTION,
                  help='Снижение расхода при общем ΔP² на столько процентов и больше — ухудшение (как в «Динамике коэффициентов ГДИ»).'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        book = from_project(data)
        if book is None:
            result.notes.append(Note(EMPTY_HINT))
            return result
        priority, works = book
        if GDI in data and not data[GDI].empty:
            flags = gdi_flags(data[GDI], params['threshold'], params['change'], int(params['gdi_last']))
        else:
            flags = pd.DataFrame(columns=['well', 'verdict', 'change', 'first', 'last'])
            result.notes.append(Note('Данных ГДИ в проекте нет: динамика ГДИ не показана, только приоритет по ревизиям КРУ.'))
        table = combine(priority, flags)
        worse = int(table.verdict.eq(VERDICTS['down']).sum())
        need = int(table['Приоритет итог'].notna().sum())
        result.summary = [
            Stat('Скважин в таблице', str(len(table))),
            Stat('Нуждаются в КР', str(need), 'Приоритет итог заполнен (расчёт или вручную)'),
            Stat('Приоритет 1', str(int(table['Приоритет итог'].eq(1).sum())), 'Самые срочные'),
            Stat('С ухудшением ГДИ', str(worse), f'Расход при общем ΔP² снизился на {params["change"]:g}% и более'),
            Stat('Проведено КР', str(len(works)))]
        result.notes.append(Note(NOTE))
        for chart in (works_chart(works),):
            if chart is not None:
                result.charts.append(chart)
        result.tables.append(Table('krs-priority', 'Скважины: приоритет КР и динамика ГДИ', table, [
            Column('Скважина', 'Скважина'), Column('ГСП', 'ГСП'),
            Column('Приоритет итог', 'Приоритет КР', kind='number', decimals=0),
            Column('Приоритет (расчёт)', 'Расчёт', kind='number', decimals=0),
            Column('Приоритет вручную', 'Вручную', kind='number', decimals=0),
            Column('Песок в ревизиях КРУ', 'Сезоны с песком'),
            Column('Последний КР', 'Последний КР', kind='number', decimals=0), Column('Тип последнего КР', 'Тип'),
            Column('В плане КР', 'В плане КР', kind='number', decimals=0),
            Column('verdict', 'Вывод ГДИ'), Column('change', 'Изменение Q', '%', 1, 'number'),
            Column('hint', 'Подсказка по ГДИ'), Column('Причина', 'Причина приоритета')],
            note='Приоритет — подсказка по ревизиям КРУ, ручное значение главнее. Подсказка по ГДИ приоритет не меняет.'))
        if not works.empty:
            by_year = works.pivot_table(index='Год', columns='Тип ремонта', values='Скважина', aggfunc='count', fill_value=0).reset_index()
            result.tables.append(Table('krs-by-year', 'Проведённые КР по годам и типам', by_year,
                                       [Column(str(c), str(c)) for c in by_year.columns]))
        result.tables.append(Table('krs-works', 'Все проведённые КР', works, [Column(str(c), str(c)) for c in works.columns], collapsed=True))
        return result

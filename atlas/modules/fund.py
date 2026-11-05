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
from ..contract import Axis, Chart, Series
from ._production import KINDS, PRODUCTION, periods_of, visible_periods, wells_of
from . import fund_ratio

GDI, RESPONSE, ELPRO = DatasetKind.GDI, DatasetKind.RESPONSE, DatasetKind.ELPRO
SECTION_RANK, SECTION_PROGRAM = 'Рейтинг динамики', 'Проверка выполнения программы ГДИ'
SECTION_RATIO = 'Сезон А к сезонам Б'

RANK_COLUMNS = [
    Column('Скважина', 'Скважина'), Column('Группа', 'Группа'),
    Column('Средний_тыс_м3_сут', 'Средний расход', 'тыс. м³/сут', 2, 'number'),
    Column('Объем_млн_м3', 'Объем', 'млн м³', 3, 'number'),
    Column('Активных_дней', 'Активных дней', decimals=0, kind='number'),
    Column('Записей', 'Записей', kind='number'), Column('Нулевых', 'Нулевых записей', kind='number')]

CRU_COLUMN = Column(fund_ratio.CRU_KEY, 'Среднее раскрытие КРУ', '%', 1, 'number')
CRU_NOTE = (' Среднее раскрытие КРУ — по суткам работы скважины (расход > 0), по данным ЭЛПРО; сутки без записи ЭЛПРО пропускаются, '
            'пустая ячейка — по скважине нет ЭЛПРО за эти сутки.')
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
        optional=(PRODUCTION, GDI, RESPONSE, ELPRO),
        order=51,
        params=(
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section=SECTION_RANK),
            Param('periods', 'Периоды', 'multi', default=[], dynamic=True, depends=('kind',), auto='all',
                  empty='ничего', section=SECTION_RANK),
            Param('by_season', 'Выгрузка по отдельным сезонам', 'boolean', default=False, section=SECTION_RANK,
                  help='Кроме сводного рейтинга по выбранным сезонам — своя таблица на каждый сезон. «Выгрузить все таблицы» кладёт их в один Excel: лист на сезон.'),
            Param('base', 'Сезон А', 'choice', default='', dynamic=True, depends=('kind',), section=SECTION_RATIO,
                  help='Сезон, который сравниваем. Пусто — анализ «А к Б» не строится.'),
            Param('against', 'Сезоны Б', 'multi', default=[], dynamic=True, depends=('kind',), empty='ничего', section=SECTION_RATIO,
                  help='Показатели сезона А делятся на среднее по этим сезонам.'),
            Param('ratio_well', 'Скважина для графика', 'choice', default='', dynamic=True, depends=('kind',), auto='first:1',
                  section=SECTION_RATIO),
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
        if name in ('base', 'against', 'ratio_well'):
            if PRODUCTION not in data or data[PRODUCTION].empty:
                return []
            d, kind = data[PRODUCTION], params.get('kind') or 'withdrawal'
            if name == 'ratio_well':
                return wells_of(d[d.kind.eq(kind)])
            return visible_periods(periods_of(d, kind), data.settings)
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        result.tables.append(self.composition(data))
        has = lambda kind: kind in data and not data[kind].empty
        if has(PRODUCTION):
            self.ranking(result, data, params)
            self.ratio(result, data, params)
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
        elpro = data[ELPRO] if ELPRO in data else None
        cols = RANK_COLUMNS + ([CRU_COLUMN] if elpro is not None and not elpro.empty else [])
        note = RANK_NOTE + (CRU_NOTE if len(cols) > len(RANK_COLUMNS) else '')
        stats = fund_ratio.with_cru(group_analysis.ranking(f, data.mapping), f, elpro)
        result.tables.append(Table('ranking', 'Рейтинг динамики', stats, cols, note=note))
        if params.get('by_season'):
            for i, period in enumerate(ps):
                one = f[f.period.eq(period)]
                if one.empty:
                    result.notes.append(Note(f'Сезон {period}: нет записей эксплуатации выбранного режима, лист не создан.'))
                    continue
                result.tables.append(Table(f'ranking-season-{i}', f'Рейтинг · {period}', fund_ratio.with_cru(group_analysis.ranking(one, data.mapping), one, elpro),
                                           cols, note=note))

    @staticmethod
    def ratio(result: Result, data: Data, params: dict[str, Any]) -> None:
        """Сезон А к сезонам Б: таблица по всем скважинам (в Excel — отдельный лист) и график выбранной скважины."""
        d, kind, base = data[PRODUCTION], params['kind'], params.get('base') or ''
        if not base:
            return
        known = periods_of(d, kind)
        against = [p for p in params.get('against') or [] if p in known and p != base]
        if base not in known:
            result.notes.append(Note(f'Сезон А «{base}» не найден среди сезонов выбранного режима.', 'warning'))
            return
        if not against:
            result.notes.append(Note('Выберите сезоны Б: без них нечего делить.'))
            return
        f = d[d.kind.eq(kind)]
        elpro = data[ELPRO] if ELPRO in data else None
        keys = fund_ratio.METRICS + ((fund_ratio.CRU_METRIC,) if elpro is not None and not elpro.empty else ())
        metrics = fund_ratio.season_metrics(f, data.mapping, [base, *against], elpro)
        table = fund_ratio.ratio_table(metrics, base, against, keys)
        cols = [Column('Скважина', 'Скважина'), Column('Группа', 'Группа')]
        cols += [Column(k, f'{label}: А / ср. Б', decimals=2, kind='number') for k, label, _ in keys]
        cols.append(Column('Примечание', 'Примечание'))
        result.tables.append(Table('ratio', f'А к Б · {base}', table, cols,
                                   note=f'А = {base}; Б = {", ".join(against)}. Значение А делится на среднее по сезонам Б, где у скважины есть записи. '
                                        'Пустая ячейка — нет данных или среднее Б равно 0; причина в «Примечание».'))
        well = params.get('ratio_well') or ''
        row = table[table['Скважина'].eq(well)]
        if row.empty:
            result.notes.append(Note('Выберите скважину для графика отношения А к Б.'))
            return
        labels = [label for _, label, _ in keys]
        values = [row.iloc[0][k] for k, _, _ in keys]
        chart = Chart('ratio-chart', f'Скважина {well}: {base} к среднему по Б', Axis('Показатель', scale='category', categories=labels),
                      Axis('Отношение А / ср. Б', from_zero=True))
        chart.series.append(Series(f'А / ср. Б', labels, [None if pd.isna(v) else float(v) for v in values], 'bar'))
        chart.series.append(Series('Равно Б', labels, [1.0] * len(labels), 'line', dashed=True, legend=True))
        result.charts.append(chart)
        if row.iloc[0]['Примечание']:
            result.notes.append(Note(f'Скважина {well}: {row.iloc[0]["Примечание"]}.'))

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

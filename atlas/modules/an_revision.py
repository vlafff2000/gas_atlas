"""Авторский надзор: табл. 1.8 — перечень скважин с выносом пластового песка по ГСП за сезоны отбора (ревизия КРУ).

Вход — два файла, выбранные общим проводником: историческая сводная (.xlsx, ГСП | количество | номера по сезонам)
и ревизия нового сезона (.docx с таблицами «№ скв.» или .xlsx). Расчёт — ``atlas.engine.modules.revision_report``
(перенос скрипта ``well_report.py`` без изменения правил). Здесь — только сборка таблиц и итогов для экрана.

Таблица 1.8 (в скрипте-источнике — 1.9): по ГСП и сезонам — количество (как в исходной таблице) и номера. Аналитика (показатели по ГСП, переходы
между сезонами, частота появления каждой скважины) считается по уникальным парам «ГСП + номер» за сезон.
Пустой ГСП в ревизии — «нет данных»; нулём он считается только по галочке «отсутствующий ГСП — нулевой перечень».
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from atlas.engine.modules import revision_report as rr
from atlas.engine.modules.charts import group_palette

from atlas.engine.core.config import ordered
from atlas.engine.core.loader import canonical_gsp

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Stat, Table, WellStrips
from ..domain import DatasetKind
from . import an_charts, an_wells
from ._production import periods_of
from .an_report import well_scopes

SECTION = 'Выбор данных'
CHARTS = (Option('count', 'Тепловая карта: число скважин по ГСП и сезонам'),
          Option('share', 'Тепловая карта: доля фонда ГСП (нужен «Отбор и закачка»)'),
          Option('freq', 'Частота повторов: сколько скважин встретилось в 1, 2, … сезонах'),
          Option('chronic', 'Хронические скважины по ГСП (в 3 сезонах и больше)'),
          Option('matrix', 'Матрица «скважина × сезон» (скважины в 2 сезонах и больше)'))
CHRONIC_FROM = 3        # хроническая скважина: перечень выноса песка в стольких сезонах и больше
MATRIX_FROM = 2
TITLE_19 = 'Перечень скважин с выносом пластового песка по сезонам отбора'


def season_frame(data: rr.Dataset) -> pd.DataFrame:
    """Таблица 1.8: строка — ГСП; для каждого сезона — колонка количества (c{i}) и колонка номеров (w{i})."""
    rows = []
    for g in data.gsps:
        row: dict[str, Any] = {'gsp': g}
        for i, s in enumerate(data.seasons):
            e = data.get(g, s)
            note = rr.merged_history_note(e)
            count, wells = rr.entry_display_values(e)
            row[f'c{i}'] = note or rr.text(count)
            row[f'w{i}'] = '' if note else rr.text(wells)
        rows.append(row)
    return pd.DataFrame(rows, columns=['gsp'] + [f'{k}{i}' for i in range(len(data.seasons)) for k in ('c', 'w')])


def heat_matrix(data: rr.Dataset) -> tuple[list[str], list[list[int | None]]]:
    """ГСП × сезоны: число уникальных скважин; None — по ГСП в сезоне нет данных (ревизии не было)."""
    rows = [[len(data.get(g, s).unique) if data.get(g, s).known else None for s in data.seasons] for g in data.gsps]
    return [str(g) for g in canonical_gsp(pd.Series(data.gsps, dtype=object))], rows


def well_presence(data: rr.Dataset) -> pd.DataFrame:
    """Скважины с песком: ГСП (единое написание), номер, по сезонам 1 / 0 / None (ревизии не было) и число сезонов с песком.

    Скважина — уникальная пара «ГСП + номер», как в аналитике ``rr.analyse``."""
    names = dict(zip(data.gsps, canonical_gsp(pd.Series(data.gsps, dtype=object))))
    rows = []
    for g in data.gsps:
        entries = [data.get(g, s) for s in data.seasons]
        for well in sorted({w for e in entries for w in e.unique}, key=rr.sort_key):
            cells = [None if not e.known else int(well in e.unique) for e in entries]
            rows.append({'group': str(names[g]), 'well': well, 'cells': cells, 'k': sum(c or 0 for c in cells)})
    return pd.DataFrame(rows, columns=['group', 'well', 'cells', 'k'])


def strips_chart(data: rr.Dataset, presence: pd.DataFrame, chart_id: str, title: str, layout: str, at_least: int) -> Any:
    part = presence[presence.k.ge(at_least)]
    part = part.assign(order=part.group.map({g: i for i, g in enumerate(dict.fromkeys(presence.group))}))
    part = part.sort_values(['order', 'k'], ascending=[True, False], kind='stable') if layout == 'panels' \
        else part.sort_values(['k', 'order'], ascending=[False, True], kind='stable')
    seasons = [s.replace('-', '/') for s in data.seasons]
    strips = WellStrips([f'№ {w}' for w in part.well], list(part.group), seasons, [list(c) for c in part.cells], [int(k) for k in part.k], layout,
                        colors=group_palette(presence.group))
    return an_charts.well_strips_chart(chart_id, title, strips)


def frequency_chart(data: rr.Dataset, presence: pd.DataFrame) -> Any:
    """Сколько скважин встретилось в 1, 2, … сезонах: столбики по числу сезонов, цвет — ГСП, число скважин внутри сегмента."""
    top = len(data.seasons)
    cats = [str(k) for k in range(1, top + 1)]
    chart = Chart('an-rev-frequency', 'Как часто скважины выносят песок: число скважин по числу сезонов с выносом',
                  Axis('В скольких сезонах скважина выносила песок', scale='category', categories=cats), Axis('Скважин', 'скв.', from_zero=True))
    for group in dict.fromkeys(presence.group):
        counts = [int(((presence.group == group) & (presence.k == k)).sum()) for k in range(1, top + 1)]
        if any(counts):
            chart.series.append(Series(str(group), cats, [float(c) for c in counts], 'bar', stack='freq',
                                       segments=[str(c) if c else '' for c in counts], labels=[f'{c} скв.' for c in counts]))
    return chart


def sand_charts(data: rr.Dataset, shown: list[str], production: pd.DataFrame | None, mapping: Any) -> tuple[list[Any], list[str]]:
    """Тепловые карты табл. 1.8: число скважин с песком и доля фонда ГСП. Второй результат — замечания для экрана."""
    names, counts = heat_matrix(data)
    seasons = [s.replace('-', '/') for s in data.seasons]
    charts, notes = [], []
    if 'count' in shown:
        charts.append(an_charts.heat_chart('an-rev-heat-count', 'Скважины с выносом песка по ГСП и сезонам', names, seasons, counts,
                                           [['' if v is None else str(v) for v in row] for row in counts], 'Скважин с выносом песка',
                                           missing_text='нет ревизии'))
    presence = well_presence(data) if {'freq', 'chronic', 'matrix'} & set(shown) else None
    if presence is not None and presence.empty:
        notes.append('Графики по скважинам не построены: в перечнях нет ни одного номера скважины.')
    elif presence is not None:
        if 'freq' in shown:
            charts.append(frequency_chart(data, presence))
        if 'chronic' in shown:
            charts.append(strips_chart(data, presence, 'an-rev-chronic', f'Хронические скважины: песок в {CHRONIC_FROM} сезонах и больше', 'panels', CHRONIC_FROM))
        if 'matrix' in shown:
            charts.append(strips_chart(data, presence, 'an-rev-matrix', f'Скважины с песком по сезонам ({MATRIX_FROM} сезона и больше)', 'matrix', MATRIX_FROM))
    if 'share' not in shown:
        return charts, notes
    if production is None or production.empty:
        return charts, ['Доля фонда не построена: загрузите «Отбор и закачка» (фонд ГСП берётся из последнего сезона отбора).']
    period = periods_of(production, 'withdrawal')[-1:] or periods_of(production, 'injection')[-1:]
    kind = 'withdrawal' if periods_of(production, 'withdrawal') else 'injection'
    wells = an_wells.season_wells(production, kind, period[0])
    fund = pd.Series(well_scopes(mapping, ordered(wells.well))).value_counts()
    labels = [f'{n} ({int(fund.get(n, 0))})' for n in names]
    share = [[None if v is None or not fund.get(n) else v / fund[n] * 100 for v in row] for n, row in zip(names, counts)]
    charts.append(an_charts.heat_chart('an-rev-heat-share', 'Доля фонда ГСП с выносом песка', labels, seasons, share,
                                       [['' if v is None and c is None else 'нет фонда' if v is None else f'{v:.0f} %' for v, c in zip(row, crow)]
                                        for row, crow in zip(share, counts)], '% от фонда ГСП',
                                       missing_text='нет ревизии'))
    notes.append(f'Доля фонда: фонд ГСП (в скобках) — скважины сезона {period[0]} из «Отбор и закачка», один и тот же для всех сезонов.')
    return charts, notes


def season_table(data: rr.Dataset) -> Table:
    columns = [Column('gsp', 'Номер ГСП')]
    for i, s in enumerate(data.seasons):
        columns += [Column(f'c{i}', 'Кол. скв., шт.'), Column(f'w{i}', '№ скважин')]
    header = [[('', 1)] + [(f'Отбор {s} гг.', 2) for s in data.seasons]]
    first, last = int(data.seasons[0][:4]), int(data.seasons[-1][:4]) + 1
    return Table('an-rev-1-8', f'{TITLE_19} в сезоны {first} – {last} гг.', season_frame(data), columns, header=header,
                 note='Исторические значения сохранены как в исходной таблице. Текстовые пометки («Ревизия не проводилась» и т. п.) '
                      'занимают обе графы сезона. Аналитика ниже — по уникальным номерам.')


def summary_table(analytics: dict[str, Any], seasons: list[str]) -> Table:
    rows = [{'gsp': r['gsp'], 'coverage': f'{r["coverage"]}/{len(seasons)}', 'unique': r['unique'], 'events': r['events'],
             'all': r['all'] if r['all'] is not None else 'н/д', 'once': r['once'],
             'repeated': rr.percent(r['repeated_share'])} for r in analytics['summary']]
    columns = [Column('gsp', 'ГСП'), Column('coverage', 'Сезонов с данными'), Column('unique', 'Уникальных', decimals=0, kind='number'),
               Column('events', 'Появлений', decimals=0, kind='number'), Column('all', 'Во всех сезонах'),
               Column('once', 'Один раз', decimals=0, kind='number'), Column('repeated', 'Доля повторных')]
    return Table('an-rev-summary', 'Показатели по ГСП', pd.DataFrame(rows, columns=[c.key for c in columns]), columns,
                 note='Доля повторных — скважины, встречавшиеся минимум в двух сезонах, среди уникальных скважин ГСП. '
                      'Появления — «скважина × сезон».')


def transitions_table(analytics: dict[str, Any]) -> Table:
    rows = [{'gsp': t['gsp'], 'period': f'{t["from"]} → {t["to"]}', 'retained': t.get('retained'), 'new': t.get('new'),
             'returned': t.get('returned'), 'absent': t.get('absent'), 'retention': rr.percent(t.get('retention')),
             'jaccard': rr.percent(t.get('jaccard'))}
            for t in analytics['transitions'] if t['available']]
    columns = [Column('gsp', 'ГСП'), Column('period', 'Переход'), Column('retained', 'Повторно', decimals=0, kind='number'),
               Column('new', 'Впервые в данных', decimals=0, kind='number'), Column('returned', 'Вернулись', decimals=0, kind='number'),
               Column('absent', 'Нет в текущем', decimals=0, kind='number'), Column('retention', 'Повторяемость'),
               Column('jaccard', 'Сходство Жаккара')]
    return Table('an-rev-transitions', 'Повторяемость от сезона к сезону', pd.DataFrame(rows, columns=[c.key for c in columns]), columns,
                 note='«Впервые» относится к загруженной истории. Доли не рассчитываются при нулевом знаменателе, пропусках данных '
                      'или несмежных календарных сезонах.', collapsed=True)


def frequency_table(analytics: dict[str, Any], seasons: list[str]) -> Table:
    rows = [{'gsp': w['gsp'], 'well': w['well'], 'k': w['k'], 'n': w['n'], 'share': rr.percent(w['share']),
             'first': w['first'], 'last': w['last'], 'streak': w['streak']} for w in analytics['wells']]
    columns = [Column('gsp', 'ГСП'), Column('well', 'Скважина'), Column('k', 'Появления', decimals=0, kind='number'),
               Column('n', 'Сезонов с данными', decimals=0, kind='number'), Column('share', 'Частота'),
               Column('first', 'Первый сезон'), Column('last', 'Последний сезон'),
               Column('streak', 'Макс. серия', decimals=0, kind='number')]
    return Table('an-rev-frequency', 'Частота появления каждой скважины', pd.DataFrame(rows, columns=[c.key for c in columns]),
                 columns, note=f'Частота — число появлений / число сезонов с данными по ГСП; серия — подряд идущие сезоны ({seasons[0]} — {seasons[-1]}).',
                 collapsed=True)


class RevisionModule(Module):
    spec = ModuleSpec(
        id='an_revision',
        title='Авторский надзор: вынос песка по ревизии КРУ',
        group='Авторский надзор',
        description='Перечень скважин с выносом песка по ГСП за сезоны: историческая сводная и ревизия нового сезона, повторяемость, частота.',
        needs=(),
        optional=(DatasetKind.PRODUCTION,),
        order=115,
        save_label='Сохранить вид',
        params=(
            Param('history', 'История: сводная .xlsx', 'file', default='', extensions='xlsx', section=SECTION,
                  help='Книга с ГСП в строках и парами «количество | номера» по сезонам.'),
            Param('revision', 'Ревизия нового сезона', 'file', default='', extensions='docx xlsx', section=SECTION,
                  help='Word с таблицами по ГСП и столбцом «№ скв.» или Excel той же структуры.'),
            Param('season', 'Новый сезон', 'text', default='', section=SECTION, help='Например 2025/26 или 2025-2026.'),
            Param('filter', 'Фильтр строк ревизии', 'text', default='', section=SECTION,
                  help='Регулярное выражение по тексту строки ревизии; пусто — все строки с номерами.'),
            Param('charts', 'Графики', 'multi', default=['chronic'], section='Вид', empty='ничего', options=CHARTS,
                  help='Тепловые карты по таблице 1.8: число скважин с песком и доля от фонда ГСП. Таблицы остаются как есть.'),
            Param('absent_zero', 'Отсутствующий в ревизии ГСП — нулевой перечень', 'boolean', default=False, section=SECTION,
                  help='Без галочки такой ГСП помечается «нет данных».'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        if not params['history'] or not params['revision']:
            result.notes.append(Note('Выберите историческую сводную и ревизию нового сезона.'))
            return result
        if not params['season']:
            result.notes.append(Note('Укажите новый сезон, например 2025/26.'))
            return result
        try:
            history = rr.parse_history(params['history'])
            revision, issues, source, hints = rr.parse_revision(params['revision'], None, None, params['filter'])
            season = rr.normalize_season(params['season'])
            if hints and season not in hints:
                issues.append(f'Введён сезон {season}; заголовок ревизии содержит {", ".join(hints)}. Использован введённый сезон.')
            dataset = rr.append_season(history, season, revision, issues, source, params['absent_zero'])
        except rr.InputError as exc:
            result.notes.append(Note(str(exc), 'warning'))
            return result
        except re.error as exc:
            result.notes.append(Note(f'Фильтр строк: не разобран шаблон ({exc}).', 'warning'))
            return result
        analytics = rr.analyse(dataset)
        latest = analytics['totals'][-1]
        result.charts, chart_notes = sand_charts(dataset, params.get('charts') or [], data[DatasetKind.PRODUCTION] if DatasetKind.PRODUCTION in data else None,
                                                 data.mapping)
        result.notes += [Note(text) for text in chart_notes]
        result.tables.append(season_table(dataset))
        result.tables.append(summary_table(analytics, dataset.seasons))
        result.tables.append(transitions_table(analytics))
        result.tables.append(frequency_table(analytics, dataset.seasons))
        if dataset.issues:
            result.tables.append(Table('an-rev-issues', 'Замечания к данным', pd.DataFrame({'text': dataset.issues}),
                                       [Column('text', 'Замечание')], collapsed=True))
        result.summary = [
            Stat('Сезонов в истории', str(len(dataset.seasons))),
            Stat('ГСП', str(len(dataset.gsps))),
            Stat(f'Пар ГСП + скважина · {latest["season"]}',
                 str(latest['count']) if latest['complete'] else f'{latest["count"]} (данные по {latest["known"]} из {len(dataset.gsps)} ГСП)',
                 'Уникальные пары за последний сезон; если по части ГСП в ревизии нет данных, число неполное'),
            Stat('Замечаний', str(len(dataset.issues)), 'Повторы, пометки и расхождения — см. таблицу замечаний'),
        ]
        about = [*rr.methodology(dataset), *dataset.sources]
        result.tables.append(Table('an-rev-method', 'Как считается и откуда данные', pd.DataFrame({'text': about}),
                                   [Column('text', 'Пояснение')], collapsed=True))
        return result

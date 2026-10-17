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

from ..contract import Column, Data, Module, ModuleSpec, Note, Param, Result, Stat, Table

SECTION = 'Выбор данных'
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

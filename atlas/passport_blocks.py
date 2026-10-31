"""Графики и таблицы дашборда «Паспорта скважины» в общем контракте (``atlas.contract``).

Экран рисует их тем же ``ChartView`` и ``TableView``, что и остальные модули, а выгрузка PNG/XLSX идёт тем же кодом ``render``.
Здесь только выбор данных из карточки (``passport_card.build``) и представление; расчётов нет.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .contract import Axis, Chart, CellStyle, Column, Series, Table

KIND_LABEL = {'withdrawal': 'Отбор', 'injection': 'Закачка'}


def _f(values: list[Any]) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], float)


def seasons_chart(seasons: list[dict[str, Any]]) -> Chart | None:
    """Объём по сезонам: столбцы отбора и закачки, слева направо по времени."""
    rows = [r for r in reversed(seasons) if r['volume'] is not None]      # таблица идёт от свежего сезона
    if not rows:
        return None
    cats = list(dict.fromkeys(r['period'] for r in rows))
    chart = Chart('passport-seasons', 'Объём по сезонам', Axis('Сезон', scale='category', categories=cats),
                  Axis('Объём', 'млн м³', from_zero=True))
    for kind, label in KIND_LABEL.items():
        part = [r for r in rows if r['kind'] == kind]
        if part:
            chart.series.append(Series(label, [r['period'] for r in part], _f([r['volume'] for r in part]), 'bar', group=label,
                                       labels=[f"{label}, {r['period']} · Qmax {r['max_rate']:.1f} тыс. м³/сут" if r['max_rate'] is not None
                                               else f"{label}, {r['period']}" for r in part]))
    return chart


def daily_chart(daily: dict[str, dict[str, list]]) -> Chart | None:
    """Суточные расходы за все сезоны: отбор и закачка линиями по времени; в подсказке часы работы."""
    chart = Chart('passport-daily', 'Суточные расходы', Axis('Дата', scale='time'), Axis('Суточный объём', 'тыс. м³/сут', from_zero=True),
                  crosshair=True)
    for kind, label in KIND_LABEL.items():
        s = daily.get(kind) or {}
        if not s.get('date'):
            continue
        hours = [f'Часы работы: {h:g}' if h is not None else 'Часы работы: нет данных' for h in s['hours']]
        chart.series.append(Series(label, pd.to_datetime(s['date']).to_numpy(), _f(s['volume']), 'line', group=label, labels=hours,
                                   width=1.4))
    return chart if chart.series else None


def gdi_chart(items: list[dict[str, Any]]) -> Chart | None:
    """Индикаторные диаграммы: точки режимов (q, Δp²) и кривая Δp² = a·q + b·q² каждого исследования; ненадёжные — пунктиром."""
    if not items:
        return None
    chart = Chart('passport-gdi', 'Индикаторные диаграммы ГДИ', Axis('Дебит q', 'тыс. м³/сут', from_zero=True),
                  Axis('Δp² = p_пл² − p_заб²', '(кгс/см²)²', from_zero=True))
    for g in items:
        name = g['date'] + (' · ' + g['method'] if g['method'] else '') + ('' if g['reliable'] else ' (ненадёжное)')
        qs = [p[0] for p in g['points']]
        chart.series.append(Series(name, qs, [p[1] for p in g['points']], 'points', group=name,
                                   tooltip='' if g['reliable'] else 'Ненадёжное исследование: решает инженер'))
        if g['a'] is not None and g['b'] is not None:
            top = max(qs) * 1.05
            curve = np.linspace(0, top, 41)
            chart.series.append(Series(name + ' (аппроксимация)', curve, g['a'] * curve + g['b'] * curve ** 2, 'line', group=name,
                                       dashed=not g['reliable'], legend=False))
    return chart


def seasons_table(seasons: list[dict[str, Any]]) -> Table | None:
    if not seasons:
        return None
    frame = pd.DataFrame({
        'kind': [KIND_LABEL[r['kind']] for r in seasons], 'period': [r['period'] for r in seasons],
        'volume': _f([r['volume'] for r in seasons]), 'days': [r['days'] for r in seasons],
        'max_rate': _f([r['max_rate'] for r in seasons]), 'max_date': [r['max_date'] for r in seasons],
        'mean_rate': _f([r['mean_rate'] for r in seasons]), 'hours': _f([r['hours'] for r in seasons]),
        'water': _f([r['water'] for r in seasons])})
    return Table('passport-seasons', 'Сезоны эксплуатации', frame, [
        Column('kind', 'Вид'), Column('period', 'Сезон'), Column('volume', 'Объём', 'млн м³', 2, 'number'),
        Column('days', 'Отработано дней', '', 0, 'number'), Column('max_rate', 'Qmax', 'тыс. м³/сут', 1, 'number'),
        Column('max_date', 'Дата Qmax'), Column('mean_rate', 'Qср', 'тыс. м³/сут', 1, 'number'),
        Column('hours', 'Часы', '', 0, 'number'), Column('water', 'Вода', 'м³', 1, 'number')],
        note='Сверху самый свежий сезон, затем предыдущий другого вида (отбор / закачка) и так далее.')


def gdi_table(rows: list[dict[str, Any]]) -> Table | None:
    if not rows:
        return None
    frame = pd.DataFrame({
        'date': [r['date'] for r in rows], 'method': [r['method'] or '—' for r in rows],
        'a': _f([r['a'] for r in rows]), 'b': _f([r['b'] for r in rows]), 'r2': _f([r['r2'] for r in rows]),
        'q_max': _f([r['q_max'] for r in rows]), 'q_free': _f([r['q_free'] for r in rows]),
        'reliable': ['да' if r['reliable'] else 'нет' for r in rows]})
    bad = [i for i, r in enumerate(rows) if not r['reliable']]
    return Table('passport-gdi', 'ГДИ за всё время', frame, [
        Column('date', 'Дата'), Column('method', 'Метод'), Column('a', 'a', '', 3, 'number'), Column('b', 'b', '', 4, 'number'),
        Column('r2', 'R²', '', 3, 'number'), Column('q_max', 'Qmax', '', 0, 'number'), Column('q_free', 'Qсв', '', 0, 'number'),
        Column('reliable', 'Надёжно')], styles=[CellStyle(bad, font='808080')] if bad else [],
        note='Ненадёжные исследования выделены серым, но не скрыты: решает инженер.')


def krs_table(krs: dict[str, Any]) -> Table | None:
    if not krs['works']:
        return None
    frame = pd.DataFrame({'year': [w['year'] if w['year'] is not None else np.nan for w in krs['works']],
                          'type': [w['type'] for w in krs['works']], 'detail': [w['detail'] for w in krs['works']]})
    return Table('passport-krs', 'Проведённые КРС', frame, [
        Column('year', 'Год', '', 0, 'number'), Column('type', 'Тип ремонта'), Column('detail', 'Подробности')])


def blocks(card: dict[str, Any]) -> tuple[list[Chart], list[Table]]:
    charts = [c for c in (seasons_chart(card['seasons']), daily_chart(card['daily']), gdi_chart(card['gdi_diagrams'])) if c]
    tables = [t for t in (seasons_table(card['seasons']), gdi_table(card['gdi']), krs_table(card['krs'])) if t]
    return charts, tables

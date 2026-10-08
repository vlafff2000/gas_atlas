"""Динамика коэффициентов ГДИ по годам и рейтинг скважин с ухудшением отдачи.

Новый раздел (в 5.8 есть только сравнение двух исследований и «Динамика трёх последних»). Математика 5.8 не
переписана: коэффициенты a, b, R² и признак надёжности — ``atlas.engine.modules.well_analysis.gdi_history``, расход при общем
ΔP² — оттуда же (по методу, без экстраполяции). Здесь только выбор данных, сравнение первого и последнего
надёжного исследования и представление.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from atlas.engine.core.config import COLORS
from atlas.engine.modules import well_analysis as legacy

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Source, Stat, Table
from ..domain import UNITS, DatasetKind
from .gdi import select, well_key

GDI = DatasetKind.GDI
NOTE = ('Сравниваются первое и последнее надёжное исследование скважины одним методом (R² не ниже порога, не менее трёх '
        'разных расходов, коэффициенты неотрицательны). Расход считается при одном ΔP² — общем для надёжных исследований '
        'метода, без экстраполяции. Причины изменения по этим данным не устанавливаются: сначала проверьте исследования.')
VERDICTS = {'down': 'Ухудшение', 'up': 'Улучшение', 'same': 'Без изменений', 'few': 'Недостаточно надёжных исследований'}


def histories(gdi: pd.DataFrame, threshold: float, methods: list[str]) -> pd.DataFrame:
    """Исследования всех выбранных скважин: a, b, R², надёжность, расход при общем ΔP² (``gdi_history`` 5.8 по скважине)."""
    parts = []
    for well, group in gdi.groupby(gdi.well.astype(str), sort=False):
        if methods and 'method' in group:
            group = group[group.method.astype(str).isin(methods)]
        if group.empty:
            continue
        h = legacy.gdi_history(group, threshold)
        if not h.empty:
            h['well'] = well
            parts.append(h)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def rating(history: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Рейтинг: по скважине и методу — изменение расхода при общем ΔP² между первым и последним надёжным исследованием."""
    rows = []
    for (well, method), g in history.groupby(['well', history.method.fillna('')], sort=False):
        ok = g[g.reliable & g.q_reference.notna()].sort_values('date')
        ok = ok.drop_duplicates('date', keep='last')
        row = {'well': well, 'method': method or '—', 'studies': len(g), 'reliable': len(ok)}
        if len(ok) < 2:
            rows.append({**row, 'verdict': VERDICTS['few']})
            continue
        first, last = ok.iloc[0], ok.iloc[-1]
        change = (last.q_reference - first.q_reference) / first.q_reference * 100 if first.q_reference else np.nan
        verdict = (VERDICTS['down'] if change <= -threshold else VERDICTS['up'] if change >= threshold else VERDICTS['same']) \
            if np.isfinite(change) else VERDICTS['few']
        rows.append({**row, 'first': first.date, 'last': last.date, 'q_first': first.q_reference, 'q_last': last.q_reference,
                     'change': change, 'a_change': _pct(first.a, last.a), 'b_change': _pct(first.b, last.b),
                     'dp2': last.reference_dp2, 'verdict': verdict})
    out = pd.DataFrame(rows)
    for col in ('first', 'last', 'q_first', 'q_last', 'change', 'a_change', 'b_change', 'dp2'):
        if col not in out:
            out[col] = np.nan
    out['_k'] = out.well.map(well_key)
    out = out.sort_values(['change', '_k'], na_position='last', kind='stable').drop(columns='_k').reset_index(drop=True)
    out.insert(0, 'rank', [i + 1 if pd.notna(c) else np.nan for i, c in enumerate(out.change)])
    return out


def _pct(old, new) -> float:
    return (new - old) / old * 100 if old else np.nan


class GdiTrendModule(Module):
    spec = ModuleSpec(
        id='gdi_trend',
        title='Динамика коэффициентов ГДИ',
        group='Исследования скважин',
        description='Как менялись коэффициенты a и b и расход при одном ΔP² по годам; рейтинг скважин с ухудшением отдачи.',
        needs=(GDI,),
        order=35,
        params=(
            Param('wells', 'Скважины', 'multi', default=[], source=Source(GDI, 'well'), section='Выбор данных'),
            Param('last_n', 'Последние даты исследований', 'choice', default=6, section='Выбор данных',
                  options=(Option(3, '3'), Option(6, '6'), Option(10, '10'), Option(0, 'Все')),
                  help='Сколько последних дат исследований брать по каждой скважине. «Все» на большом объекте считается долго '
                       '(подбор коэффициентов по каждому исследованию).'),
            Param('methods', 'Метод ГДИ', 'multi', default=[], source=Source(GDI, 'method'), section='Выбор данных',
                  help='Пусто — все методы. Исследования разных методов не сравниваются между собой.'),
            Param('threshold', 'Порог R²', 'number', default=0.95, minimum=0.0, maximum=1.0, step=0.01,
                  setting='r2_threshold', section='Выбор данных',
                  help='Общая настройка проекта. Исследования с R² ниже порога в рейтинг не попадают.'),
            Param('change', 'Порог изменения', 'number', default=10.0, minimum=1, maximum=80, step=1, unit='%', section='Выбор данных',
                  help='Изменение расхода при общем ΔP² меньше порога считается «без изменений».',
                  formula='изменение = (Q последнего исследования − Q первого) / Q первого × 100%',
                  example='Q при ΔP² = 500 было 180, стало 153: −15% — при пороге 10% это ухудшение.'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        gdi = data[GDI]
        gdi = select(gdi, params['wells'], [], int(params['last_n']))
        history = histories(gdi, params['threshold'], params['methods']) if not gdi.empty else pd.DataFrame()
        if history.empty:
            return Result(notes=[Note('Под выбранные условия не попало ни одного исследования. Выберите скважины с данными ГДИ.',
                                      'warning')])
        table = rating(history, params['change'])
        worse = int(table.verdict.eq(VERDICTS['down']).sum())
        result = Result(summary=[
            Stat('Скважин', str(history.well.nunique())), Stat('Исследований', str(len(history))),
            Stat('Надёжных', str(int(history.reliable.sum())), 'R² не ниже порога, три разных расхода, a и b не отрицательны'),
            Stat('С ухудшением', str(worse), f'Расход при общем ΔP² снизился на {params["change"]:g}% и более')])
        result.notes.append(Note(NOTE))
        result.tables.append(Table('rating', 'Рейтинг скважин по изменению отдачи', table, [
            Column('rank', 'Место', kind='number', decimals=0), Column('well', 'Скважина'), Column('method', 'Метод'),
            Column('first', 'Первое исследование', kind='date'), Column('last', 'Последнее исследование', kind='date'),
            Column('reliable', 'Надёжных исследований', kind='number', decimals=0),
            Column('dp2', 'Общий ΔP²', UNITS['dp2'], 0, 'number'),
            Column('q_first', 'Q было', UNITS['q_gdi'], 1, 'number'), Column('q_last', 'Q стало', UNITS['q_gdi'], 1, 'number'),
            Column('change', 'Изменение Q', '%', 1, 'number'), Column('a_change', 'Изменение a', '%', 1, 'number'),
            Column('b_change', 'Изменение b', '%', 1, 'number'), Column('verdict', 'Вывод')],
            note='Выше в списке — сильнее снизилась отдача. a и b — коэффициенты ΔP² = aQ + bQ² (рост a и b при том же ΔP² даёт меньший расход).'))
        for tid, title, field, label, unit in (
                ('q', 'Расход при общем ΔP²', 'q_reference', 'Q', UNITS['q_gdi']),
                ('a', 'Коэффициент a', 'a', 'a', ''), ('b', 'Коэффициент b', 'b', 'b', '')):
            chart = Chart(f'trend-{tid}', title, Axis('Дата исследования', scale='time'), Axis(label, unit))
            for i, (well, g) in enumerate(sorted(history.groupby('well'), key=lambda kv: well_key(kv[0]))):
                g = g[g.reliable & g[field].notna()].sort_values('date')
                if g.empty:
                    continue
                chart.series.append(Series(f'№ {well}', g.date.to_numpy(), g[field].to_numpy(float), 'line',
                                           group=f'№ {well}', color=COLORS[i % len(COLORS)], markers=True, width=2.0,
                                           labels=[f'№ {well} · {m or "метод не указан"}' for m in g.method.fillna('')]))
            if chart.series:
                result.charts.append(chart)
        studies = history[['well', 'date', 'method', 'study', 'a', 'b', 'r2', 'source', 'reliable', 'reference_dp2',
                           'q_reference']].assign(reliable=lambda d: d.reliable.map({True: 'да', False: 'нет'}))
        result.tables.append(Table('studies', 'Все исследования', studies, [
            Column('well', 'Скважина'), Column('date', 'Дата', kind='date'), Column('method', 'Метод'),
            Column('study', 'Исследование'), Column('a', 'a', decimals=5, kind='number'), Column('b', 'b', decimals=5, kind='number'),
            Column('r2', 'R²', decimals=4, kind='number'), Column('source', 'Источник коэффициентов'),
            Column('reliable', 'Надёжное'), Column('reference_dp2', 'Общий ΔP²', UNITS['dp2'], 0, 'number'),
            Column('q_reference', 'Q при общем ΔP²', UNITS['q_gdi'], 1, 'number')], collapsed=True))
        return result

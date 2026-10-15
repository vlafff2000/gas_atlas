"""Сравнение базы ЭЛПРО с классической базой расходов: накопленные объёмы по объекту, группам и скважинам.

Сравниваются только сутки, в которых есть значение в обеих базах: пропуск не считается нулём, простой (ноль) — считается.
Разница — ЭЛПРО минус БД расходов; в процентах — от БД расходов. «Флаг» — разница больше порога.
Объёмы — тыс. м³ за период. Группы — единая схема имён (проектные группы, иначе группа из ЭЛПРО).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from atlas.engine.core.loader import canonical_gsp

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Param, Result, Series, Stat, Table
from ..domain import DatasetKind
from ._production import KINDS, group_of

PRODUCTION, ELPRO = DatasetKind.PRODUCTION, DatasetKind.ELPRO
UNIT = 'тыс. м³'
SECTION = 'Выбор данных'
CLASSIC_COLOR, ELPRO_COLOR = '#1f4e8c', '#ff5a1f'
NOTE = ('Сравниваются сутки, в которых есть значение в обеих базах; пропуск не считается нулём. '
        'Разница — ЭЛПРО минус БД расходов, в процентах — от БД расходов. Флаг — разница больше порога.')


def _num(v: float) -> str:
    return f'{v:,.0f}'.replace(',', ' ')


def classic_daily(prod: pd.DataFrame, mapping, kind: str) -> pd.DataFrame:
    """БД расходов по скважинам и суткам: well, date, group, classic (тыс. м³). Q хранится в м³/сут."""
    d = prod[prod['kind'].eq(kind)]
    d = pd.DataFrame({'well': d['well'].astype(str), 'date': pd.to_datetime(d['date']).dt.normalize(),
                      'classic': d['q'] / 1000})
    d['group'] = d['well'].map(lambda w: group_of(mapping, w))
    return d.groupby(['well', 'date'], sort=False).agg(classic=('classic', lambda v: v.sum(min_count=1)),
                                                        group=('group', 'first')).reset_index()


def elpro_daily(elpro: pd.DataFrame, kind: str) -> pd.DataFrame:
    """ЭЛПРО по скважинам и суткам: well, date, elpro_group, elpro (тыс. м³). Q уже в тыс. м³/сут."""
    d = elpro[elpro['kind'].eq(kind)]
    d = pd.DataFrame({'well': d['well'].astype(str), 'date': pd.to_datetime(d['date']).dt.normalize(),
                      'elpro': d['q'], 'elpro_group': d['group'].astype(str)})
    return d.groupby(['well', 'date'], sort=False).agg(elpro=('elpro', lambda v: v.sum(min_count=1)),
                                                        elpro_group=('elpro_group', 'first')).reset_index()


def paired(prod: pd.DataFrame, elpro: pd.DataFrame, mapping, kind: str, date_from, date_to) -> tuple[pd.DataFrame, dict]:
    """Сутки, где есть значения в обеих базах: well, date, group, classic, elpro. Второе — счётчики непарных суток."""
    c = classic_daily(prod, mapping, kind)
    e = elpro_daily(elpro, kind)
    if date_from is not None:
        c, e = c[c.date >= date_from], e[e.date >= date_from]
    if date_to is not None:
        c, e = c[c.date <= date_to], e[e.date <= date_to]
    both = c.merge(e, on=['well', 'date'], how='outer')
    counts = {'classic_only': int((both.elpro.isna() & both.classic.notna()).sum()),
              'elpro_only': int((both.classic.isna() & both.elpro.notna()).sum())}
    both = both.dropna(subset=['classic', 'elpro'])
    both['group'] = both['group'].where(both['group'].ne('Без группы') & both['group'].notna(), both['elpro_group'])
    both['group'] = canonical_gsp(both['group'].fillna('Без группы').astype(str)).astype(str)
    return both.drop(columns=['elpro_group']).reset_index(drop=True), counts


def summed(d: pd.DataFrame, by: str | None, threshold: float) -> pd.DataFrame:
    """Итоги по ключу ``by`` (None — весь объект): key, group, дней, два объёма, разница, %, флаг."""
    key = d[by].astype(str) if by else pd.Series('Объект', index=d.index)
    s = d.assign(key=key).groupby('key', sort=False).agg(
        group=('group', 'first'), days=('date', 'size'), classic=('classic', 'sum'), elpro=('elpro', 'sum')).reset_index()
    s['delta'] = s.elpro - s.classic
    s['percent'] = np.where(s.classic > 0, s.delta / s.classic.where(s.classic > 0) * 100, np.nan)
    s['flag'] = np.where(s.percent.notna() & (s.percent.abs() > threshold), 'больше порога',
                         np.where(s.percent.isna() & s.elpro.gt(0), 'нет в БД расходов', ''))
    return s


class ElproCompareModule(Module):
    spec = ModuleSpec(
        id='elpro_compare',
        title='Сравнение БД ЭЛПРО и БД расходов',
        group='Эксплуатация',
        description='Накопленные объёмы по объекту, группам и скважинам: база ЭЛПРО против классической базы расходов.',
        needs=(PRODUCTION, ELPRO),
        order=30,
        save_label='Сохранить вид',
        params=(
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section=SECTION),
            Param('date_from', 'Период с', 'date', default=None, section=SECTION),
            Param('date_to', 'по', 'date', default=None, section=SECTION,
                  help='Пусто — до последних суток в обеих базах.'),
            Param('threshold', 'Порог расхождения', 'number', default=10.0, minimum=0, unit='%', section=SECTION,
                  help='Строки с разницей больше порога помечаются флагом.'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        kind = params['kind']
        threshold = float(params['threshold'])
        date_from = pd.Timestamp(params['date_from']) if params.get('date_from') else None
        date_to = pd.Timestamp(params['date_to']) if params.get('date_to') else None
        if not (data[ELPRO]['kind'].eq(kind)).any():
            result.notes.append(Note('В базе ЭЛПРО нет данных по выбранному режиму. Загрузите файлы ЭЛПРО через «Источники» '
                                     '(роль «ЭЛПРО»).', 'warning'))
            return result
        pairs, counts = paired(data[PRODUCTION], data[ELPRO], data.mapping, kind, date_from, date_to)
        if pairs.empty:
            result.notes.append(Note('За выбранный период нет суток, в которых есть данные и в БД расходов, и в ЭЛПРО. '
                                     'Измените период.', 'warning'))
            return result
        result.notes.append(Note(NOTE))
        total = summed(pairs, None, threshold)
        by_group = summed(pairs, 'group', threshold).sort_values('key')
        by_well = summed(pairs, 'well', threshold)
        by_well = by_well.sort_values('key', key=lambda v: v.astype(int) if v.str.isdigit().all() else v)
        row = total.iloc[0]
        result.summary += [Stat('БД расходов', f'{_num(row.classic)} {UNIT}'),
                           Stat('ЭЛПРО', f'{_num(row.elpro)} {UNIT}'),
                           Stat('Разница', f'{row.percent:+.1f} %' if pd.notna(row.percent) else '—')]
        result.charts.append(self.cumulative_chart(pairs, kind))
        result.tables.append(self.table('elpro-object', 'По объекту', total, 'Объект', with_group=False))
        result.tables.append(self.table('elpro-groups', 'По группам', by_group, 'Группа', with_group=False))
        result.tables.append(self.table('elpro-wells', 'По скважинам', by_well, 'Скважина', with_group=True))
        flagged = int(by_well.flag.eq('больше порога').sum())
        if flagged:
            result.notes.append(Note(f'Скважин с разницей больше {threshold:g} %: {flagged}. Смотрите флаг в таблице «По скважинам».',
                                     'warning'))
        if counts['classic_only'] or counts['elpro_only']:
            result.notes.append(Note(f'Суток без пары: только в БД расходов — {counts["classic_only"]}, только в ЭЛПРО — '
                                     f'{counts["elpro_only"]}. В сравнение не вошли.'))
        return result

    @staticmethod
    def cumulative_chart(pairs: pd.DataFrame, kind: str) -> Chart:
        daily = pairs.groupby('date')[['classic', 'elpro']].sum().sort_index()
        cum = daily.cumsum()
        what = 'закачки' if kind == 'injection' else 'отбора'
        chart = Chart('elpro-cumulative', f'Накопленный {what} по объекту: БД расходов и ЭЛПРО', Axis('Дата', scale='time'),
                      Axis(f'Накопленный объём, {UNIT}', from_zero=True), crosshair=True)
        chart.series.append(Series('БД расходов', cum.index.to_numpy(), cum.classic.to_numpy(), 'line', color=CLASSIC_COLOR))
        chart.series.append(Series('ЭЛПРО', cum.index.to_numpy(), cum.elpro.to_numpy(), 'line', color=ELPRO_COLOR))
        return chart

    @staticmethod
    def table(tid: str, title: str, s: pd.DataFrame, label: str, with_group: bool) -> Table:
        frame = pd.DataFrame({label: s['key'].to_numpy()})
        columns = [Column(label, label)]
        if with_group:
            frame['Группа'] = s['group'].to_numpy()
            columns.append(Column('Группа', 'Группа'))
        frame['Дней в обеих базах'] = s['days'].to_numpy()
        frame['БД расходов'] = s['classic'].to_numpy()
        frame['ЭЛПРО'] = s['elpro'].to_numpy()
        frame['Разница'] = s['delta'].to_numpy()
        frame['Разница, %'] = s['percent'].to_numpy()
        frame['Флаг'] = s['flag'].to_numpy()
        columns += [Column('Дней в обеих базах', 'Дней в обеих базах', '', 0, 'number'),
                    Column('БД расходов', 'БД расходов', UNIT, 0, 'number'),
                    Column('ЭЛПРО', 'ЭЛПРО', UNIT, 0, 'number'),
                    Column('Разница', 'Разница', UNIT, 0, 'number'),
                    Column('Разница, %', 'Разница, %', '%', 1, 'number'),
                    Column('Флаг', 'Флаг')]
        return Table(tid, title, frame, columns, note='Разница = ЭЛПРО − БД расходов. Флаг «больше порога» — |разница, %| выше порога.')

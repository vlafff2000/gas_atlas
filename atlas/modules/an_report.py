"""Авторский надзор: общий расчёт сезона, на котором строятся главы отчёта АН (Касимовское ПХГ, 2025).

Здесь — только общая часть: по каждому выбранному сезону даты начала и остановки по суткам с расходом, длительность
в календарных сутках (високосный год учитывается календарём), число скважин, работавших хотя бы сутки, средние суточные
расходы по объекту и группам за сезон и по месяцам, пик суточного расхода объекта, давление объекта на ближайшую дату.

Группы — единая схема имён: регистр, пробелы, «_» и «-» не различают группы, «ГСП-1» = «ГСП 1»
(``loader.unify_groups`` и ``canonical_gsp`` из импорта). Давления — абсолютные, кгс/см²: Атлас их не пересчитывает.

Главы отчёта (1.1.1, 1.1.2, 1.2, 2, 11.3) — разделы-заглушки в ``CHAPTERS``; каждая наполняется отдельным PR.
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from atlas.engine.core.config import ordered
from atlas.engine.core.loader import canonical_gsp, unify_groups

from ..contract import Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Stat, Table
from ..domain import DatasetKind
from ._production import KINDS, group_of, periods_of, visible_periods
from .plan_fact import month_label

PRODUCTION, OBJECT = DatasetKind.PRODUCTION, DatasetKind.OBJECT_PRESSURE
Q_UNIT = 'тыс. м³/сут'
P_UNIT = 'кгс/см²'
OBJECT_SCOPE = 'Объект'
WHOLE = 'Весь сезон'
NOTE = ('Средние считаются по суткам с положительным расходом; пропущенные даты не считаются нулём и простоем. '
        'Длительность — календарные сутки от первого до последнего суток с расходом включительно (високосный год — по календарю). '
        'Давления абсолютные, кгс/см²: давление объекта берётся на дату начала, пика или на ближайшую к ней дату.')

# Главы отчёта, для которых в Атласе будет свой раздел. Пока — только заметка о том, что раздел в работе.
CHAPTERS = (
    ('1.1.1', 'Отбор: статистика сезона'),
    ('1.1.2', 'Фонд скважин: таблицы 1.4–1.6'),
    ('1.2', 'Режим закачки: таблица 1.10 (ГСП-9)'),
    ('2', 'Закачка: статистика сезона'),
    ('11.3', 'Межколонные давления: таблица 11.3'),
)


def pressure_near(pressure: pd.DataFrame | None, when: Any) -> float | None:
    """Давление объекта на дату ``when`` или на ближайшую к ней; при равной разнице берётся более ранняя дата."""
    if pressure is None or pressure.empty:
        return None
    p = pressure.dropna(subset=['pressure']).sort_values('date', kind='stable')
    if p.empty:
        return None
    gap = (p.date - pd.Timestamp(when)).abs()
    return float(p.loc[gap.idxmin(), 'pressure'])


def well_scopes(mapping: Mapping[str, Mapping[str, str]], wells: list[str]) -> dict[str, str]:
    """Скважина → группа в едином написании: регистр, пробелы, «_» и «-» не различают группы."""
    raw = pd.Series([group_of(mapping, w) for w in wells], dtype=object)
    names = canonical_gsp(unify_groups(raw)).to_numpy()
    return dict(zip(wells, names))


def daily_rates(d: pd.DataFrame, scopes: Mapping[str, str]) -> pd.DataFrame:
    """Суточный расход (м³/сут) объекта и каждой группы: scope, date, q; только сутки с положительным расходом."""
    obj = d.groupby('date').q.sum(min_count=1).reset_index().assign(scope=OBJECT_SCOPE)
    grp = d.assign(scope=d.well.map(scopes)).groupby(['scope', 'date']).q.sum(min_count=1).reset_index()
    out = pd.concat([obj, grp], ignore_index=True)
    out = out[out.q.gt(0)].copy()
    out['month'] = out.date.dt.to_period('M').dt.to_timestamp()
    return out


def season_report(prod: pd.DataFrame, mapping: Mapping[str, Mapping[str, str]], pressure: pd.DataFrame | None,
                  kind: str, period: str) -> tuple[dict[str, Any] | None, pd.DataFrame]:
    """Сводка одного сезона и средние по объекту и группам (за весь сезон и по месяцам).

    Возвращает (сводка или None, если в сезоне нет суток с расходом; таблица средних: scope, period, days, mean).
    """
    d = prod[prod.kind.eq(kind) & prod.period.eq(period)][['well', 'date', 'q']].copy()
    d['well'] = d.well.astype(str)
    scopes = well_scopes(mapping, ordered(d.well.unique())) if not d.empty else {}
    daily = daily_rates(d, scopes)
    obj = daily[daily.scope.eq(OBJECT_SCOPE)]
    if obj.empty:
        return None, pd.DataFrame(columns=['scope', 'period', 'days', 'mean'])
    start, stop = obj.date.min(), obj.date.max()
    peak = obj.loc[obj.q.idxmax()]
    summary = {
        'period': period,
        'start': start,
        'stop': stop,
        'days': (stop - start).days + 1,
        'active_days': len(obj),
        'wells': int(d[d.q.gt(0)].well.nunique()),
        'mean': obj.q.mean() / 1000,
        'peak': peak.q / 1000,
        'peak_date': peak.date,
        'pressure_start': pressure_near(pressure, start),
        'pressure_peak': pressure_near(pressure, peak.date),
    }
    rows = []
    for scope in [OBJECT_SCOPE] + [s for s in ordered(daily.scope.unique()) if s != OBJECT_SCOPE]:
        part = daily[daily.scope.eq(scope)]
        rows.append({'scope': scope, 'period': WHOLE, 'days': len(part), 'mean': part.q.mean() / 1000})
        for month, chunk in part.groupby('month', sort=True):
            rows.append({'scope': scope, 'period': month_label(month), 'days': len(chunk), 'mean': chunk.q.mean() / 1000})
    return summary, pd.DataFrame(rows)


class AuthorReportModule(Module):
    spec = ModuleSpec(
        id='an_report',
        title='Авторский надзор: сезон',
        group='Авторский надзор',
        description='Общий расчёт сезона для глав отчёта АН: даты, длительность, средние по объекту и группам, пик, давление.',
        needs=(PRODUCTION,),
        optional=(OBJECT,),
        order=110,
        save_label='Сохранить вид',
        params=(
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section='Выбор данных'),
            Param('periods', 'Сезоны', 'multi', default=[], dynamic=True, depends=('kind',), auto='last:1',
                  empty='ничего', section='Выбор данных'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name != 'periods':
            return super().options(name, data, params)
        return visible_periods(periods_of(data[PRODUCTION], params.get('kind') or 'withdrawal'), data.settings)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        kind = params['kind']
        pressure = data[OBJECT] if OBJECT in data else None
        if pressure is None:
            result.notes.append(Note('Давление объекта не загружено: столбцы давления будут пустыми. '
                                     'Загрузите «Давление объекта» (среднее пластовое, абсолютное).', 'warning'))
        known = set(periods_of(data[PRODUCTION], kind))
        periods = [p for p in params['periods'] if p in known]
        if not periods:
            result.notes.append(Note('Выберите сезон: в проекте нет данных для выбранного режима.'))
        summaries, means = [], []
        for period in periods:
            summary, table = season_report(data[PRODUCTION], data.mapping, pressure, kind, period)
            if summary is None:
                result.notes.append(Note(f'Сезон {period}: нет суток с расходом — расчёт пропущен.'))
                continue
            summaries.append(summary)
            means.append(table.assign(period_season=period))
            result.summary += [Stat(f'Длительность · {period}', f'{summary["days"]} сут', 'Календарные сутки с расходом'),
                               Stat(f'Средний расход · {period}', f'{summary["mean"]:.1f} {Q_UNIT}'.replace('.', ','))]
        if summaries:
            result.tables.append(self.season_table(summaries))
            result.tables.append(self.means_table(means))
        result.notes.append(Note(NOTE))
        for number, title in CHAPTERS:
            result.notes.append(Note(f'Глава {number} · {title}: раздел в разработке, появится отдельным изменением.'))
        return result

    @staticmethod
    def season_table(summaries: list[dict[str, Any]]) -> Table:
        frame = pd.DataFrame(summaries)
        columns = [Column('period', 'Сезон'), Column('start', 'Начало', kind='date'), Column('stop', 'Остановка', kind='date'),
                   Column('days', 'Длительность, сут', decimals=0, kind='number'),
                   Column('active_days', 'Суток с расходом', decimals=0, kind='number'),
                   Column('wells', 'Скважин в работе', decimals=0, kind='number'),
                   Column('mean', 'Средний расход объекта', Q_UNIT, 1, 'number'),
                   Column('peak', 'Максимум суточного', Q_UNIT, 1, 'number'),
                   Column('peak_date', 'Дата максимума', kind='date'),
                   Column('pressure_start', f'Рпл на начало, абс. {P_UNIT}', decimals=2, kind='number'),
                   Column('pressure_peak', f'Рпл на дату максимума, абс. {P_UNIT}', decimals=2, kind='number')]
        return Table('an-season', 'Сезон: основные показатели', frame, columns)

    @staticmethod
    def means_table(parts: list[pd.DataFrame]) -> Table:
        frame = pd.concat(parts, ignore_index=True)
        frame = frame.rename(columns={'period_season': 'season'})
        columns = [Column('season', 'Сезон'), Column('scope', 'Группа'), Column('period', 'Период'),
                   Column('days', 'Суток с расходом', decimals=0, kind='number'),
                   Column('mean', 'Средний суточный расход', Q_UNIT, 1, 'number')]
        return Table('an-season-means', 'Средние суточные расходы: объект и группы', frame[['season', 'scope', 'period', 'days', 'mean']],
                     columns, note='Строка «Весь сезон» — среднее за сезон, остальные — по месяцам.')

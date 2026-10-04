"""План и факт по группам: сопоставление плановых и фактических объёмов отбора или закачки за сезон.

Факт — сумма суточных объёмов скважин по их группам (исключённые точки не считаются, пропуски не нули).
План приходит отдельным набором «План по группам» (группа, месяц, режим, объём, млн м³) через обычный импорт.
Сезон плана — сезон факта за тот же месяц, поэтому правило сезонов проекта действует и здесь.
Образец в отчёте: рис. 1.9 и 2.3, таблицы 2.1 и 2.4.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from app.core.config import ordered
from app.modules import production as legacy

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Param, Result, Series, Stat, Table
from ..domain import DatasetKind
from ._group_charts import _valid
from ._production import KINDS, group_of, periods_of

PRODUCTION, PLAN = DatasetKind.PRODUCTION, DatasetKind.PLAN
UNIT = 'млн м³'
PLAN_COLOR, FACT_COLOR = '#1f4e8c', '#ff5a1f'      # как на рис. 2.3 отчёта: синий — план, оранжевый — факт
MONTHS = ('январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь')
NOTE = ('Факт — сумма по скважинам группы за месяц; план берётся из набора «План по группам». '
        'Пропущенные дни не считаются нулём. «Выполнение» — факт к плану, %.')


def month_label(ts: pd.Timestamp) -> str:
    return f'{MONTHS[ts.month - 1].capitalize()} {ts.year}'


def plan_periods(prod: pd.DataFrame, plan: pd.DataFrame, settings: Mapping[str, Any]) -> pd.Series:
    """Сезон каждой строки плана: тот, что факт имеет в этом месяце; нет факта — правило сезонов проекта."""
    months = plan.date.dt.to_period('M').dt.to_timestamp()
    seen = prod.assign(month=prod.date.dt.to_period('M').dt.to_timestamp())
    seen = seen[seen.kind.isin(plan.kind.unique())]
    known = seen.groupby(['kind', 'month']).period.agg(lambda s: s.value_counts().index[0])
    keys = pd.MultiIndex.from_arrays([plan.kind, months])
    out = pd.Series(known.reindex(keys).to_numpy(), index=plan.index, dtype=object)
    missing = out.isna()
    if missing.any():
        guess = legacy.periods_for(plan.loc[missing, ['date', 'kind']], settings)
        out.loc[missing] = guess.period.to_numpy()
    return out


def fact_by_group(prod: pd.DataFrame, mapping: Mapping[str, Mapping[str, str]], kind: str) -> pd.DataFrame:
    """Факт: kind, period, month, group, fact (млн м³)."""
    d = prod[prod.kind.eq(kind)]
    d = d.assign(v=_valid(d), month=d.date.dt.to_period('M').dt.to_timestamp())
    wells = d.groupby(['period', 'month', 'well'], sort=False).v.sum(min_count=1).rename('fact').reset_index()
    wells['group'] = wells.well.map(lambda w: group_of(mapping, str(w)))
    out = wells.groupby(['period', 'month', 'group'], sort=False).fact.sum(min_count=1).reset_index()
    out['fact'] = out.fact / 1e6
    return out


def compare(prod: pd.DataFrame, plan: pd.DataFrame, mapping: Mapping[str, Mapping[str, str]], kind: str,
            settings: Mapping[str, Any]) -> pd.DataFrame:
    """План и факт по сезону, месяцу и группе: period, month, group, plan, fact (млн м³). Группы без плана не входят."""
    p = plan[plan.kind.eq(kind)]
    if p.empty:
        return pd.DataFrame(columns=['period', 'month', 'group', 'plan', 'fact'])
    p = p.assign(period=plan_periods(prod, p, settings), month=p.date.dt.to_period('M').dt.to_timestamp(),
                 group=p.group.astype(str))
    p = p.groupby(['period', 'month', 'group'], sort=False).plan_volume.sum().rename('plan').reset_index()
    f = fact_by_group(prod, mapping, kind)
    return p.merge(f, on=['period', 'month', 'group'], how='left')


def ratio(plan, fact):
    return np.where(plan > 0, fact / plan * 100, np.nan)


def summed(d: pd.DataFrame, by: str) -> pd.DataFrame:
    s = d.groupby(by, sort=False).agg(plan=('plan', 'sum'), fact=('fact', lambda v: v.sum(min_count=1))).reset_index()
    s['percent'] = ratio(s.plan, s.fact)
    s['delta'] = s.fact - s.plan
    return s


class PlanFactModule(Module):
    spec = ModuleSpec(
        id='plan_fact',
        title='План и факт по группам',
        group='Эксплуатация',
        description='Плановые и фактические объёмы отбора или закачки по группам и месяцам сезона.',
        needs=(PRODUCTION, PLAN),
        order=25,
        save_label='Сохранить вид',
        params=(
            Param('kind', 'Режим', 'choice', default='injection', options=KINDS, section='Выбор данных'),
            Param('periods', 'Сезоны', 'multi', default=[], dynamic=True, depends=('kind',), auto='last:1',
                  empty='ничего', section='Выбор данных'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name != 'periods':
            return super().options(name, data, params)
        if PLAN not in data or data[PLAN].empty or PRODUCTION not in data:
            return []
        d = compare(data[PRODUCTION], data[PLAN], data.mapping, params.get('kind') or 'injection', data.settings)
        return [p for p in periods_of(data[PRODUCTION], params.get('kind') or 'injection') if p in set(d.period)]

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        kind = params['kind']
        d = compare(data[PRODUCTION], data[PLAN], data.mapping, kind, data.settings)
        if d.empty:
            result.notes.append(Note('В плане нет строк для выбранного режима: загрузите «План по группам» в разделе импорта.'))
            return result
        periods = [p for p in params['periods'] if p in set(d.period)]
        if not periods:
            result.notes.append(Note('Выберите сезон, для которого загружен план.'))
            return result
        result.notes.append(Note(NOTE))
        groups_table, months_table = [], []
        for period in periods:
            part = d[d.period.eq(period)]
            by_group, by_month = summed(part, 'group'), summed(part, 'month')
            by_group = by_group.set_index('group').loc[ordered(by_group.group)].reset_index()
            by_month = by_month.sort_values('month')
            result.charts.append(self.groups_chart(by_group, period, kind))
            result.charts.append(self.months_chart(by_month, period, kind))
            total = summed(part.assign(all='Суммарно'), 'all').iloc[0]
            result.summary += [Stat(f'План · {period}', f'{total.plan:,.1f} {UNIT}'.replace(',', ' ')),
                               Stat(f'Факт · {period}', f'{total.fact:,.1f} {UNIT}'.replace(',', ' ') if pd.notna(total.fact) else '—'),
                               Stat(f'Выполнение · {period}', f'{total.percent:.1f} %' if pd.notna(total.percent) else '—')]
            self.outside_plan(result, data, kind, period, set(part.group))
            self.unfinished(result, part, period)
            groups_table.append(by_group.assign(period=period))
            months_table.append(pd.concat([by_month.assign(label=by_month.month.map(month_label)),
                                           pd.DataFrame([{'label': 'Суммарно', 'plan': total.plan, 'fact': total.fact,
                                                          'percent': total.percent, 'delta': total.fact - total.plan}])],
                                          ignore_index=True).assign(period=period))
        result.tables.append(self.table('plan-fact-groups', 'По группам', pd.concat(groups_table, ignore_index=True),
                                        'group', 'Группа'))
        result.tables.append(self.table('plan-fact-months', 'По месяцам', pd.concat(months_table, ignore_index=True),
                                        'label', 'Месяц'))
        return result

    @staticmethod
    def table(tid: str, title: str, frame: pd.DataFrame, key: str, label: str) -> Table:
        frame = frame[['period', key, 'plan', 'fact', 'percent', 'delta']]
        return Table(tid, title, frame, [Column('period', 'Сезон'), Column(key, label),
                                         Column('plan', 'План', UNIT, 1, 'number'), Column('fact', 'Факт', UNIT, 1, 'number'),
                                         Column('percent', 'Выполнение', '%', 1, 'number'),
                                         Column('delta', 'Факт − план', UNIT, 1, 'number')])

    @staticmethod
    def pair(chart: Chart, cats: list[str], plan: np.ndarray, fact: np.ndarray, percent: np.ndarray) -> Chart:
        tips = [f'выполнение {v:.1f} %' if np.isfinite(v) else 'нет плана или факта' for v in percent]
        chart.series.append(Series('План', cats, plan, 'bar', color=PLAN_COLOR, labels=tips))
        chart.series.append(Series('Факт', cats, fact, 'bar', color=FACT_COLOR, labels=tips))
        return chart

    def groups_chart(self, s: pd.DataFrame, period: str, kind: str) -> Chart:
        what = 'закачки' if kind == 'injection' else 'отбора'
        cats = [f'ГСП {g}' if str(g).isdigit() else str(g) for g in s.group]
        chart = Chart(f'plan-fact-groups-{period}', f'План и факт {what} по группам · {period}',
                      Axis('Группа', scale='category', categories=cats), Axis('Объём', UNIT, from_zero=True))
        return self.pair(chart, cats, s.plan.to_numpy(float), s.fact.to_numpy(float), s.percent.to_numpy(float))

    def months_chart(self, s: pd.DataFrame, period: str, kind: str) -> Chart:
        what = 'закачки' if kind == 'injection' else 'отбора'
        cats = [month_label(m) for m in s.month]
        chart = Chart(f'plan-fact-months-{period}', f'План и факт {what} по месяцам · {period}',
                      Axis('Месяц', scale='category', categories=cats), Axis('Объём', UNIT, from_zero=True))
        return self.pair(chart, cats, s.plan.to_numpy(float), s.fact.to_numpy(float), s.percent.to_numpy(float))

    @staticmethod
    def outside_plan(result: Result, data: Data, kind: str, period: str, planned: set) -> None:
        """Факт групп, которых нет в плане, в сравнение не входит: показываем его заметкой."""
        f = fact_by_group(data[PRODUCTION], data.mapping, kind)
        f = f[f.period.eq(period) & ~f.group.isin(planned)]
        by = f.groupby('group').fact.sum()
        by = by[by.gt(0)]
        if not by.empty:
            result.notes.append(Note(f'{period}: факт групп без плана не вошёл в сравнение: ' +
                                     ', '.join(f'{g} — {v:,.1f} {UNIT}'.replace(',', ' ') for g, v in by.items()) + '.', 'warning'))

    @staticmethod
    def unfinished(result: Result, part: pd.DataFrame, period: str) -> None:
        months = part.groupby('month').fact.apply(lambda v: v.isna().all())
        empty = [month_label(m) for m in months.index[months]]
        if empty:
            result.notes.append(Note(f'{period}: по месяцам без факта ({", ".join(empty)}) план учтён, а факта нет, '
                                     'поэтому выполнение занижено.', 'warning'))

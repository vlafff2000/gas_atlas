"""Гистограммы по фондам скважин: сколько скважин в каждом фонде и как эксплуатационные делятся на группы.

Фонд берётся из проекта (``atlas/well_funds.py``): ручной выбор инженера важнее подсказки. Скважина без признаков фонда
показана отдельным столбцом «Не определён» — её фонд выбирают вручную. Математики нет: только подсчёт и представление.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from atlas import well_funds

from ..contract import Axis, Chart, Column, Data, DatasetKind, Module, ModuleSpec, Note, Option, Param, Result, Series, Table

UNKNOWN = 'Не определён'
NO_GROUP = 'Без группы'
SECTION = 'Выбор данных'


def fund_rows(data: Data) -> pd.DataFrame:
    """Скважина, фонд (подпись), группа и подгруппа; по фондам проекта."""
    frames = {k.value if isinstance(k, DatasetKind) else str(k): v for k, v in data.raw.items()}
    groups = {w: (m or {}).get('group', '') for w, m in data.mapping.items()}
    rows = well_funds.table(frames, groups, data.settings or {})
    sub = {well_funds.norm(w): (m or {}).get('subgroup', '') for w, m in data.mapping.items()}
    out = pd.DataFrame([{'well': r['well'], 'fund': well_funds.LABEL.get(r['fund'], UNKNOWN),
                         'group': r['group'] or NO_GROUP, 'subgroup': sub.get(r['well'], ''),
                         'manual': r['manual'], 'reason': r['reason']} for r in rows],
                       columns=['well', 'fund', 'group', 'subgroup', 'manual', 'reason'])
    return out


def count_chart(cid: str, title: str, axis_label: str, counts: pd.Series, color: str = '') -> Chart:
    cats = [str(c) for c in counts.index]
    chart = Chart(cid, title, Axis(axis_label, scale='category', categories=cats), Axis('Скважин', 'шт', from_zero=True, step=1))
    chart.series.append(Series('Скважин', cats, counts.to_numpy(), 'bar', color=color, labels=[f'{int(v)} скв.' for v in counts]))
    return chart


class FundHistModule(Module):
    spec = ModuleSpec(
        id='fund_hist',
        title='Гистограммы по фондам скважин',
        group='Фонд скважин',
        description='Число скважин по фондам (эксплуатационные, наблюдательные, геофизические, контрольные) '
                    'и деление эксплуатационных на группы.',
        order=55,
        params=(
            Param('split', 'Деление эксплуатационных', 'choice', default='group', section=SECTION,
                  options=(Option('group', 'По группам'), Option('subgroup', 'По подгруппам'))),
            Param('funds', 'Фонды на общей гистограмме', 'multi', default=[], dynamic=True, auto='all', empty='ничего',
                  section=SECTION),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'funds':
            return [label for _, label in well_funds.FUNDS] + [UNKNOWN]
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        rows = fund_rows(data)
        if rows.empty:
            result.notes.append(Note('Сначала загрузите данные: скважины и фонды появятся здесь после импорта.'))
            return result
        labels = [label for _, label in well_funds.FUNDS] + [UNKNOWN]
        shown = [f for f in (params.get('funds') or labels) if f in labels]
        by_fund = rows.groupby('fund').size().reindex(labels).fillna(0).astype(int)
        result.charts.append(count_chart('fund-counts', 'Скважины по фондам', 'Фонд', by_fund.loc[shown]))
        prod = rows[rows.fund == well_funds.LABEL['production']]
        key = 'subgroup' if params.get('split') == 'subgroup' else 'group'
        if prod.empty:
            result.notes.append(Note('Эксплуатационных скважин нет: распределение по группам не построено.'))
        else:
            col = prod[key].where(prod[key].astype(str).str.strip() != '', NO_GROUP if key == 'group' else 'Без подгруппы')
            by_key = col.value_counts().sort_index()
            what = 'подгруппам' if key == 'subgroup' else 'группам'
            result.charts.append(count_chart('fund-production-split', f'Эксплуатационные скважины по {what}',
                                             'Подгруппа' if key == 'subgroup' else 'Группа', by_key))
        unknown = int(by_fund[UNKNOWN])
        if unknown:
            result.notes.append(Note(f'У {unknown} скв. фонд не определён: выберите его вручную в таблице фондов проекта.', 'warning'))
        table = rows.sort_values(['fund', 'group', 'well'], key=lambda s: s.map(
            lambda v: (not str(v).isdigit(), int(v) if str(v).isdigit() else 0, str(v))) if s.name == 'well' else s)
        result.tables.append(Table('fund-wells', 'Скважины по фондам', table.assign(manual=table.manual.map({True: 'вручную', False: 'авто'})),
                                   [Column('well', 'Скважина'), Column('fund', 'Фонд'), Column('group', 'Группа'),
                                    Column('subgroup', 'Подгруппа'), Column('manual', 'Выбор'), Column('reason', 'Причина подсказки')]))
        return result

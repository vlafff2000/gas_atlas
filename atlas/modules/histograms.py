"""Гистограммы по эксплуатации скважин: средние расходы по скважинам или по периодам.

Полный перечень функций раздела — docs/parity/production.md.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..contract import Data, ModuleSpec, Option, Param, Result
from ._production import DIRECTIONS, KINDS, PRODUCTION, ProductionBase, Selection, histogram_charts

SECTION_DATA, SECTION_VIEW = 'Выбор данных', 'Вид'
SIZES = ('Авто', '10', '20', '50', 'Все')


def histogram_size(value: str, count: int) -> int:
    """Скважин на одной гистограмме: как ``app.ui.selection.histogram_size``."""
    if value == 'Все':
        return max(1, count)
    if value == 'Авто':
        return 10
    return max(1, int(value))


class HistogramModule(ProductionBase):
    spec = ModuleSpec(
        id='histograms',
        title='Гистограммы по эксплуатации скважин',
        group='Эксплуатация',
        description='Сравнение периодов и расходов выбранных скважин и групп.',
        needs=(PRODUCTION,),
        order=20,
        panels=2,
        params=(
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section=SECTION_DATA),
            Param('groups', 'Группы', 'multi', default=[], dynamic=True, auto='all', empty='ничего',
                  section=SECTION_DATA),
            Param('wells', 'Скважины', 'multi', default=[], dynamic=True, depends=('groups',), auto='first:10',
                  empty='ничего', prefix='№ ', section=SECTION_DATA),
            Param('periods', 'Периоды', 'multi', default=[], dynamic=True, depends=('kind',), auto='last:3',
                  empty='ничего', section=SECTION_DATA),
            Param('axis', 'Ось гистограммы', 'choice', default='well', section=SECTION_VIEW, chart_kind=True,
                  options=(Option('well', 'Скважины'), Option('period', 'Периоды'))),
            Param('hist_size', 'Скважин на одной гистограмме', 'choice', default='Авто', section=SECTION_VIEW,
                  options=tuple(Option(s, s) for s in SIZES)),
            Param('direction', 'Порядок скважин', 'choice', default='number', options=DIRECTIONS, section=SECTION_VIEW),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        sel = Selection(data, params)
        result = Result()
        ws = sel.wells()
        if not ws or not sel.periods:
            return self.nothing_selected(result)
        size = histogram_size(params['hist_size'], len(ws))
        result.charts.extend(histogram_charts(sel, ws, params['axis'], size, 'hist'))
        self.common_tables(result, sel, ws)
        return result

    # --- сохранённый вид: формат 5.8 (settings.panels.hist_0 / hist_1; раньше — prod_0 / prod_1) ---
    def panel_key(self, panel: int = 0) -> str:
        return f'hist_{panel}'

    def panel_fallbacks(self, panel: int = 0) -> tuple[str, ...]:
        return (f'prod_{panel}',)

    def save_state(self, params: dict[str, Any], data: Data) -> dict[str, Any]:
        return {'kind': params['kind'], 'periods': params['periods'], 'wells': params['wells'], 'groups': params['groups'],
                'view': 'hist', 'direction': params['direction'], 'histaxis': params['axis'],
                'hist_size': params['hist_size'], 'two': False}

    def load_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        out = {k: state[k] for k in ('kind', 'periods', 'wells', 'groups', 'direction', 'hist_size') if state.get(k) is not None}
        if state.get('histaxis') is not None:
            out['axis'] = state['histaxis']
        return out

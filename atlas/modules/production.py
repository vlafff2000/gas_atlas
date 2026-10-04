"""Производительность скважин: суточный расход по накопленному объёму или по дате; суммы по группам.

Полный перечень функций раздела — docs/parity/production.md.
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
from app.modules import group_analysis

from ..contract import Data, ModuleSpec, Note, Option, Param, Result, Stat
from ..domain import DatasetKind
from ._group_charts import SHARE_METRICS, hybrid_chart, object_days, pareto_chart, share_chart, vs_object_chart, well_days
from ._production import (DIRECTIONS, GROUP_NOTE, KINDS, CURVE_NOTE, PRODUCTION, ProductionBase, Selection, curve_chart, kind_label, period_stat,
                          group_chart, group_table)

SECTION_DATA, SECTION_VIEW = 'Выбор данных', 'Вид'
INDIVIDUAL, GROUPS = {'mode': 'individual'}, {'mode': 'groups'}
MANY_CURVES = 200       # столько кривых на одном графике уже не различить, а строятся они десятки секунд


class ProductionModule(ProductionBase):
    spec = ModuleSpec(
        id='production',
        title='Производительность скважин',
        group='Эксплуатация',
        description='Сравнение периодов и расходов выбранных скважин и групп.',
        needs=(PRODUCTION,),
        optional=(DatasetKind.GDI,),       # даты ГДИ — отметки на графике по дате
        order=10,
        panels=2,
        params=(
            Param('mode', 'Представление', 'choice', default='individual', section=SECTION_DATA,
                  options=(Option('individual', 'Отдельные скважины'), Option('groups', 'Суммарные показатели групп'))),
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section=SECTION_DATA),
            Param('groups', 'Группы', 'multi', default=[], dynamic=True, auto='all', empty='ничего',
                  section=SECTION_DATA),
            Param('wells', 'Скважины', 'multi', default=[], dynamic=True, depends=('groups',), auto='first:10',
                  empty='ничего', prefix='№ ', section=SECTION_DATA, show_if=INDIVIDUAL),
            Param('periods', 'Периоды', 'multi', default=[], dynamic=True, depends=('kind',), auto='last:3',
                  empty='ничего', section=SECTION_DATA),
            Param('overlay', 'Скважины поверх суммы', 'multi', default=[], dynamic=True, depends=('groups',),
                  empty='ничего', prefix='№ ', section=SECTION_DATA, show_if=GROUPS,
                  help='Выбор кривых наложения не меняет сумму'),
            Param('view', 'График', 'choice', default='curve', section=SECTION_VIEW, show_if=INDIVIDUAL, options=(
                Option('curve', 'Q / накопленный объем объекта'), Option('time', 'Q / дата'))),
            Param('direction', 'Порядок скважин', 'choice', default='number', options=DIRECTIONS,
                  section=SECTION_VIEW, show_if=INDIVIDUAL),
            Param('metric', 'Показатель группы', 'choice', default='daily', section=SECTION_VIEW, show_if=GROUPS,
                  options=(Option('daily', 'Суточный суммарный расход'), Option('cumulative', 'Накопленный объем'),
                           Option('active', 'Работающие скважины'),
                           Option('shares', 'Доля скважин в накопленном объеме группы'),
                           Option('hybrid', 'Месячные объемы по скважинам + суточный расход'),
                           Option('pareto', 'Вклад скважин в объем (Парето)'),
                           Option('vs_object', 'Группа и объект, доля группы'))),
            Param('gx', 'Ось X', 'choice', default='date', section=SECTION_VIEW, show_if=GROUPS,
                  options=(Option('date', 'Дата'), Option('object', 'Накопленный объем объекта')),
                  help='Только для суточного суммарного расхода'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        sel = Selection(data, params)
        result = Result()
        if params['mode'] == 'groups':
            return self.run_groups(result, sel)
        ws = sel.wells()
        if not ws or not sel.periods:
            return self.nothing_selected(result)
        curves = len(ws) * len(sel.periods)
        if curves > MANY_CURVES:
            result.notes.append(Note(
                f'Выбрано {curves:,} кривых ({len(ws)} скважин × {len(sel.periods)} периодов) на одном графике: '
                'он строится долго и плохо читается. Выберите меньше скважин или периодов (например, одну группу или '
                'последние сезоны). Линии показаны с прореживанием, пики и провалы сохранены; при увеличении видны все '
                'точки, выгрузки и таблицы содержат все данные.'.replace(',', ' '), 'warning'))
        result.charts.append(curve_chart(sel, ws, 'date' if params['view'] == 'time' else 'cumulative'))
        result.notes.append(Note(CURVE_NOTE))
        self.common_tables(result, sel, ws)
        return result

    @staticmethod
    def run_groups(result: Result, sel: Selection) -> Result:
        if not sel.periods or not sel.groups:
            result.notes.append(Note('Выберите группы и периоды.'))
            return result
        result.notes.append(Note(GROUP_NOTE))
        result.summary = [Stat('Групп', str(len(sel.groups))),
                          Stat('Скважин в группах', str(len(sel.choices()))),
                          Stat('Режим', kind_label(sel.kind)), period_stat(sel.periods)]
        metric, overlay = sel.params['metric'], sel.params['overlay']
        for group in sel.groups:
            daily, wells = group_analysis.daily(sel.df, sel.mapping, group, sel.kind, sel.periods)
            if metric in SHARE_METRICS:
                if daily.empty:
                    continue
                d = well_days(sel, wells)
                result.charts.append({'shares': lambda: share_chart(sel, d, group),
                                      'hybrid': lambda: hybrid_chart(sel, d, daily, group),
                                      'pareto': lambda: pareto_chart(sel, d, group),
                                      'vs_object': lambda: vs_object_chart(sel, daily, object_days(sel), group)}[metric]())
            else:
                result.charts.append(group_chart(sel, daily, wells, group, metric, overlay,
                                                 sel.params['gx'] == 'object'))
            if not daily.empty:
                result.tables.append(group_table(group, daily))
        return result

    # --- сохранённый вид: формат 5.8 (settings.panels.prod_0 / prod_1) ---
    def panel_key(self, panel: int = 0) -> str:
        return f'prod_{panel}'

    def save_state(self, params: dict[str, Any], data: Data) -> dict[str, Any]:
        return {'kind': params['kind'], 'periods': params['periods'], 'wells': params['wells'], 'groups': params['groups'],
                'view': params['view'], 'direction': params['direction'], 'histaxis': 'well', 'hist_size': 'Авто',
                'two': False}

    def load_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        names = ('kind', 'periods', 'wells', 'groups', 'view', 'direction')
        return {k: state[k] for k in names if state.get(k) is not None}

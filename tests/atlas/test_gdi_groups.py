"""Справка ГДИ: разбивка скважин на улучшение, без изменений и ухудшение; период сравнения (вместе или по сезонам)."""
import pandas as pd

from atlas import registry
from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.engine.core import exclusions
from atlas.engine.core.demo import demo_frames

GDI = DatasetKind.GDI


def frame():
    d = demo_frames()['gdi'].copy()
    late = d.date.eq(d.date.max())
    d.loc[late & d.well.eq('31'), 'dp2'] *= 1.3            # та же форма ΔP² = aQ + bQ², но выше: отдача упала
    # Скважина 31 летом 2025 после ремонта: то же исследование с ΔP² в 0,7 раза — отдача выросла.
    summer = d[d.well.eq('31') & d.date.eq(pd.Timestamp('2024-12-10'))].copy()
    summer['date'] = pd.Timestamp('2025-06-10')
    summer['dp2'] *= 0.7
    return exclusions.identify(pd.concat([d, summer], ignore_index=True), 'gdi')


def run(data, **params):
    module = registry.get('gdi')
    prepared = exclusions.apply({'gdi': data}, {'excluded_points': {}})['gdi']
    wells = sorted(data.well.astype(str).unique())
    return module.run(Data({GDI: prepared}, {GDI: data}, {}),
                      module.spec.coerce({'wells': wells, 'last_n': 0, 'change_threshold': 5, **params}))


def groups(result):
    return next(t for t in result.tables if t.id == 'groups').frame


def wells_of(table, verdict, season=None):
    row = table[table.verdict.eq(verdict)]
    if season is not None:
        row = row[row.season.eq(season)]
    return set(w.strip() for text in row.wells for w in text.split(',') if w.strip()) if len(row) else set()


def test_groups_cover_every_well_and_name_the_declining_one():
    data = frame()
    table = groups(run(data))
    listed = set().union(*(wells_of(table, v) for v in table.verdict.unique()))  # все скважины попали в группы
    assert listed == set(data.well.astype(str).unique())
    assert '31' in wells_of(table, 'Ухудшение')
    assert '31' not in wells_of(table, 'Улучшение')


def test_season_split_gives_separate_verdicts():
    result = run(frame(), period='season')
    table = groups(result)
    assert '31' in wells_of(table, 'Улучшение', '2024-2025')          # летний ремонт — отдельная оценка
    assert '31' in wells_of(table, 'Недостаточно надёжных', '2023-2024')
    assert 'season' in next(t for t in result.tables if t.id == 'productivity').frame.columns


def test_date_range_removes_the_pair_and_leaves_too_few_studies():
    table = groups(run(frame(), period='season', date_from='2025-01-01'))
    assert '31' in wells_of(table, 'Недостаточно надёжных', '2024-2025')


def test_together_uses_first_and_last_reliable_study_of_period():
    table = groups(run(frame(), period='together'))
    assert set(table.columns) >= {'verdict', 'count', 'wells'} and 'season' not in table.columns

"""«ГСП 5» и «ГСП-5» — одна группа: единая нормировка при импорте и при чтении уже загруженных проектов."""
import pandas as pd

from atlas.engine.core.loader import group_merges, normalize_groups


def test_variants_become_one_group():
    s = pd.Series(['ГСП 5', 'ГСП-5', 'гсп_5', 'ГСП5', ' ГСП  5 ', 'ГСП-05'])
    assert set(normalize_groups(s)) == {'ГСП 5'}


def test_merges_are_reported():
    raw = pd.Series(['ГСП 5', 'ГСП-5', 'ГСП 6'])
    assert group_merges(raw, normalize_groups(raw)) == {'ГСП 5': ['ГСП-5']}


def test_catalog_unifies_old_project(tmp_path):
    from atlas.engine.core.performance import Project
    folder = tmp_path / 'projects' / 'p' / 'snapshots' / '1'
    folder.mkdir(parents=True)
    pd.DataFrame({'well': ['1', '2', '3'], 'group': ['ГСП 5', 'ГСП-5', 'Без группы'], 'subgroup': ['', '', ''],
                  'date': pd.to_datetime(['2024-01-01'] * 3)}).to_parquet(folder / 'production.parquet')
    cat = Project(tmp_path, 'p', 1, ['production']).catalog()
    assert {cat['mapping'][w]['group'] for w in '12'} == {'ГСП 5'}
    assert cat['group_merges'] == {'ГСП 5': ['ГСП-5']}

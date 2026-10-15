"""Единая схема имён групп (аудит объединения, пункт 8): Атлас, Карты ГСП и Скедул сравнивают группы одинаково.

Тот же список случаев есть в all_scripts/tests/test_group_names.py: менять только вместе.
"""
import pytest

from atlas.engine.core.loader import group_key

# (название из одного файла, название из другого, одна ли это группа)
CASES = [
    ('ГСП-1', 'ГСП 1', True),
    ('ГСП_4', 'гсп 4', True),
    ('ГСП4', 'ГСП 4', True),
    ('СП-2', 'СП 2', True),
    ('ГСП 1', 'ГСП 2', False),
    ('ГСП 1', 'ГСП 10', False),
]


@pytest.mark.parametrize('a, b, same', CASES)
def test_group_names_compare_the_same_way(a, b, same):
    assert (group_key(a) == group_key(b)) is same

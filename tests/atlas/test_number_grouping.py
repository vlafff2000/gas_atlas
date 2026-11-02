"""Разряды на осях: 1000 → «1 000» (неразрывный пробел), десятичный знак не меняется."""
from atlas.engine.core.export_style import group_thousands, ru_format, ru_tick


def test_group_thousands_basic():
    assert group_thousands('1000') == '1 000'
    assert group_thousands('999') == '999'
    assert group_thousands('1234567') == '1 234 567'
    assert group_thousands('1234567.5') == '1 234 567.5'
    assert group_thousands('-12000.25') == '-12 000.25'
    assert group_thousands('1e+06') == '1e+06'


def test_ru_format_and_tick_use_same_grouping():
    assert ru_format(0)(1000, 0) == '1 000'
    assert ru_format(1, 1000.0)(12500, 0) == '12,5'
    assert ru_tick('.10g')(2500, 0) == '2 500'
    assert ru_tick('.2f')(0.5, 0) == '0.50'

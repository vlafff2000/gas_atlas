import pandas as pd

from atlas.contract import Chart, Axis, Result, Series, Table
from atlas.season_format import format_of, relabel, text


def test_text():
    assert text('Отбор 2025-2026, закачка 2025', 'slash') == 'Отбор 2025/2026, закачка 2025'
    assert text('2025/2026', 'dash') == '2025-2026'
    assert text('2025-2027 и 01-2025', 'slash') == '2025-2027 и 01-2025'
    assert format_of({}) == 'dash' and format_of({'season_format': 'slash'}) == 'slash'


def test_result():
    t = Table('t', 'Сезон 2025-2026', pd.DataFrame({'s': ['2025-2026', 'x'], '2024-2025': [1, 2]}))
    c = Chart('c', 'ГДИ 2025-2026', Axis('x'), Axis('y'), [Series('2025-2026', [1], [2], facets={'Период': '2025-2026'})])
    r = relabel(Result(tables=[t], charts=[c]), 'slash')
    assert r.tables[0].title == 'Сезон 2025/2026' and list(r.tables[0].frame['s']) == ['2025/2026', 'x']
    assert '2024/2025' in r.tables[0].frame.columns
    assert r.charts[0].series[0].name == '2025/2026' and r.charts[0].series[0].facets == {'Период': '2025/2026'}
    assert t.title == 'Сезон 2025-2026'


def test_enum_kept():
    from atlas.domain import DatasetKind
    from atlas.contract import TableAction
    t = Table('t', 'x', pd.DataFrame({'a': [1]}), action=TableAction(label='L', endpoint='e', dataset=DatasetKind.PRODUCTION)) \
        if False else None
    k = relabel({'k': DatasetKind.PRODUCTION}, 'slash')
    assert k['k'] is DatasetKind.PRODUCTION

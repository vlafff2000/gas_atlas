"""Оформление «только этот график»: уровень charts в настройке chart_formats идёт после темы и типа и не затрагивает остальные графики."""
from atlas import chart_style
from atlas.contract import Axis, Chart, Result

NOTE = {'kind': 'text', 'x': 'a', 'y': 1, 'text': 'только здесь'}


def _chart(cid):
    return Chart(cid, cid, Axis('x'), Axis('y'))


def test_annotation_only_on_chosen_chart():
    settings = {'chart_formats': {'charts': {'mod::a': {'chart': {'annotations': [NOTE]}}}}}
    res = Result(charts=[_chart('a'), _chart('b')])
    out = chart_style.apply_store(res, settings, 'mod')
    by = {c.id: c for c in out.charts}
    assert by['a'].style.get('annotations')
    assert not by['b'].style.get('annotations')


def test_chart_level_overrides_type():
    settings = {'chart_formats': {'types': {'mod': {'chart': {'background': '#ffffff'}}},
                                  'charts': {'mod::a': {'chart': {'background': '#eeeeee'}}}}}
    assert chart_style.format_of(settings, 'mod', 'a')['chart']['background'] == '#eeeeee'
    assert chart_style.format_of(settings, 'mod', 'b')['chart']['background'] == '#ffffff'


def test_store_accepts_charts():
    got = chart_style.clean_store({'charts': {'mod::a': {'chart': {'annotations': [NOTE]}}}})
    assert 'mod::a' in got['charts']

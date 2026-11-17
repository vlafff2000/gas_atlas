"""Подписи категорий оси X: переименование и перенос строки (экран и файл строятся по одной модели)."""
import pytest

from atlas import chart_style
from atlas.category_labels import label, labels, wrap
from atlas.contract import Axis, Chart, ParamError, Series
from atlas.render import chart_file, to_plotly


def test_wrap_by_words_keeps_own_breaks_and_long_words():
    assert wrap('ГСП 1 северная часть', 8) == 'ГСП 1\nсеверная\nчасть'
    assert wrap('Сверхдлинное слово', 5) == 'Сверхдлинное\nслово'
    assert wrap('первая\nвторая строка', 8) == 'первая\nвторая\nстрока'
    assert wrap('как есть', 0) == 'как есть'


def test_rename_then_wrap():
    spec = {'category_names': {'ГСП-1': 'Северная часть залежи'}, 'category_wrap': 10}
    assert label('ГСП-1', spec) == 'Северная\nчасть\nзалежи'
    assert labels(['ГСП-1', 'ГСП-2'], spec) == ['Северная\nчасть\nзалежи', 'ГСП-2']


def test_axis_settings_are_cleaned_and_reach_the_axis():
    out = chart_style.clean_axis({'category_names': {'a': ' Новое ', 'b': ''}, 'category_wrap': '12'}, 'x')
    assert out['category_names'] == {'a': 'Новое'} and out['category_wrap'] == 12
    with pytest.raises(ParamError):
        chart_style.clean_axis({'category_wrap': 500}, 'x')
    chart = Chart('c', 'T', Axis('X', scale='category', categories=['a']), Axis('Y'))
    chart.series.append(Series('s', ['a'], [1.0], 'bar'))
    doc = {'axes': {'x': out}}
    assert chart_style.apply_format(chart, doc).x.style['category_wrap'] == 12


def test_file_shows_renamed_wrapped_categories():
    cats = ['ГСП-1', 'ГСП-2']
    chart = Chart('c', 'T', Axis('Группа', scale='category', categories=cats), Axis('Y'))
    chart.series.append(Series('s', cats, [1.0, 2.0], 'bar'))
    chart = chart_style.apply_format(chart, {'axes': {'x': {'category_names': {'ГСП-1': 'Северная часть залежи'}, 'category_wrap': 10}}})
    from matplotlib import pyplot
    import matplotlib.figure as mf
    seen = []
    orig = mf.Figure.savefig
    mf.Figure.savefig = lambda self, *a, **k: (seen.extend(t.get_text() for ax in self.axes for t in ax.get_xticklabels()), orig(self, *a, **k))[1]
    try:
        chart_file(chart, 'png', 150)
    finally:
        mf.Figure.savefig = orig
    assert 'Северная\nчасть\nзалежи' in seen and 'ГСП-2' in seen

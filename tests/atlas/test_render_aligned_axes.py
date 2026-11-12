"""Файлы берут шкалы Y из общего автоподбора (atlas/axis_auto.py): те же границы и деления, что на экране."""
from __future__ import annotations

from atlas import axis_auto
from atlas.contract import Axis, Chart, Series
from atlas.render import chart_file, to_plotly


def _chart(**kw):
    c = Chart('t-1', 'Тест', Axis('Дата', scale='time'), Axis('Дебит', from_zero=True), y2=Axis('Давление', **kw))
    c.series.append(Series('a', ['2024-01-01', '2024-02-01', '2024-03-01'], [3.0, 47.0, 120.0], 'line'))
    c.series.append(Series('b', ['2024-01-01', '2024-02-01', '2024-03-01'], [0.31, 0.5, 0.97], 'line', axis='y2'))
    return c


def _counts(fig):
    return [round((axis.range[1] - axis.range[0]) / axis.dtick) for axis in (fig.layout.yaxis, fig.layout.yaxis2)]


def test_two_axes_share_tick_count_and_grid():
    fig = to_plotly(_chart(from_zero=True))
    assert len(set(_counts(fig))) == 1 and 4 <= _counts(fig)[0] <= 8
    for axis in (fig.layout.yaxis, fig.layout.yaxis2):
        assert axis.tick0 == axis.range[0]
    assert fig.layout.yaxis.range[0] <= 0 and fig.layout.yaxis.range[1] >= 120


def test_file_axes_equal_screen_axes():
    """Экран получает график после ``axis_auto.auto_chart``; файл рисует те же границы и шаг — и для одной шкалы тоже."""
    for chart in (_chart(), Chart('t-2', 'Одна шкала', Axis('Дата', scale='time'), Axis('Давление'),
                                  series=[Series('p', ['2024-01-01', '2024-02-01'], [44.3, 87.2], 'line')])):
        shown, fig = axis_auto.auto_chart(chart), to_plotly(chart)
        for name in shown.axis_names():
            spec, axis = shown.axis_at(name), getattr(fig.layout, 'yaxis' if name == 'y' else 'yaxis' + name[1:])
            assert (spec.minimum, spec.maximum, spec.step) == (axis.range[0], axis.range[1], axis.dtick)


def test_fixed_maximum_is_kept():
    fig = to_plotly(_chart(from_zero=True, maximum=100))
    assert fig.layout.yaxis2.range[1] == 100
    assert len(set(_counts(fig))) == 1


def test_inverse_axis_keeps_direction():
    c = _chart(inverse=True)
    fig = to_plotly(c)
    lo, hi = fig.layout.yaxis2.range
    assert lo > hi and fig.layout.yaxis2.tick0 == hi


def test_png_export_runs():
    data, name, _ = chart_file(_chart(), 'png', 150)
    assert data[:4] == b'\x89PNG'


def test_axis_without_data_still_aligned():
    c = _chart(from_zero=True)
    c.series.pop()      # у y2 нет данных
    fig = to_plotly(c)
    assert len(set(_counts(fig))) == 1


def test_manual_step_from_manual_minimum_in_file():
    """Ручные минимум и шаг: деления в файле идут от минимума (37, 47, 57…), как на экране, а не по кратным шагу (40, 50…)."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from atlas.engine.core.export_style import apply_style
    f, ax = plt.subplots()
    try:
        ax.plot([0, 1], [44, 87])
        apply_style(f, ax, {}, {'chart': {}, 'axes': {'y': {'min': 37.0, 'max': 97.0, 'step': 10.0, 'scale': 'value'}}}, '', 1.0, 9, False)
        assert [round(t, 6) for t in ax.get_yticks() if 37 <= t <= 97] == [37, 47, 57, 67, 77, 87, 97]
    finally:
        plt.close(f)


def test_fit_mode_reaches_the_file():
    """Режим «Подбор пределов» из оформления (``style['fit']``) меняет шкалу в файле так же, как на экране."""
    def low(fit):
        c = Chart('t-3', 'Режим', Axis('Дата', scale='time'), Axis('Закачка', from_zero=True, style={'fit': fit} if fit else {}),
                  series=[Series('q', ['2024-01-01', '2024-02-01', '2024-03-01'], [583.3, 905.5, 1085.6], 'line')])
        return to_plotly(c).layout.yaxis.range[0]
    assert low('') == 0 and low('zero') == 0        # раздел просит «от нуля»
    assert low('auto') == 500 and low('data') == 500    # инженер выбрал другой режим: он сильнее настройки раздела

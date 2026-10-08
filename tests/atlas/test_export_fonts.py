"""Шрифты выгрузки: Times New Roman и Arial Narrow (на Linux — аналоги из atlas/fonts), размер шрифта."""
import re

import pytest

from atlas.engine.core import fonts
from atlas.engine.core.export import figure_bytes
from atlas.contract import Axis, Chart, Series
from atlas.render import chart_file


def chart():
    c = Chart('gdi-1', 'Скважина 1', Axis('Дебит'), Axis('Давление'))
    c.series.append(Series('a', [1, 2, 3], [3, 4, 6], 'line'))
    return c


def test_bundled_fonts_are_registered():
    fonts.register()
    for family in ('Liberation Serif', 'Atlas Sans Narrow'):
        assert fonts.installed(family)


@pytest.mark.parametrize('key,expected', [('times', ('Times New Roman', 'Liberation Serif')),
                                           ('arial_narrow', ('Arial Narrow', 'Atlas Sans Narrow'))])
def test_svg_uses_chosen_font(key, expected):
    svg, _, _ = chart_file(chart(), 'svg', 300, key, 11)
    assert any(name in svg.decode('utf-8') for name in expected)


def test_narrow_is_narrower_than_regular():
    from matplotlib import font_manager
    fonts.register()
    def width(family):
        f = font_manager.get_font(font_manager.findfont(family))
        f.set_size(10, 72)
        f.set_text('Давление скважины', 0)
        return f.get_width_height()[0]
    assert width('Atlas Sans Narrow') < width('Liberation Sans') * 0.9


def test_size_changes_output_and_validates():
    small = figure_bytes(chart_to_fig(), 'svg', 300, font='times', font_size=7)
    big = figure_bytes(chart_to_fig(), 'svg', 300, font='times', font_size=14)
    assert small != big
    with pytest.raises(ValueError):
        figure_bytes(chart_to_fig(), 'png', 300, font='comic')
    with pytest.raises(ValueError):
        figure_bytes(chart_to_fig(), 'png', 300, font='times', font_size=2)


def chart_to_fig():
    from atlas.render import to_plotly
    return to_plotly(chart())

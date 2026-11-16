"""Гистограмма фонда по группам (рис. 1.3-А): столбец на группу цветом группы, над ним число и доля; файл и экран одинаковы."""
import pandas as pd

from atlas import group_colors, render
from atlas.modules import an_charts


def _fund():
    return pd.DataFrame({'group': ['ГСП 1', 'ГСП 2', 'ГСП 10', 'Всего'], 'fund': [40, 50, 10, 100],
                         'working': [30, 40, 5, 75], 'percent': [75.0, 80.0, 50.0, 75.0]})


def test_one_bar_per_group_in_group_color_with_number_and_share(monkeypatch):
    group_colors.set_known_groups(['ГСП 1', 'ГСП 2', 'ГСП 10'])
    monkeypatch.setattr(group_colors, 'load_overrides', lambda: {'гсп 2': '#123456'})
    chart = an_charts.fund_chart('withdrawal', '2024', _fund())
    assert chart.title.startswith('Эксплуатационный фонд по группам (всего 100)')
    assert chart.x.categories == ['ГСП 1', 'ГСП 2', 'ГСП 10']
    assert [s.name for s in chart.series] == chart.x.categories and {s.stack for s in chart.series} == {'by-group'}
    assert [s.color for s in chart.series][1] == '#123456'                        # ручной цвет группы действует
    assert len({s.color for s in chart.series}) == 3
    assert [next(c for c in s.captions if c) for s in chart.series] == ['40\n(40 %)', '50\n(50 %)', '10\n(10 %)']
    assert 'работало за сезон: 30 (75.0 %)' in next(l for l in chart.series[0].labels if l)


def test_caption_text_is_drawn_above_each_bar_in_the_file():
    import matplotlib.figure as mf
    from atlas.engine.core.export import figure_bytes
    group_colors.set_known_groups(['ГСП 1', 'ГСП 2', 'ГСП 10'])
    drawn = []
    orig = mf.Figure.savefig
    mf.Figure.savefig = lambda self, *a, **k: (drawn.extend(t.get_text() for ax in self.axes for t in ax.texts), orig(self, *a, **k))[1]
    try:
        figure_bytes(render.to_plotly(an_charts.fund_chart('withdrawal', '2024', _fund())), 'png')
    finally:
        mf.Figure.savefig = orig
    assert {'40\n(40 %)', '50\n(50 %)', '10\n(10 %)'} <= set(drawn)


def test_axis_leaves_room_above_the_tallest_caption():
    from atlas.axis_auto import auto_chart
    group_colors.set_known_groups(['ГСП 1', 'ГСП 2', 'ГСП 10'])
    chart = auto_chart(an_charts.fund_chart('withdrawal', '2024', _fund()))
    assert chart.y.maximum > 50


def test_fund_split_by_group_uses_group_colors_and_natural_order():
    from atlas.modules.fund_hist import group_count_chart
    group_colors.set_known_groups(['ГСП 2', 'ГСП 10'])
    chart = group_count_chart('x', 'Т', pd.Series({'ГСП 2': 3, 'ГСП 10': 1}))
    assert chart.x.categories == ['ГСП 2', 'ГСП 10']
    assert [s.color for s in chart.series] == [group_colors.colors_for(['ГСП 2', 'ГСП 10'])[g] for g in chart.x.categories]

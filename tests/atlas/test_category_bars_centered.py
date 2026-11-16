"""Столбцы по категориям: засечка сезона посередине столбца, стопка рядов — один столбец на категорию (во всех графиках)."""
from atlas.contract import Axis, Chart, Series
from atlas.render import to_plotly


def _chart(chart_id: str) -> Chart:
    cats = ['Закачка 2023', 'Отбор 2023/24', 'Закачка 2024']
    c = Chart(chart_id, 'Тест', Axis('Сезон', scale='category', categories=cats), Axis('ГНТ', 'м'))
    c.series.append(Series('осень', cats, [1.0, None, 3.0], 'bar', stack='s'))
    c.series.append(Series('весна', cats, [None, 2.0, None], 'bar', stack='s'))
    return c


def test_stack_on_category_axis_is_one_column_for_any_chart():
    fig = to_plotly(_chart('fund-stack'))
    assert [t.meta.get('cat_stack') for t in fig.data] == ['s', 's']


def test_stacked_bars_are_centered_on_the_tick_in_the_file():
    from atlas.engine.core.export import figure_bytes
    from matplotlib import pyplot
    import matplotlib.figure as mf
    drawn = []
    orig = mf.Figure.savefig
    mf.Figure.savefig = lambda self, *a, **k: (drawn.extend(p for ax in self.axes for p in ax.patches), orig(self, *a, **k))[1]
    try:
        figure_bytes(to_plotly(_chart('fund-stack')), 'png')
    finally:
        mf.Figure.savefig = orig
    centers = sorted(round(p.get_x() + p.get_width() / 2, 3) for p in drawn if p.get_height() > 0 and p.get_width() < 1)
    assert centers == [0.0, 1.0, 2.0]


def test_value_labels_on_line_over_stacked_bars_do_not_break_the_file():
    """Подписи значений у Кг при столбцах-стопке ГНТ раньше падали: имя ``base`` (размер шрифта) затиралось словарём стопки."""
    from atlas.render import chart_file
    c = _chart('fund-stack')
    c.y2 = Axis('Кг', '%')
    c.series.append(Series('Кг', c.x.categories, [60.0, 65.0, 55.0], 'line', axis='y2', markers=True, look={'valueLabels': True}))
    data, name, _ = chart_file(c, 'png', 150)
    assert data[:4] == b'\x89PNG'

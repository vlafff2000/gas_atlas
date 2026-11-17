"""Таблица под графиком: центр ячейки категории совпадает с центром её столбца (файлы; экран — те же поля в ChartView.tsx)."""
import numpy as np
import matplotlib

matplotlib.use('Agg')
from matplotlib import pyplot as plt

from atlas import chart_special
from atlas.contract import Axis, Chart, ChartTable, Series


def _chart(n: int) -> Chart:
    cats = [f'Очень длинное название группы {i}' for i in range(n)]
    chart = Chart('t', 'Т', Axis('Группа', scale='category', categories=cats), Axis('Скважин', 'ед.'))
    for k, name in enumerate(('выполнено', 'не выполнено')):
        values = np.array([float(i + k + 1) for i in range(n)])
        chart.series.append(Series(name, cats, values, 'bar', stack='s', segments=[str(int(v)) for v in values]))
    chart.table = ChartTable([s.name for s in chart.series], cats, [[str(i) for i in range(n)]] * 2, swatches=False)
    return chart


def test_table_cells_are_under_their_bars():
    fig = chart_special._stack_figure(plt, _chart(5), {'выполнено': '#2a6f97', 'не выполнено': '#d1495b'}, lambda c: c, {})
    ax = fig.axes[0]
    fig.canvas.draw()
    table = ax.tables[0]
    low, high = ax.get_xlim()
    cells = sorted((c for (r, col), c in table.get_celld().items() if r == 1 and col >= 0), key=lambda c: c.get_x())
    centers = [(c.get_x() + c.get_width() / 2) * (high - low) + low for c in cells]
    assert np.allclose(centers, range(5), atol=1e-6), centers
    bars = sorted({round(p.get_x() + p.get_width() / 2, 6) for p in ax.patches if p.get_width() < 1})
    assert np.allclose(bars, range(5))

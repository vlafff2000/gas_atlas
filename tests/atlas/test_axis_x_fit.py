"""Числовая ось X подбирается той же функцией, что шкалы Y (atlas/axis_auto.py): экран и файл получают одни границы и шаг."""
from __future__ import annotations

import matplotlib.pyplot as plt

from atlas import axis_auto
from atlas.contract import Axis, Chart, Series
from atlas.engine.core import export
from atlas.render import to_plotly


def _chart(xs, kind='line', **x):
    return Chart('t-x', 'Тест', Axis('Сутки', **x), Axis('Расход'), series=[Series('a', xs, [float(i + 1) for i in range(len(xs))], kind)])


def _drawn(fig):
    """Пределы и деления оси X готового рисунка (по осям Matplotlib)."""
    seen, real = {}, plt.close

    def keep(f=None):
        if f is not None and getattr(f, 'axes', None):
            lo, hi = f.axes[0].get_xlim()
            seen['lim'] = (lo, hi)
            seen['ticks'] = [round(float(v), 6) for v in f.axes[0].get_xticks() if min(lo, hi) - 1e-9 <= v <= max(lo, hi) + 1e-9]
            f.canvas.draw()
            seen['labels'] = [t.get_text() for v, t in zip(f.axes[0].get_xticks(), f.axes[0].get_xticklabels()) if min(lo, hi) - 1e-9 <= v <= max(lo, hi) + 1e-9]
        return real(f)
    plt.close = keep
    try:
        export.figure_bytes(fig, 'png', 150, 160)
    finally:
        plt.close = real
    return seen


def test_x_axis_is_fitted_like_y():
    x = axis_auto.auto_chart(_chart([1, 50, 150])).x
    assert (x.minimum, x.maximum, x.step) == (0, 150, 25) and x.auto['why'] == 'near'
    x = axis_auto.auto_chart(_chart([583.3, 905.5, 1085.6])).x
    assert (x.minimum, x.maximum, x.step) == (500, 1100, 100) and x.auto['why'] == 'cut'
    x = axis_auto.auto_chart(_chart([100, 150, 200])).x
    assert (x.minimum, x.maximum) == (100, 200)        # у оси X запаса у среза нет: круглый край данных остаётся краем


def test_x_axis_with_bars_dates_or_categories_is_left_alone():
    for chart in (_chart([1, 2, 3], kind='bar'), _chart(['2024-01-01', '2024-02-01'], scale='time'), _chart(['а', 'б'], scale='category'),
                  _chart([1, 10, 100], scale='log')):
        x = axis_auto.auto_chart(chart).x
        assert (x.minimum, x.maximum, x.step, x.auto) == (None, None, None, None)


def test_manual_x_bounds_are_stronger():
    x = axis_auto.auto_chart(_chart([1, 50, 150], minimum=10.0)).x
    assert x.minimum == 10 and 'min' not in x.auto and x.maximum >= 150
    again = axis_auto.auto_chart(axis_auto.auto_chart(_chart([1, 50, 150]))).x        # повторный подбор ничего не меняет
    assert (again.minimum, again.maximum, again.step) == (0, 150, 25)


def test_file_x_axis_equals_screen_x_axis():
    chart = _chart([583.3, 905.5, 1085.6])
    shown = axis_auto.auto_chart(chart).x
    seen = _drawn(to_plotly(chart))
    assert seen['lim'] == (shown.minimum, shown.maximum)
    assert seen['ticks'] == [500, 600, 700, 800, 900, 1000, 1100]


def test_inverse_x_axis_with_bounds_stays_inverse_in_file():
    """Обратная ось X с границами (ручными или подобранными) в файле остаётся обратной."""
    lo, hi = _drawn(to_plotly(_chart([1, 50, 150], inverse=True, minimum=0.0, maximum=200.0)))['lim']
    assert (lo, hi) == (200, 0)
    lo, hi = _drawn(to_plotly(_chart([1, 50, 150], inverse=True)))['lim']
    assert (lo, hi) == (150, 0)


def test_fractional_x_step_keeps_its_decimals_in_file():
    """Шаг 2,5 по оси X: подписи 0; 2,5; 5 … — а не округлённые до целых 0; 2; 5; 8."""
    labels = _drawn(to_plotly(_chart([0.4, 5.0, 9.6], minimum=0.0, maximum=10.0, step=2.5)))['labels']
    assert [t.replace('.', ',') for t in labels] == ['0', '2,5', '5', '7,5', '10']      # десятичный знак в файлах — отдельная правка

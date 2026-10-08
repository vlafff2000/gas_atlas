from __future__ import annotations

import pytest

from app.modules.charts import separated_ranges
from atlas import chart_format


def test_pressure_axis_never_negative_and_ticks_equal():
    pressure = [0.5, 30, 60, 100]                       # большой размах и малые значения: шкала не должна уйти ниже нуля
    level = [200, 400, 900]
    (p0, p1), (top, bottom) = separated_ranges(pressure, level, 'below')
    assert p0 >= 0 and p1 >= 100
    assert bottom >= 900
    step_p, step_l = (p1 - p0) / 5, (bottom - top) / 5
    assert step_p > 0 and step_l > 0
    for v in (step_p, step_l):
        assert abs(v * 100 - round(v * 100)) < 1e-6      # круглые шаги


def test_negative_levels_allowed_when_data_negative():
    (_, _), (top, bottom) = separated_ranges([60, 100], [-70, -20, 20], 'above')
    assert top <= -70 and bottom >= 20


def test_parse_axes_numbers_and_dates():
    out = chart_format.parse_axes('{"y": {"min": "0", "max": "150", "major": "25", "minor": "5"},'
                                  ' "x": {"dates": true, "min": "01.07.2006", "major": {"unit": "year", "n": "2"}}}')
    assert out['y'] == {'min': 0.0, 'max': 150.0, 'major': 25.0, 'minor': 5.0, 'dates': False}
    assert out['x']['min'] == '2006-07-01' and out['x']['major'] == {'unit': 'year', 'n': 2}
    with pytest.raises(chart_format.FormatError):
        chart_format.parse_axes('{"y": {"min": 10, "max": 5}}')
    with pytest.raises(chart_format.FormatError):
        chart_format.parse_axes('{"x": {"dates": true, "min": "вчера"}}')


def test_manual_axes_in_export():
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    from app.core.export import figure_bytes
    dates = pd.date_range('2006-01-01', periods=40, freq='MS')
    fig = go.Figure([go.Scatter(x=dates, y=np.linspace(50, 100, 40), mode='lines', name='p'),
                     go.Scatter(x=dates, y=np.linspace(10, 20, 40), mode='lines', name='l', yaxis='y2')])
    fig.update_layout(xaxis={'type': 'date'}, yaxis2={'overlaying': 'y', 'side': 'right'})
    cfg = chart_format.configs({'fmt_response_axes': '{"y": {"min": 0, "max": 150, "major": 50, "minor": 10},'
                                ' "y2": {"min": 0, "max": 40, "major": 10},'
                                ' "x": {"dates": true, "min": "2006-01-01", "max": "2009-06-01",'
                                ' "major": {"unit": "year", "n": 1}, "minor": {"unit": "month", "n": 3}}}'})
    styled = chart_format.apply(fig, cfg['response'])
    assert figure_bytes(styled, 'png', 150)[:4] == b'\x89PNG'


def test_x_labels_fit_by_angle():
    """Чем круче наклон подписей оси X, тем больше их помещается; ручные деления X автоподбор не трогает."""
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    from app.core import export
    seen = {}
    original = export.x_labels

    def spy(ax, angle, *rest):
        original(ax, angle, *rest)
        ax.figure.canvas.draw()
        seen[angle] = len([t for t in ax.get_xticklabels() if t.get_text()])
    export.x_labels = spy
    try:
        dates = pd.date_range('2025-03-01', '2025-12-01', freq='3D')
        fig = go.Figure([go.Scatter(x=dates, y=np.arange(len(dates)), mode='lines', name='p')])
        fig.update_layout(xaxis={'type': 'date'})
        for angle in ('0', '45', '90'):
            export.figure_bytes(chart_format.apply(fig, chart_format.configs({'fmt_angle': angle})['*']), 'png', 150)
    finally:
        export.x_labels = original
    assert seen[0.0] <= seen[45.0] <= seen[90.0] and seen[0.0] < seen[90.0]

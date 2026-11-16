"""Ручные границы осей Y в выгрузке действуют и у графиков со стопкой столбцов (плитка ГНТ и Кг): 0–20 остаётся 0–20."""
import json

import pandas as pd

from atlas import chart_format, export_chart, render
from atlas.modules import gis_tiles


def _figure(axes: dict):
    labels = ['осень 2023', 'весна 2024', 'осень 2024']
    frame = pd.DataFrame({'season': labels, 'gnt': [14.0, 16.0, 18.0], 'kg': [14.0, 17.0, 20.0]})
    chart = gis_tiles.chart('18', 'нижняя', frame, labels, {})
    cfg = chart_format.for_module(chart_format.configs({'fmt_gis_tiles_axes': json.dumps(axes)}), 'gis_tiles')
    return export_chart.fit_figure(chart_format.apply(render.to_plotly(chart), cfg))


def test_hand_range_of_both_y_axes_is_kept_for_stacked_bars():
    fig = _figure({'y': {'min': 0, 'max': 20}, 'y2': {'min': 0, 'max': 20}})
    chart = export_chart.to_chart(fig, drawn_only=True)
    assert (chart.y.minimum, chart.y.maximum) == (0.0, 20.0)
    assert (chart.y2.minimum, chart.y2.maximum) == (0.0, 20.0)

"""Разряды «1 000» в файлах: подписи данных, цветовая шкала и подписи ячеек (общие функции export_style)."""
import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from atlas.chart_special import _g
from atlas.engine.core.export import point_labels, value_labels

NB = ' '


def _texts(ax):
    return [t.get_text() for t in ax.texts]


def test_point_labels_grouped():
    fig, ax = plt.subplots()
    point_labels(ax, [0, 1], np.array([12345.6, 7.0]), 'DejaVu Sans', 9, {'label_decimals': 1})
    assert f'12{NB}345,6' in _texts(ax)


def test_bar_labels_grouped():
    fig, ax = plt.subplots()
    bars = ax.bar([0], [1500000])
    value_labels(ax, bars, [1500000], 'DejaVu Sans', 9, {})
    assert f'1{NB}500{NB}000' in _texts(ax)


def test_cell_text_grouped_only_numbers():
    assert _g('12345,6') == f'12{NB}345,6'
    assert _g('нет данных') == 'нет данных'
    assert _g('') == ''

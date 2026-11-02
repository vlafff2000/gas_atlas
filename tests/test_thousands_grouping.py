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


def test_label_angle_in_files():
    fig, ax = plt.subplots()
    point_labels(ax, [0], np.array([5.0]), 'DejaVu Sans', 9, {'label_angle': 90})
    assert ax.texts[0].get_rotation() == 90
    bars = ax.bar([1], [3])
    value_labels(ax, bars, [3], 'DejaVu Sans', 9, {'label_angle': -45})
    assert ax.texts[-1].get_rotation() == 315 % 360 or ax.texts[-1].get_rotation() == -45


def test_label_angle_validated():
    from atlas.chart_style import clean_look
    assert clean_look({"valueLabels": True, "label_angle": 90}, 0).get('label_angle') == 90


def test_label_pick_in_files():
    fig, ax = plt.subplots()
    point_labels(ax, ['2024-01-01', '2024-01-02', '2024-01-03'], np.array([1.0, 2.0, 3.0]), 'DejaVu Sans', 9, {'label_pick': ['2024-01-02']})
    assert len(ax.texts) == 1
    bars = ax.bar([1, 2], [3, 4])
    value_labels(ax, bars, [3, 4], 'DejaVu Sans', 9, {'label_pick': ['2']}, keys=[1.0, 2.0])
    assert [t.get_text() for t in ax.texts[1:]] == ['4']
    point_labels(ax, [0], np.array([1.0]), 'DejaVu Sans', 9, {'label_pick': []})
    assert len(ax.texts) == 2


def test_label_pick_validated():
    from atlas.chart_style import clean_look
    assert clean_look({'valueLabels': True, 'label_pick': ['a', 5]}, 0)['label_pick'] == ['a', '5']
    assert clean_look({'label_pick': []}, 0)['label_pick'] == []

"""Сцена рисунка (atlas/engine/core/export_scene.py): имена и рамки элементов файла графика.

По сцене предпросмотр «как в файле» понимает, по чему щёлкнули, а проверки качества находят наложения. Поэтому важны три вещи:
файл от сцены не зависит, рамки стоят там, где элемент на самом деле нарисован, и имена постоянны."""
from __future__ import annotations

import io
import re

import numpy as np
import pytest
from PIL import Image

from atlas.contract import Axis, Chart, Series
from atlas.engine.core.export_scene import KINDS, Names
from atlas.render import chart_file

DATES = ['2024-01-01', '2024-02-01', '2024-03-01', '2024-04-01']


def _chart(**style):
    c = Chart('builder-1', 'Проба сцены', Axis('Дата', scale='time'), Axis('Расход, тыс. м³/сут', from_zero=True), y2=Axis('Давление, кгс/см²'))
    c.style = style
    c.series.append(Series('расход', DATES, [3.0, 47.0, 120.0, 80.0], 'bar'))
    c.series.append(Series('пласт', DATES, [31.0, 50.0, 97.0, 88.0], 'line', axis='y2', look={'valueLabels': True}))
    c.series.append(Series('пласт', DATES, [35.0, 55.0, 90.0, 80.0], 'line', axis='y2'))
    return c


def _stack():
    """Стопка с числами в сегментах: её рисует отдельный рисовальщик (atlas/chart_special.py), файл обрезан по содержимому."""
    c = Chart('t-s', 'Стопка с подписями', Axis('Скважина', scale='category'), Axis('Доля, %'))
    c.series.append(Series('а', ['1', '2', '3'], [10.0, 20.0, 30.0], 'bar', stack='s', segments=['10', '20', '30']))
    c.series.append(Series('б', ['1', '2', '3'], [5.0, 15.0, 25.0], 'bar', stack='s', segments=['5', '15', '25']))
    return c


def _scene(chart, fmt='png'):
    scene: list = []
    data = chart_file(chart, fmt, 150, scene=scene)[0]
    return data, {e['id']: e for e in scene}


def _dark(png):
    return np.asarray(Image.open(io.BytesIO(png)).convert('L')) < 200


def test_scene_names_what_is_drawn():
    notes = [{'kind': 'hline', 'value': '60', 'text': 'уровень 60'}, {'kind': 'text', 'x': '2024-02-01', 'y': '100', 'text': 'заметка'}]
    _, scene = _scene(_chart(subtitle='подзаголовок', annotations=notes))
    assert {'plot', 'title', 'subtitle', 'legend', 'axis:x', 'axis:y', 'axis:y2', 'axis-title:x', 'axis-title:y', 'axis-title:y2',
            'series:расход', 'series:пласт', 'annotation:1', 'annotation-text:1', 'annotation-text:2'} <= set(scene)
    assert 'annotation:2' not in scene      # у подписи линии нет
    assert all(e['kind'] in KINDS for e in scene.values())
    assert scene['title']['text'] == 'Проба сцены' and scene['subtitle']['text'] == 'подзаголовок'
    assert scene['annotation-text:1']['text'] == 'уровень 60'
    assert scene['series:пласт']['axis'] == 'y2' and scene['series:расход']['axis'] == 'y'
    assert scene['axis-title:y2']['text'] == 'Давление, кгс/см²'


def test_same_series_name_twice_gets_a_number():
    _, scene = _scene(_chart())
    assert {'series:пласт', 'series:пласт#2', 'legend:пласт', 'legend:пласт#2'} <= set(scene)
    assert scene['series:пласт']['box'] != scene['series:пласт#2']['box']
    names = Names()
    assert [names.series('а'), names.series('а'), names.series('б'), names.series('а')] == ['а', 'а#2', 'б', 'а#3']


def test_value_labels_know_their_series_and_point():
    _, scene = _scene(_chart())
    labels = [e for e in scene.values() if e['kind'] == 'label']
    assert [e['id'] for e in labels] == ['label:пласт:' + d for d in DATES]
    assert [e['text'] for e in labels] == ['31', '50', '97', '88']
    assert all(e['series'] == 'пласт' for e in labels) and [e['point'] for e in labels] == DATES
    line = scene['series:пласт']['box']
    for e in labels:        # подпись стоит у своей точки: внутри рамки ряда с запасом на высоту текста
        x0, y0, x1, y1 = e['box']
        assert line[0] - 0.03 <= (x0 + x1) / 2 <= line[2] + 0.03 and line[1] - 0.05 <= (y0 + y1) / 2 <= line[3] + 0.05


@pytest.mark.parametrize('make', [_chart, _stack])
def test_file_does_not_depend_on_scene(make):
    """Сцена собирается после сохранения: с ней и без неё файл один и тот же."""
    assert chart_file(make(), 'png', 150)[0] == _scene(make())[0]
    stamp = re.compile(rb'/CreationDate \(.*?\)')
    assert stamp.sub(b'', chart_file(make(), 'pdf', 150)[0]) == stamp.sub(b'', _scene(make(), 'pdf')[0])


@pytest.mark.parametrize('make', [_chart, _stack])
def test_boxes_are_fractions_of_the_saved_image(make):
    """Рамки — в долях сохранённого рисунка (у стопки он обрезан по содержимому): заголовок и оси стоят там, где нарисованы."""
    png, scene = _scene(make())
    for e in scene.values():
        x0, y0, x1, y1 = e['box']
        assert -0.005 <= x0 <= x1 <= 1.005 and -0.005 <= y0 <= y1 <= 1.005, e
        assert all(type(v) is float for v in e['box'])
    dark = _dark(png)
    h, w = dark.shape
    x0, y0, x1, y1 = scene['title']['box']
    band = dark[round(y0 * h):round(y1 * h), max(0, round(x0 * w) - 20):round(x1 * w) + 20]
    cols = np.flatnonzero(band.any(axis=0)) + max(0, round(x0 * w) - 20)
    assert abs(cols[0] - x0 * w) <= 5 and abs(cols[-1] - x1 * w) <= 5      # буквы заголовка — от левого края рамки до правого
    px0, _, px1, py1 = scene['plot']['box']
    rows = dark[round(py1 * h) - 3:round(py1 * h) + 4, round(px0 * w) + 2:round(px1 * w) - 2]
    assert rows.mean(axis=1).max() > 0.9      # нижний край области построения — линия оси X


def test_axis_box_holds_only_ticks_of_the_scale():
    """Matplotlib держит подписи делений и за пределами шкалы; в рамку оси идут только нарисованные."""
    _, scene = _scene(_chart())
    _, top, _, bottom = scene['plot']['box']
    for name in ('axis:y', 'axis:y2'):
        _, y0, _, y1 = scene[name]['box']
        assert top - 0.03 <= y0 <= top + 0.03 and bottom - 0.03 <= y1 <= bottom + 0.03      # от нижнего деления до верхнего ± высота числа
    x0, _, x1, _ = scene['axis:x']['box']
    assert scene['plot']['box'][0] - 0.05 <= x0 and x1 <= scene['plot']['box'][2] + 0.05


@pytest.mark.parametrize('make', [_chart, _stack])
def test_scene_is_the_same_in_every_format(make):
    scenes = {fmt: _scene(make(), fmt)[1] for fmt in ('png', 'svg', 'pdf')}
    assert set(scenes['png']) == set(scenes['svg']) == set(scenes['pdf'])
    for fmt in ('svg', 'pdf'):
        for key, e in scenes['png'].items():
            assert np.allclose(e['box'], scenes[fmt][key]['box'], atol=0.003), (fmt, key)


def test_special_chart_scene_has_common_elements():
    _, scene = _scene(_stack())
    assert {'plot', 'title', 'axis:x', 'axis:y', 'axis-title:x', 'axis-title:y', 'legend', 'legend:а', 'legend:б'} <= set(scene)
    legend, plot = scene['legend']['box'], scene['plot']['box']
    assert legend[0] >= plot[2]      # легенда стопки — справа от области построения
    for item in ('legend:а', 'legend:б'):
        x0, y0, x1, y1 = scene[item]['box']
        assert legend[0] <= x0 and x1 <= legend[2] and legend[1] <= y0 and y1 <= legend[3]


def test_no_scene_requested_no_work():
    """Без ``scene`` рисовальщик ничего не собирает: обычная выгрузка идёт прежним путём."""
    data, name, kind = chart_file(_chart(), 'svg', 150)
    assert data.lstrip().startswith(b'<?xml') and name.endswith('.svg') and kind == 'image/svg+xml'

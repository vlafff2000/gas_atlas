"""Ручное положение элементов графика (раздел ``elements`` модели оформления): сдвиг в долях рисунка и «спрятать подпись».

Последнее слово за инженером: он двигает заголовок, легенду, название оси, подпись точки, текст аннотации; остальное остаётся
на месте, положение одинаково в PNG, SVG и PDF, а сдвиг, который применить нельзя, не теряется молча."""
from __future__ import annotations

import pytest

from atlas import export_any
from atlas.chart_style import apply_format, clean_format, clean_store, merge_formats
from atlas.contract import Axis, Chart, ParamError, Series
from atlas.engine.core.export_scene import MOVABLE
from atlas.render import chart_file

DATES = ['2024-01-01', '2024-02-01', '2024-03-01', '2024-04-01']
MOVES = {'title': (0.1, 0.02), 'subtitle': (0.3, 0.0), 'legend': (-0.2, -0.3), 'axis-title:x': (0.1, -0.05), 'axis-title:y': (0.02, 0.1),
         'axis-title:y2': (0.0, -0.1), 'label:пласт:2024-03-01': (0.05, -0.05), 'annotation-text:1': (-0.1, 0.05), 'annotation-text:2': (0.05, 0.05)}


def _chart():
    c = Chart('builder-1', 'Проба сцены', Axis('Дата', scale='time'), Axis('Расход, тыс. м³/сут', from_zero=True), y2=Axis('Давление, кгс/см²'))
    c.style = {'subtitle': 'подзаголовок', 'annotations': [{'kind': 'hline', 'value': '60', 'text': 'уровень 60'},
                                                           {'kind': 'text', 'x': '2024-02-01', 'y': '100', 'text': 'заметка'}]}
    c.series.append(Series('расход', DATES, [3.0, 47.0, 120.0, 80.0], 'bar'))
    c.series.append(Series('пласт', DATES, [31.0, 50.0, 97.0, 88.0], 'line', axis='y2', look={'valueLabels': True}))
    return c


def _stack():
    c = Chart('t-s', 'Стопка с подписями', Axis('Скважина', scale='category'), Axis('Доля, %'))
    c.series.append(Series('а', ['1', '2', '3'], [10.0, 20.0, 30.0], 'bar', stack='s', segments=['10', '20', '30']))
    c.series.append(Series('б', ['1', '2', '3'], [5.0, 15.0, 25.0], 'bar', stack='s', segments=['5', '15', '25']))
    return c


def _doc(moves):
    return clean_format({'elements': {key: {'dx': dx, 'dy': dy} for key, (dx, dy) in moves.items()}})


def _scene(chart, fmt='png'):
    scene: list = []
    data = chart_file(chart, fmt, 150, scene=scene)[0]
    return data, {e['id']: e for e in scene}


def _moved(base, now, key, dx, dy, tol=0.002):
    a, b = base[key]['box'], now[key]['box']
    return max(abs(b[0] - a[0] - dx), abs(b[2] - a[2] - dx), abs(b[1] - a[1] - dy), abs(b[3] - a[3] - dy)) <= tol


# ---- модель ----

def test_model_keeps_shift_and_drops_what_cannot_move():
    doc = clean_format({'elements': {'title': {'dx': '0,1', 'dy': -0.05}, 'legend': {'dx': 0, 'dy': 0}, 'series:пласт': {'dx': 0.1},
                                     'plot': {'dy': 0.1}, 'label:пласт:2024-03-01': {'hide': True}, 'title2': {'dx': 0.1},
                                     'annotation-text:1': {'hide': True, 'dx': 0.02}}})
    assert doc == {'elements': {'title': {'dx': 0.1, 'dy': -0.05}, 'label:пласт:2024-03-01': {'hide': True}, 'annotation-text:1': {'dx': 0.02}}}
    assert clean_format({'elements': {}}) == {} and clean_format({'chart': {'title_size': 14}}) == {'chart': {'title_size': 14.0}}
    with pytest.raises(ParamError, match='Элемент «title», сдвиг вправо'):
        clean_format({'elements': {'title': {'dx': 3}}})
    with pytest.raises(ParamError):
        clean_format({'elements': ['title']})


def test_levels_merge_by_element_and_field():
    low, high = _doc({'title': (0.1, 0.1), 'legend': (0.2, 0.0)}), clean_format({'elements': {'title': {'dx': 0.3}}})
    assert merge_formats(low, high)['elements'] == {'title': {'dx': 0.3, 'dy': 0.1}, 'legend': {'dx': 0.2}}
    chart = apply_format(apply_format(_chart(), low), high)
    assert chart.style['elements'] == {'title': {'dx': 0.3, 'dy': 0.1}, 'legend': {'dx': 0.2}}
    assert chart.style['subtitle'] == 'подзаголовок'      # остальное оформление графика на месте


def test_position_belongs_to_one_chart_only():
    """Тема, тип и шаблон действуют на много графиков: положение элементов в них не хранится, у «только этого графика» — хранится."""
    doc = {'chart': {'title_size': 14}, 'elements': {'title': {'dx': 0.1}}}
    store = clean_store({'theme': doc, 'types': {'gdi': doc}, 'charts': {'gdi::ipr': doc}, 'templates': {'отчёт': doc}})
    assert store['charts']['gdi::ipr']['elements'] == {'title': {'dx': 0.1}}
    for shared in (store['theme'], store['types']['gdi'], store['templates']['отчёт']):
        assert shared == {'chart': {'title_size': 14.0}}
    assert clean_store({'theme': {'chart': {'title_size': 14}}}) == {'theme': {'chart': {'title_size': 14.0}}}      # старый проект читается как раньше


# ---- файл ----

@pytest.mark.parametrize('fmt', ['png', 'svg', 'pdf'])
def test_moved_elements_stand_where_asked_and_the_rest_stays(fmt):
    _, base = _scene(_chart(), fmt)
    _, now = _scene(apply_format(_chart(), _doc(MOVES)), fmt)
    assert set(now) == set(base)
    for key in base:
        dx, dy = MOVES.get(key, MOVES['legend'] if key.startswith('legend:') else (0.0, 0.0))      # пункты легенды едут вместе с ней
        assert _moved(base, now, key, dx, dy), key


def test_every_movable_element_of_the_scene_can_be_moved():
    """Имена сцены и имена, по которым рисовальщик ищет элемент для сдвига, — одни и те же."""
    _, base = _scene(_chart())
    movable = [key for key, e in base.items() if e['kind'] in MOVABLE]
    assert {e['kind'] for e in base.values()} >= set(MOVABLE)
    _, now = _scene(apply_format(_chart(), _doc({key: (0.01, 0.01) for key in movable})))
    assert not [e for e in now.values() if e.get('missing')]
    assert all(_moved(base, now, key, 0.01, 0.01) for key in movable)


def test_title_can_be_put_inside_the_plot():
    """Matplotlib сам держит заголовок над областью построения; ручное положение сильнее."""
    chart = _chart()
    chart.style = {}
    _, base = _scene(chart)
    _, now = _scene(apply_format(chart, _doc({'title': (0.3, 0.2)})))
    assert _moved(base, now, 'title', 0.3, 0.2)
    assert now['plot']['box'][1] < now['title']['box'][1] and now['plot']['box'] == base['plot']['box']


def test_no_elements_no_change():
    plain = chart_file(_chart(), 'png', 150)[0]
    assert chart_file(apply_format(_chart(), clean_format({'elements': {'title': {'dx': 0}}})), 'png', 150)[0] == plain
    assert chart_file(apply_format(_chart(), _doc({'title': (0.1, 0.0)})), 'png', 150)[0] != plain


def test_hidden_label_stays_in_scene_so_it_can_be_returned():
    key = 'label:пласт:2024-01-01'
    plain, base = _scene(_chart())
    data, now = _scene(apply_format(_chart(), clean_format({'elements': {key: {'hide': True}}})))
    assert data != plain
    assert now[key].get('hidden') is True and now[key]['box'] == base[key]['box'] and now[key]['text'] == '31'
    assert not any(e.get('hidden') for k, e in now.items() if k != key)


def test_shift_of_absent_element_is_reported_not_lost():
    doc = _doc({'title': (0.1, 0.0), 'label:пласт:2031-01-01': (0.1, 0.1), 'axis-title:y4': (0.0, 0.1)})
    _, base = _scene(_chart())
    _, now = _scene(apply_format(_chart(), doc))
    assert [k for k, e in now.items() if e.get('missing')] == ['label:пласт:2031-01-01', 'axis-title:y4']
    assert now['label:пласт:2031-01-01'] == {'id': 'label:пласт:2031-01-01', 'kind': 'label', 'missing': True}
    assert _moved(base, now, 'title', 0.1, 0.0)      # остальное применилось
    *_, notes = export_any.export(_chart(), {'format': 'png', 'dpi': 150, 'doc': doc})
    assert any('Ручное положение не применено' in n and '«label:пласт:2031-01-01»' in n and '«axis-title:y4»' in n for n in notes)
    *_, notes = export_any.export(_chart(), {'format': 'png', 'dpi': 150, 'doc': _doc({'title': (0.1, 0.0)})})
    assert not any('Ручное положение' in n for n in notes)


def test_any_chart_export_applies_position_from_its_format():
    plain = export_any.export(_chart(), {'format': 'png', 'dpi': 150})[0]
    moved = export_any.export(_chart(), {'format': 'png', 'dpi': 150, 'doc': _doc({'legend': (0.0, -0.4)})})[0]
    assert plain != moved


@pytest.mark.parametrize('fmt', ['png', 'pdf'])
def test_special_chart_moves_too(fmt):
    """У стопки файл обрезается по содержимому: сдвиг считается в долях обрезанного рисунка (того, что видит инженер)."""
    moves = {'title': (0.05, 0.0), 'axis-title:y': (0.0, 0.1)}      # такие сдвиги не меняют обрезку
    _, base = _scene(_stack(), fmt)
    _, now = _scene(apply_format(_stack(), _doc(moves)), fmt)
    for key in base:
        assert _moved(base, now, key, *moves.get(key, (0.0, 0.0))), key

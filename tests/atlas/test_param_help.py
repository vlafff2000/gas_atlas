"""Кнопка «?» у расчётных параметров: формула и пример приходят в описании модуля; формулы сходятся с расчётом."""
import numpy as np
from starlette.testclient import TestClient

from atlas.engine.modules.gdi import free_flow
from atlas.api import create_app
from atlas.projects import Projects


def test_formula_and_example_are_in_module_specs(tmp_path):
    specs = TestClient(create_app(Projects(tmp_path))).get('/api/modules').json()
    helped = {(s['id'], p['name']) for s in specs for p in s['params'] if p['formula']}
    assert {('gdi', 'threshold'), ('gdi', 'outlier_threshold'), ('wells', 'threshold'), ('wells', 'dp2'),
            ('pressure', 'threshold'), ('pressure', 'match_good'), ('quality', 'jump'), ('gdi_trend', 'change')} <= helped
    assert all(p['example'] for s in specs for p in s['params'] if p['formula'])


def test_example_of_dp2_formula_is_correct():
    a, b, dp2 = 0.7, 0.012, 500
    q = (-a + np.sqrt(a * a + 4 * b * dp2)) / (2 * b)
    assert round(q) == 177
    assert abs(q * a + b * q * q - dp2) < 1e-9
    assert free_flow(a, b, np.sqrt(dp2)) is not None

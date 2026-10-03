"""Большое демо: формат как после импорта 5.8, точные объёмы, повторяемость. Здесь — малые объёмы."""
import pandas as pd
import pytest

from app.core import exclusions
from app.core.demo import demo_frames
from app.core.demo_large import create_large_demo, large_demo_frames
from app.core.storage import Store
from app.modules import gdi, pressure_match, production

SIZES = dict(production=20000, gdi=3000, response=4000, pressure_match=6000)


@pytest.fixture(scope='module')
def frames():
    return large_demo_frames(**SIZES)


def test_exact_sizes_and_same_columns_as_small_demo(frames):
    assert {k: len(v) for k, v in frames.items()} == SIZES
    small = demo_frames()
    for name in ('production', 'gdi', 'response'):
        assert list(frames[name].columns) == list(small[name].columns)
        for col in small[name]:
            assert frames[name][col].dtype.kind == small[name][col].dtype.kind, (name, col)
    assert {'object', 'scenario', 'well', 'date', 'fact', 'model', 'fond'} <= set(frames['pressure_match'])


def test_repeatable_and_seeded(frames):
    again = large_demo_frames(**SIZES)
    for name in frames:
        pd.testing.assert_frame_equal(frames[name], again[name])
    other = large_demo_frames(seed=1, **SIZES)
    assert not other['production'].q.equals(frames['production'].q)


def test_zero_skips_dataset():
    out = large_demo_frames(production=1000, gdi=0, response=0, pressure_match=0)
    assert list(out) == ['production']
    with pytest.raises(ValueError):
        large_demo_frames(production=0)


def test_legacy_calculations_accept_data(frames):
    p = production.periods(frames['production'])
    assert set(p.kind) == {'withdrawal', 'injection'} and p.period.notna().all()
    sample = frames['gdi'][frames['gdi'].well.isin(frames['gdi'].well.unique()[:5])]
    studies = gdi.analyze(sample)
    assert len(studies) == sample.groupby(gdi.KEYS).ngroups and studies.a.notna().all()
    d, stats = pressure_match.filter_data(frames['pressure_match'], {'season_start': 11, 'season_end': 4}, {})
    assert stats['used'] > 0 and stats['missing'] > 0 and len(d) == stats['used']
    assert len(exclusions.identify_frames(frames)['gdi']) == SIZES['gdi']


def test_saved_project_opens_in_58(tmp_path):
    store = Store(tmp_path)
    pid = create_large_demo(store, production=5000, gdi=600, response=900, pressure_match=1200)
    manifest, data = store.load(pid)
    assert manifest['demo'] and manifest['tables'] == {'production': 5000, 'gdi': 600, 'response': 900,
                                                       'pressure_match': 1200}
    assert manifest['settings']['working_horizons'] == ['Окский']
    assert len(data['production']) == 5000

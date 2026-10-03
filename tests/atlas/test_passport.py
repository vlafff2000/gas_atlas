"""Паритет с 5.8: «Паспорт скважины» — тот же выбор, тот же reporting.build + passport_pdf, общий комментарий."""
import re

import pytest
from starlette.testclient import TestClient

from _wells_data import make_project
from app.core import reporting
from app.core.config import DEFAULT_SETTINGS, MODULES, ordered
from app.core.documents import passport_pdf
from app.core.performance import Frames
from app.modules import production
from atlas.api import create_app
from atlas.projects import Projects

WELL = '31'


@pytest.fixture(scope='module')
def env(tmp_path_factory):
    projects = Projects(tmp_path_factory.mktemp('passport'))
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    return client, pid, projects


def legacy_page(projects, pid):
    """Что видит страница 5.8 «Паспорт скважины» (app/ui/extras.render_extra)."""
    m = projects.manifest(pid)
    settings = {**DEFAULT_SETTINGS, **m['settings']}
    cache = projects._cache(pid, m)
    return Frames(cache, settings), Frames(cache), settings, m


def pages(pdf: bytes) -> int:
    return len(re.findall(rb'/Type\s*/Page[^s]', pdf))


def test_info_matches_58(env):
    client, pid, projects = env
    frames, raw, settings, _ = legacy_page(projects, pid)
    info = client.get(f'/api/projects/{pid}/passport').json()
    assert info['wells'] == ordered({w for d in raw.values() if 'well' in d for w in d.well.unique()})
    assert [s['value'] for s in info['sections']] == [x for x in frames if x != 'object_pressure']
    assert [s['label'] for s in info['sections']] == [MODULES[x] for x in frames if x != 'object_pressure']
    d = production.periods(frames['production'], settings['season_start'], settings['season_end'])
    for kind in ('withdrawal', 'injection'):
        available = ordered(d.loc[d.kind.eq(kind), 'period'])
        assert info['periods'][kind]['options'] == available
        assert info['periods'][kind]['default'] == available[-2:]
    assert client.get(f'/api/projects/{pid}/passport?well=нет').status_code == 400


def test_comment_saved_like_58(env):
    client, pid, projects = env
    revision = projects.manifest(pid)['revision']
    r = client.post(f'/api/projects/{pid}/passport/comment', json={'well': WELL, 'comment': 'Проверить шлейф\nи забой'})
    assert r.status_code == 200, r.text
    m = projects.manifest(pid)
    assert m['revision'] == revision + 1
    assert m['settings']['well_comments'] == {WELL: 'Проверить шлейф\nи забой'}
    assert projects.store.history(pid)['Действие'].iloc[0] == 'Комментарий инженера'
    assert client.get(f'/api/projects/{pid}/passport?well={WELL}').json()['comment'] == 'Проверить шлейф\nи забой'
    assert client.get(f'/api/projects/{pid}/passport?well=45').json()['comment'] == ''
    stale = client.post(f'/api/projects/{pid}/passport/comment', json={'well': WELL, 'comment': 'x', 'revision': revision})
    assert stale.status_code == 409


def test_pdf_matches_58(env):
    client, pid, projects = env
    frames, raw, settings, m = legacy_page(projects, pid)
    sections = ['production', 'gdi', 'operations', 'bottom', 'construction']
    periods = {'withdrawal': ['2025-2026'], 'injection': []}
    before = len(projects.store.exports(pid))
    r = client.post(f'/api/projects/{pid}/passport/pdf', json={'well': WELL, 'sections': sections, 'periods': periods,
                                                                'comment': 'Комментарий для PDF'})
    assert r.status_code == 200, r.text
    assert r.headers['content-type'] == 'application/pdf' and r.content.startswith(b'%PDF')
    exports = projects.store.exports(pid)
    assert len(exports) == before + 1 and exports[0].read_bytes() == r.content
    assert 'Паспорт_скважины_31.pdf' in exports[0].name
    # Тот же словарь параметров и тот же PDF, что собирает страница 5.8
    options = {'modules': sections, 'wells': [WELL], 'apply_exclusions': True, 'style': settings.get('chart_style', {}),
               'gdi': {'wells': [WELL], 'n': 3, 'show_excluded': True},
               'response': {'wells': [WELL], 'view': 'combined', 'split': 'well'},
               'production': {'wells': [WELL], 'periods': periods, 'view': 'mixed', 'split': 'well'}}
    import json
    assert json.loads(exports[0].with_name(exports[0].name + '.json').read_text(encoding='utf8')) == options
    figures, tables = reporting.build(frames, projects.data(pid).mapping, settings, options, raw)
    expected = passport_pdf(m['name'], WELL, figures, tables, settings, 'Комментарий для PDF')
    assert pages(r.content) == pages(expected) > len(figures) > 0


def test_pdf_validation(env):
    client, pid, projects = env
    url = f'/api/projects/{pid}/passport/pdf'
    assert client.post(url, json={'well': WELL, 'sections': []}).status_code == 400
    assert client.post(url, json={'well': WELL, 'sections': ['object_pressure']}).status_code == 400
    assert client.post(url, json={'well': WELL, 'sections': ['gdi'], 'periods': {'withdrawal': ['1900']}}).status_code == 400
    assert client.post(url, json={'well': 'нет', 'sections': ['gdi']}).status_code == 400

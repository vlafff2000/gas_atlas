"""Паритет с 5.8: «Паспорт скважины» — тот же выбор, тот же reporting.build + passport_pdf, общий комментарий."""
import re

import pytest
from starlette.testclient import TestClient

from _wells_data import make_project
from atlas.engine.core import reporting
from atlas.engine.core.config import DEFAULT_SETTINGS, MODULES, ordered
from atlas.engine.core.documents import passport_pdf
from atlas.engine.core.performance import Frames
from atlas.engine.modules import production
from atlas.api import create_app
from atlas.api_passport import PASSPORT_SECTIONS, Passport
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
    expected = [x for x in frames if x in PASSPORT_SECTIONS and 'well' in frames[x].columns]
    assert [s['value'] for s in info['sections']] == expected
    assert [s['label'] for s in info['sections']] == [MODULES[x] for x in expected]
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


def test_sections_skip_sets_without_well_column(env, monkeypatch):
    """Журнал 30.10: PDF падал на наборе без колонки «скважина» (AttributeError ... 'well'); такие наборы в паспорт не входят."""
    import pandas as pd
    _, pid, projects = env
    passport = Passport(projects, pid)
    passport.frames = {'gdi': pd.DataFrame({'well': ['31']}), 'annulus': pd.DataFrame({'date': [], 'pressure': []}),
                       'elpro': pd.DataFrame({'well': ['31']})}
    assert passport.sections() == ['gdi']
    assert 'annulus' not in passport.sections() and 'elpro' not in passport.sections()


def test_info_filter_and_group_pdf(env):
    client, pid, projects = env
    url = f'/api/projects/{pid}/passport'
    full = client.get(url).json()
    assert full['shown'] == full['wells'] and set(full['groups']) == set(full['wells'])
    group = full['groups'][WELL]
    some = client.get(url, params={'filter': '{"groups": ["%s"]}' % group}).json()
    assert WELL in some['shown'] and set(some['shown']) <= set(full['wells']) and some['well'] in some['shown']
    two = [w for w in full['wells'] if w != WELL][:1] + [WELL]
    r = client.post(url + '/pdf', json={'wells': two, 'sections': ['gdi'], 'card': True})
    assert r.status_code == 200, r.text
    import io, zipfile
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 2 and all(n.endswith('.pdf') for n in names)
    assert client.post(url + '/pdf', json={'wells': [WELL, 'нет'], 'sections': ['gdi']}).status_code == 400
    single = client.post(url + '/pdf', json={'wells': [WELL], 'sections': ['gdi']})
    assert single.headers['content-type'] == 'application/pdf'


def test_card_has_diagrams_daily_and_chronology(env):
    client, pid, _ = env
    card = client.get(f'/api/projects/{pid}/passport/card?well={WELL}').json()
    ends = [pd_date(r['end']) for r in card['seasons']]
    assert ends == sorted(ends, reverse=True)                        # свежий сезон сверху, виды чередуются по времени
    assert [r['kind'] for r in card['seasons']][:2] == ['withdrawal', 'injection']
    assert card['gdi_diagrams'] and card['gdi_diagrams'][0]['points']
    assert len(card['daily']['withdrawal']['date']) == len(card['daily']['withdrawal']['volume']) > 0


def pd_date(text):
    import datetime
    return datetime.datetime.strptime(text, '%d.%m.%Y')

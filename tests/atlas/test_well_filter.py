"""Фильтр скважин проекта: сквозной для всех модулей (группы и скважины пересекаются, логика «И»)."""
from atlas import well_filter
from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.engine.core import exclusions
from atlas.engine.core.demo import well_demo_frames
from atlas.modules.gdi import GdiModule
from atlas.modules.gdi_trend import GdiTrendModule

GDI = DatasetKind.GDI


def _data(settings):
    gdi = exclusions.identify(well_demo_frames()['gdi'].copy(), 'gdi')
    wells = sorted(gdi.well.astype(str).unique(), key=lambda w: int(w) if w.isdigit() else w)
    data = Data({GDI: gdi}, {GDI: gdi}, {})
    data.mapping = {w: {'group': 'ГСП 1' if i < 2 else 'ГСП 2'} for i, w in enumerate(wells)}
    data.wells = wells
    data.settings = settings
    return data


def test_setting_is_validated_and_normalised():
    assert well_filter.valid(None) and well_filter.valid({'groups': ['ГСП 1'], 'wells': []})
    assert not well_filter.valid({'groups': 'ГСП 1'}) and not well_filter.valid({'объект': []})
    assert well_filter.clean({'groups': [], 'wells': []}) is None
    assert well_filter.clean({'groups': ['ГСП 1', 'ГСП 1'], 'wells': ['3']}) == {'groups': ['ГСП 1'], 'wells': ['3']}


def test_no_filter_returns_the_same_data():
    data = _data({})
    assert well_filter.apply(data) is data
    assert well_filter.status(data) == {'groups': [], 'wells': [], 'total': len(data.wells), 'shown': len(data.wells), 'hidden': 0}


def test_groups_and_wells_intersect_for_every_module():
    first, last = _data({}).wells[0], _data({}).wells[-1]    # last — из другой группы
    data = _data({'well_filter': {'groups': ['ГСП 1'], 'wells': [first, last]}})
    scoped = well_filter.apply(data)
    assert scoped.wells == [first]
    assert set(scoped[GDI].well.astype(str)) == {first}
    assert well_filter.status(data) == {'groups': ['ГСП 1'], 'wells': [first, last], 'total': len(data.wells), 'shown': 1, 'hidden': 1}
    # Модули ГДИ берут уже отобранные скважины, без собственного фильтра групп
    result = GdiModule().run(scoped, GdiModule().spec.coerce({'wells': []}))
    assert len(result.charts) == 1
    assert GdiTrendModule().run(scoped, GdiTrendModule().spec.coerce({'wells': []})) is not None


def test_group_filter_without_wells_keeps_the_group():
    data = _data({'well_filter': {'groups': ['ГСП 2'], 'wells': []}})
    scoped = well_filter.apply(data)
    assert scoped.wells == data.wells[2:]
    assert set(scoped[GDI].well.astype(str)) <= set(data.wells[2:])


def test_filter_is_a_project_setting_and_shows_status(tmp_path, monkeypatch):
    import atlas.api_projects as api_projects
    from starlette.testclient import TestClient
    from atlas.api import create_app
    from atlas.engine.core.storage import Store
    from atlas.projects import Projects

    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    client = TestClient(create_app(Projects(tmp_path / 'storage')))
    pid = client.post('/api/projects/demo').json()['id']
    groups = client.get(f'/api/projects/{pid}/group-list').json()['groups']
    total = client.get(f'/api/projects/{pid}/well-filter').json()['total']
    r = client.patch(f'/api/projects/{pid}/settings', json={'values': {'well_filter': {'groups': groups[:1], 'wells': []}}})
    assert r.status_code == 200, r.text
    assert r.json()['settings']['well_filter'] == {'groups': groups[:1], 'wells': []}
    status = client.get(f'/api/projects/{pid}/well-filter').json()
    assert 0 < status['shown'] < total and status['groups'] == groups[:1]
    assert Store(tmp_path / 'storage').history(pid).iloc[0]['Действие'] == 'Фильтр скважин'
    r = client.patch(f'/api/projects/{pid}/settings', json={'values': {'well_filter': None}})
    assert r.json()['settings']['well_filter'] is None
    assert client.get(f'/api/projects/{pid}/well-filter').json()['shown'] == total
    bad = client.patch(f'/api/projects/{pid}/settings', json={'values': {'well_filter': {'groups': 'ГСП 1'}}})
    assert bad.status_code == 400


def test_export_filters_per_tab_are_kept_and_cleaned():
    """Фильтры вкладок экспорта: поле без списка — «все» (не хранится), пустой список — «ничего»; пустые вкладки убираются."""
    from atlas import well_filter as wf
    assert wf.valid_tabs(None) and wf.valid_tabs({'production': {'wells': ['31']}})
    assert not wf.valid_tabs({'production': ['31']})
    assert wf.clean_tabs({'production': {'wells': ['31', '31'], 'groups': None}, 'pack': {}, 'gis': {'wells': []}}) == {
        'production': {'wells': ['31']}, 'gis': {'wells': []}}
    assert wf.clean_tabs({'pack': {}}) is None

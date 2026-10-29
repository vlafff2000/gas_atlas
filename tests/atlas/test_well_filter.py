"""Фильтр скважин вкладки: свой у каждой вкладки, пресеты общие (группы и скважины пересекаются, логика «И»)."""
import json

from atlas import well_filter
from atlas.contract import Data, ParamError
from atlas.domain import DatasetKind
from atlas.engine.core import exclusions
from atlas.engine.core.demo import well_demo_frames
from atlas.modules.gdi import GdiModule
from atlas.modules.gdi_trend import GdiTrendModule

GDI = DatasetKind.GDI


def _data(settings=None):
    gdi = exclusions.identify(well_demo_frames()['gdi'].copy(), 'gdi')
    wells = sorted(gdi.well.astype(str).unique(), key=lambda w: int(w) if w.isdigit() else w)
    data = Data({GDI: gdi}, {GDI: gdi}, {})
    data.mapping = {w: {'group': 'ГСП 1' if i < 2 else 'ГСП 2'} for i, w in enumerate(wells)}
    data.wells = wells
    data.settings = settings or {}
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
    data = _data()
    flt = {'groups': ['ГСП 1'], 'wells': [first, last]}
    scoped = well_filter.apply(data, flt)
    assert scoped.wells == [first]
    assert set(scoped[GDI].well.astype(str)) == {first}
    assert well_filter.status(data, flt) == {'groups': ['ГСП 1'], 'wells': [first, last], 'total': len(data.wells), 'shown': 1, 'hidden': 1}
    # Модули ГДИ берут уже отобранные скважины, без собственного фильтра групп
    result = GdiModule().run(scoped, GdiModule().spec.coerce({'wells': []}))
    assert len(result.charts) == 1
    assert GdiTrendModule().run(scoped, GdiTrendModule().spec.coerce({'wells': []})) is not None


def test_group_filter_without_wells_keeps_the_group():
    data = _data()
    scoped = well_filter.apply(data, {'groups': ['ГСП 2'], 'wells': []})
    assert scoped.wells == data.wells[2:]
    assert set(scoped[GDI].well.astype(str)) <= set(data.wells[2:])


def test_project_setting_no_longer_limits_modules():
    """Прежний общий фильтр проекта расчёты не ограничивает: фильтр задаёт каждая вкладка сама."""
    data = _data({'well_filter': {'groups': ['ГСП 2'], 'wells': []}})
    assert well_filter.apply(data) is data


def test_split_takes_the_filter_out_of_tab_params():
    flt, rest = well_filter.split({'wells': ['3'], 'well_filter': {'groups': ['ГСП 1', 'ГСП 1'], 'wells': []}})
    assert flt == {'groups': ['ГСП 1'], 'wells': []} and rest == {'wells': ['3']}
    assert well_filter.split({'well_filter': {'groups': [], 'wells': []}})[0] is None
    assert well_filter.split(None) == (None, {})
    try:
        well_filter.split({'well_filter': {'groups': 'ГСП 1'}})
    except ParamError:
        pass
    else:
        raise AssertionError('неверный фильтр должен быть отклонён')


def _client(tmp_path, monkeypatch):
    import atlas.api_projects as api_projects
    from starlette.testclient import TestClient
    from atlas.api import create_app
    from atlas.projects import Projects

    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    client = TestClient(create_app(Projects(tmp_path / 'storage')))
    return client, client.post('/api/projects/demo').json()['id']


def test_each_tab_filters_by_itself(tmp_path, monkeypatch):
    """Фильтр идёт среди параметров вкладки: расчёт, списки и состояние других вкладок от него не зависят."""
    client, pid = _client(tmp_path, monkeypatch)
    groups = client.get(f'/api/projects/{pid}/group-list').json()['groups']
    total = client.get(f'/api/projects/{pid}/well-filter').json()['total']
    flt = {'groups': [g for g in groups if g != 'Без группы'][:1], 'wells': []}
    status = client.post(f'/api/projects/{pid}/well-filter', json=flt).json()
    assert 0 < status['shown'] < total and status['groups'] == flt['groups']
    assert client.get(f'/api/projects/{pid}/well-filter').json()['shown'] == total     # без фильтра — все
    all_wells = client.get(f'/api/projects/{pid}/options', params={'dataset': 'production', 'column': 'well'}).json()
    some = client.get(f'/api/projects/{pid}/options', params={'dataset': 'production', 'column': 'well',
                                                              'filter': json.dumps(flt)}).json()
    assert 0 < len(some) < len(all_wells) and set(some) <= set(all_wells)
    bad = client.get(f'/api/projects/{pid}/options', params={'dataset': 'production', 'column': 'well', 'filter': '{"groups": "x"}'})
    assert bad.status_code == 400 or set(bad.json()) <= set(all_wells)
    # расчёт: у вкладки с фильтром меньше скважин, у вкладки без фильтра — все; запросы друг друга не затирают
    mine = client.post('/api/modules/gdi/run', json={'project': pid, 'params': {'well_filter': flt}}).json()
    other = client.post('/api/modules/gdi/run', json={'project': pid, 'params': {}}).json()
    assert 'error' not in mine and 'error' not in other
    assert mine['summary'] != other['summary'] or len(mine['charts']) <= len(other['charts'])
    broken = client.post('/api/modules/gdi/run', json={'project': pid, 'params': {'well_filter': {'wells': 5}}})
    assert broken.status_code == 400


def test_export_filters_per_tab_are_kept_and_cleaned():
    """Фильтры вкладок экспорта: поле без списка — «все» (не хранится), пустой список — «ничего»; пустые вкладки убираются."""
    from atlas import well_filter as wf
    assert wf.valid_tabs(None) and wf.valid_tabs({'production': {'wells': ['31']}})
    assert not wf.valid_tabs({'production': ['31']})
    assert wf.clean_tabs({'production': {'wells': ['31', '31'], 'groups': None}, 'pack': {}, 'gis': {'wells': []}}) == {
        'production': {'wells': ['31']}, 'gis': {'wells': []}}
    assert wf.clean_tabs({'pack': {}}) is None

"""«Экспорт»: перечень графиков, архивы и Word — код 5.8 (reporting.plan, export_plan, export_word);
форма с полями виджетов 5.8 даёт те же options, что собирает ``export_panel`` 5.8."""
import io
import json
import zipfile

import pandas as pd
import pytest
from starlette.testclient import TestClient

import atlas.api_projects as api_projects
from app.core import reporting
from app.core.bulk_export import export_plan, migrate_preset
from app.core.config import ordered
from app.core.storage import Store
from atlas.api import create_app
from atlas.api_export import options_from, preset_values, sync_form
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    projects = Projects(tmp_path / 'storage')
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, projects, Store(tmp_path / 'storage')


FORM = {'modules': ['production', 'gdi', 'response'], 'production_wells': ['31', '45'], 'gdi_wells': ['31', '70'],
        'response_split': 'well', 'formats': ['svg'], 'dpi': 300, 'width': 160}


def frames58(data, apply=True):
    raw = {k.value: d for k, d in data.raw.items()}
    return ({k.value: d for k, d in data.items()} if apply else raw), raw


def options58(data, form):
    """Options так, как их собирает export_panel 5.8 при этих значениях виджетов (остальные — по умолчанию)."""
    frames, raw = frames58(data)
    mapping, settings = data.mapping, data.settings
    group = lambda w: mapping.get(w, {}).get('group', 'Без группы')   # noqa: E731
    out = {'modules': [], 'wells': [], 'raw': False, 'apply_exclusions': True,
           'style': {'points': True, 'legend': True, 'grid': True}}
    selected = set()
    for module in ('production', 'gdi', 'response'):
        wells = ordered(raw[module].well)
        gs = ordered(group(w) for w in wells)
        ws = form.get(module + '_wells', wells)
        selected.update(ws)
        cfg = {'wells': ws, 'groups': gs}
        if module == 'production':
            d = frames['production']
            cfg.update(periods={k: ordered(d.loc[d.kind.eq(k), 'period']) for k in ('withdrawal', 'injection')},
                       view='curve', split='well', direction='number')
        elif module == 'gdi':
            cfg.update(n=3, orientation='standard', curves=True, db_curves=True, crosshair=True, show_excluded=True,
                       seasons=[])
        else:
            r = frames['response']
            hs = ordered(r.horizon)
            cfg.update(horizons=hs, working=[h for h in settings.get('working_horizons', []) if h in hs],
                       dates=[str(r.date.min().date()), str(r.date.max().date())], view='separate', split=form['response_split'])
        out[module] = cfg
        out['modules'].append(module)
    out['wells'] = ordered(selected)
    return out


def test_form_gives_58_options_and_plan(env):
    client, pid, projects, _ = env
    data = projects.data(pid)
    options, frames, raw = options_from(FORM, data)
    expected = options58(data, FORM)
    assert json.dumps(options, sort_keys=True, default=str) == json.dumps(expected, sort_keys=True, default=str)
    plan = reporting.plan(*frames58(data)[:1], data.mapping, data.settings, expected, frames58(data)[1])
    body = client.post(f'/api/projects/{pid}/export/plan', json={'form': FORM}).json()
    assert [c['name'] for c in body['charts']] == [j.name for j in plan.jobs]
    assert body['tables'] == list(plan.tables) and body['modules'] == ['production', 'gdi', 'response']


def test_archive_same_as_58(env, tmp_path):
    client, pid, projects, store = env
    form = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31']}
    r = client.post(f'/api/projects/{pid}/export/archive', json={'form': form})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['planned'] == body['completed'] == 1 and body['errors'] == [] and len(body['files']) == 1
    ours = store.path(pid) / 'exports' / body['files'][0]

    data = projects.data(pid)
    options, frames, raw = options_from(form, data)
    plan = reporting.plan(frames, data.mapping, data.settings, options, raw)
    theirs = export_plan(plan, store, pid, ['svg'], 300, 160, {'options': options}).paths[0]
    with zipfile.ZipFile(ours) as a, zipfile.ZipFile(theirs) as b:
        assert sorted(a.namelist()) == sorted(b.namelist())
        for name in a.namelist():
            if name.startswith('tables/'):
                assert a.read(name) == b.read(name)
        params = json.loads(a.read('parameters.json'))
        assert params['options']['gdi']['wells'] == ['31'] and params['width_mm'] == 160 and params['module'] == 'gdi'
    events = store.history(pid)
    assert 'Экспорт' in set(events['Действие'])


def test_word_preview_bundle(env):
    client, pid, _, store = env
    form = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31', '45'], 'caption_template_gdi': 'Рис. {номер} — {скважина}'}
    plan = client.post(f'/api/projects/{pid}/export/plan', json={'form': form}).json()
    png = client.post(f'/api/projects/{pid}/export/preview', json={'form': form, 'chart': plan['charts'][0]['name']})
    assert png.status_code == 200 and png.content[:4] == b'\x89PNG'
    assert client.post(f'/api/projects/{pid}/export/preview', json={'form': form, 'chart': 'нет'}).status_code == 404
    word = client.post(f'/api/projects/{pid}/export/word', json={'form': form}).json()
    assert word['completed'] == 2 and word['files'][0].endswith('ГДИ.docx')
    with zipfile.ZipFile(store.path(pid) / 'exports' / word['files'][0]) as z:
        assert 'Рис. 1 — 31' in z.read('word/document.xml').decode('utf8')
    bad = client.post(f'/api/projects/{pid}/export/word', json={'form': {**form, 'caption_template_gdi': '{нет}'}})
    assert bad.status_code == 400 and 'Неизвестное поле подписи' in bad.json()['error']
    bundle = client.post(f'/api/projects/{pid}/export/bundle', json={'files': word['files']}).json()
    with zipfile.ZipFile(store.path(pid) / 'exports' / bundle['file']) as z:
        assert word['files'][0] in z.namelist() and 'files.json' in z.namelist()


def test_empty_selection_is_a_note(env):
    client, pid, _, _ = env
    body = client.post(f'/api/projects/{pid}/export/plan', json={'form': {'modules': []}}).json()
    assert body['charts'] == [] and body['note']
    r = client.post(f'/api/projects/{pid}/export/archive', json={'form': {'modules': ['gdi'], 'gdi_wells': []}})
    assert r.status_code == 400 and 'скважину' in r.json()['error']
    assert client.post(f'/api/projects/{pid}/export/archive', json={'form': {**FORM, 'dpi': 72}}).status_code == 400


def test_exclusions_toggle(env):
    client, pid, projects, _ = env
    data = projects.data(pid)
    target = data.raw[next(k for k in data.raw if k.value == 'gdi')]
    point = target[target.well.eq('31')]._point_id.iloc[-1]
    client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'gdi', 'add': [point]})
    form = {'modules': ['gdi'], 'gdi_wells': ['31'], 'gdi_n': 0}
    data = projects.data(pid)
    with_ex, frames, _ = options_from(form, data)
    without, frames_all, _ = options_from({**form, 'exclusions': False}, data)
    assert len(frames['gdi']) == len(frames_all['gdi']) - 1 and without['apply_exclusions'] is False
    tables = client.post(f'/api/projects/{pid}/export/plan', json={'form': form}).json()['tables']
    assert 'Исключенные_точки' in tables
    tables = client.post(f'/api/projects/{pid}/export/plan', json={'form': {**form, 'exclusions': False}}).json()['tables']
    assert 'Исключенные_точки' not in tables


def test_presets_shared_with_58(env):
    client, pid, _, store = env
    form = {**FORM, 'style_grid': False, 'caption_section_gdi': '7', 'gdi_enabled': True, 'unrelated': 1}
    assert client.post(f'/api/projects/{pid}/export/presets', json={'name': 'Отчет', 'form': form}).status_code == 200
    saved = store.manifest(pid)['settings']['export_presets']['Отчет']
    assert saved == preset_values(form) and 'unrelated' not in saved and saved['style_grid'] is False
    assert store.history(pid).iloc[0]['Действие'] == 'Шаблон экспорта'
    # Шаблон старой версии (вид «hist») переводится так же, как при загрузке в 5.8.
    old = {'modules': ['production'], 'production_view': 'hist', 'production_wells': ['31'], 'periods_withdrawal': ['2020']}
    m = store.manifest(pid)
    store.commit(pid, settings={**m['settings'], 'export_presets': {'Старый': old}}, action='Шаблон экспорта')
    presets = client.get(f'/api/projects/{pid}/export/form').json()['presets']
    assert presets['Старый'] == migrate_preset(old) and presets['Старый']['modules'] == ['histograms']


def test_sync_from_saved_views(env):
    client, pid, projects, store = env
    m = store.manifest(pid)
    panels = {'gdi': {'wells': ['31'], 'n': 2, 'orientation': 'swapped'},
              'prod_0': {'wells': ['45'], 'kind': 'injection', 'periods': ['2021'], 'direction': 'desc'},
              'response': {'dates': ['2020-01-01T00:00:00', '2021-01-01'], 'split': 'well'}}
    store.commit(pid, settings={**m['settings'], 'panels': panels}, action='Сохранение фильтров')
    form = client.get(f'/api/projects/{pid}/export/sync').json()
    assert form == sync_form(projects.data(pid).settings)
    assert form['gdi_n'] == 2 and form['gdi_orientation'] == 'swapped' and form['gdi_wells'] == ['31']
    assert form['production_periods_injection'] == ['2021'] and form['production_direction'] == 'desc'
    assert form['response_dates'] == ['2020-01-01', '2021-01-01'] and form['response_split'] == 'well'


def test_every_module_plans_and_renders(tmp_path):
    """Все вкладки экспорта 5.8 (в т. ч. поскважинный анализ, эксплуатация, кроссплот давлений) строят план и графики."""
    from app.core.demo import well_demo_frames
    from atlas.api_export import choices
    from tests.atlas.test_pressure_module import pressure_frame
    projects = Projects(tmp_path / 'storage')
    pid = projects.store.create('Скважины')
    projects.store.commit(pid, {**well_demo_frames(), 'pressure_match': pressure_frame(tmp_path)}, action='test')
    data = projects.data(pid)
    mods = [m['id'] for m in choices(data)['modules']]
    assert {'well_dashboard', 'pressure_match', 'histograms'} <= set(mods)
    options, frames, raw = options_from({'modules': mods, 'pressure_pm_export_split': 'group'}, data)
    assert options['modules'] == mods and options['pressure_match']['split'] == 'group'
    plan = reporting.plan(frames, data.mapping, data.settings, options, raw)
    by_module = {}
    for job in plan.jobs:
        by_module.setdefault(job.module, job)
    assert {'well_dashboard', 'pressure_match', 'gdi'} <= set(by_module)
    for job in by_module.values():
        job.render()


def test_fund_pack_six_per_page(env):
    """Пакет по фонду: Word и PDF отдельно для отбора и закачки, подписи по шаблону, 6 графиков на лист A4."""
    client, pid, projects, _ = env
    r = client.post(f'/api/projects/{pid}/export/pack', json={'form': {}})
    assert r.status_code == 200, r.text
    out = r.json()
    names = out['files']
    assert [n.split('_', 3)[-1] for n in names] == [
        'Приложение_отбор.docx', 'Приложение_отбор.pdf', 'Приложение_закачка.docx', 'Приложение_закачка.pdf']
    assert out['errors'] == [] and out['completed'] == out['planned'] > 0
    docx = zipfile.ZipFile(io.BytesIO(client.get(f'/api/projects/{pid}/exports/{names[0]}').content))
    xml = docx.read('word/document.xml').decode('utf-8')
    assert 'Производительность скважины №' in xml and 'при отборе газа за ' in xml and 'Рисунок П4.1 ' in xml
    charts = len([n for n in docx.namelist() if n.startswith('word/media/')])
    assert xml.count('<w:tbl>') == -(-charts // 6) and xml.count('pageBreakBefore') == xml.count('<w:tbl>') - 1
    pdf = client.get(f'/api/projects/{pid}/exports/{names[1]}').content
    assert pdf[:4] == b'%PDF'
    assert b'/Count %d' % (-(-charts // 6)) in pdf
    only = client.post(f'/api/projects/{pid}/export/pack', json={'form': {'pack_kinds': ['injection'], 'pack_formats': ['pdf'],
                                                                      'pack_template': '{скважина}: {режим} {годы}'}})
    assert [n.split('_', 3)[-1] for n in only.json()['files']] == ['Приложение_закачка.pdf']
    bad = client.post(f'/api/projects/{pid}/export/pack', json={'form': {'pack_template': '{нет}'}})
    assert bad.status_code == 400


def test_response_control_and_working_horizons(env):
    client, pid, projects, _ = env
    data = projects.data(pid)
    working = [h for h in data.settings.get('working_horizons', [])]
    names = {}
    for mode in ('control', 'working', 'both'):
        form = {'modules': ['response'], 'response_mode': mode, 'response_working': working}
        body = client.post(f'/api/projects/{pid}/export/plan', json={'form': form}).json()
        names[mode] = [c['name'] for c in body['charts']]
    assert names['both'] == names['control'] + names['working']
    assert all(n.startswith('контроль · ') and n.endswith('уровень') for n in names['control'])
    assert all(n.startswith('рабочий · ') for n in names['working'])
    assert names['control'] or names['working']

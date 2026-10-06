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
        xml = z.read('word/document.xml').decode('utf8')
        assert 'SEQ Рисунок' in xml and 'w:bookmarkStart' in xml and '<w:t xml:space="preserve"> — 31</w:t>' in xml
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


def test_fund_pack_seasons_and_layout(env):
    """Сезоны выбираются обязательно, листов 2/4/6 на выбор; картинки палитровые и легкие."""
    client, pid, _, _ = env
    url = f'/api/projects/{pid}/export/pack'
    seasons = client.get(f'/api/projects/{pid}/export/form').json()['periods']['withdrawal']
    assert client.post(url, json={'form': {'pack_kinds': ['withdrawal'], 'pack_periods_withdrawal': []}}).status_code == 400
    assert client.post(url, json={'form': {'pack_per_page': 5}}).status_code == 400
    sizes = {}
    for per in (2, 4):
        r = client.post(url, json={'form': {'pack_kinds': ['withdrawal'], 'pack_formats': ['docx', 'pdf'], 'pack_per_page': per,
                                            'pack_periods_withdrawal': seasons[-1:]}})
        assert r.status_code == 200, r.text
        names = r.json()['files']
        pdf = client.get(f'/api/projects/{pid}/exports/{names[1]}').content
        charts = r.json()['completed']
        assert b'/Count %d' % (-(-charts // per)) in pdf
        docx = zipfile.ZipFile(io.BytesIO(client.get(f'/api/projects/{pid}/exports/{names[0]}').content))
        media = [n for n in docx.namelist() if n.startswith('word/media/')]
        assert len(media) == charts
        assert docx.read(media[0])[25] == 3        # PNG: тип цвета 3 — палитра
        assert len(docx.read(media[0])) < 60_000
        sizes[per] = docx.read('word/document.xml').decode('utf-8').count('<w:tbl>')
    assert sizes[2] >= sizes[4]


def test_interactive_preview_chart_and_exclusion(env):
    client, pid, _, _ = env
    form = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31']}
    plan = client.post(f'/api/projects/{pid}/export/plan', json={'form': form}).json()
    chart = client.post(f'/api/projects/{pid}/export/chart', json={'form': form, 'chart': plan['charts'][0]['name']}).json()
    pickable = [s for s in chart['series'] if s['ids']]
    assert pickable and pickable[0]['dataset'] == 'gdi'
    point = pickable[0]['ids'][0]
    assert client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'gdi', 'add': [point], 'remove': []}).json()['added'] == 1
    again = client.post(f'/api/projects/{pid}/export/chart', json={'form': form, 'chart': plan['charts'][0]['name']}).json()
    assert point not in [i for s in again['series'] for i in (s['ids'] or [])]      # исключённая точка больше не выбирается
    assert client.post(f'/api/projects/{pid}/export/chart', json={'form': form, 'chart': 'нет'}).status_code == 404



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


def test_chart_height_in_preview_and_archive(env):
    """Высота графика: пустая — как в 5.8, заданная меняет размер картинки предпросмотра и файлов архива."""
    import struct
    client, pid, _, _ = env
    form = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31'], 'formats': ['svg'], 'width': 200}
    name = client.post(f'/api/projects/{pid}/export/plan', json={'form': form}).json()['charts'][0]['name']

    def size(extra):
        png = client.post(f'/api/projects/{pid}/export/preview', json={'form': {**form, **extra}, 'chart': name})
        assert png.status_code == 200
        return struct.unpack('>II', png.content[16:24])
    auto_w, auto_h = size({})
    tall_w, tall_h = size({'height': 250})
    assert auto_w == tall_w and abs(tall_h / tall_w - 250 / 200) < 0.01 and tall_h != auto_h
    assert size({'height': 0}) == (auto_w, auto_h)
    for bad in (10, 900, 'abc'):
        assert client.post(f'/api/projects/{pid}/export/preview', json={'form': {**form, 'height': bad}, 'chart': name}).status_code == 400
    archive = client.post(f'/api/projects/{pid}/export/archive', json={'form': {**form, 'height': 100}}).json()
    with zipfile.ZipFile(env[3].path(pid) / 'exports' / archive['files'][0]) as z:
        svg = z.read([n for n in z.namelist() if n.endswith('.svg')][0]).decode('utf8')
    import re
    w, h = re.search(r'width="([\d.]+)pt" height="([\d.]+)pt"', svg).groups()
    assert abs(float(h) / float(w) - 100 / 200) < 0.01


def test_word_layout_landscape_fill_and_preview(env):
    """Макет Word: альбомный лист, график на всю ширину поля (не сжат), настоящие подписи, список рисунков, предпросмотр листа."""
    client, pid, _, store = env
    form = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31', '45'], 'word_orientation': 'landscape', 'word_columns': 1,
            'word_list_of_figures': True, 'word_page_numbers': True, 'word_per_page': 1}
    word = client.post(f'/api/projects/{pid}/export/word', json={'form': form}).json()
    assert word['completed'] == 2 and not word['errors']
    with zipfile.ZipFile(store.path(pid) / 'exports' / word['files'][0]) as z:
        xml = z.read('word/document.xml').decode('utf8')
        assert 'w:orient="landscape"' in xml and 'w:w="16838" w:h="11906"' in xml
        assert 'TOC \\h \\z \\c' in xml and 'w:hyperlink w:anchor="_Ref' in xml and 'PAGE' in z.read('word/footer1.xml').decode('utf8')
        assert xml.count('<w:pageBreakBefore/>') == 2          # после списка рисунков и перед вторым графиком
        import re
        cx = int(re.search(r'<wp:extent cx="(\d+)"', xml).group(1))
        assert abs(cx / 36000 - (297 - 25 - 15)) < 1          # ширина поля листа, мм
    preview = client.post(f'/api/projects/{pid}/export/word-preview', json={'form': form, 'page': 2}).json()
    assert preview['pages'] == 2 and preview['exact'] and preview['png'].startswith('data:image/png;base64,')
    assert preview['page_mm'] == [297.0, 210.0]
    bad = client.post(f'/api/projects/{pid}/export/word', json={'form': {**form, 'word_columns': 7}})
    assert bad.status_code == 400 and 'Колонок' in bad.json()['error']
    one = client.post(f'/api/projects/{pid}/export/word', json={'form': {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31'], 'word_columns': 2, 'word_caption_mode': 'text'}}).json()
    with zipfile.ZipFile(store.path(pid) / 'exports' / one['files'][0]) as z:
        xml = z.read('word/document.xml').decode('utf8')
        assert '<w:tbl>' in xml and 'SEQ' not in xml and 'w:bookmarkStart' in xml


def test_custom_labels_per_chart_type(env):
    """Подписи осей, заголовка и легенды задаются для каждого типа графиков; ГДИ — шаблон записи легенды."""
    client, pid, _, store = env
    base = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31']}
    plan = client.post(f'/api/projects/{pid}/export/plan', json={'form': base}).json()
    name = plan['charts'][0]['name']
    texts = lambda c: [s['name'] for s in c['series'] if s.get('name')]
    chart = lambda form: client.post(f'/api/projects/{pid}/export/chart', json={'form': form, 'chart': name}).json()
    before = chart({**base, 'label_gdi_template': ''})       # пусто — полная запись легенды
    assert not any('Установившиеся' in t for t in texts(chart(base)))       # по умолчанию — только дата
    assert any('Установившиеся отборы' in t for t in texts(before))
    form = {**base, 'label_gdi_template': '{дата}', 'label_gdi_x': 'Дебит Q, тыс. м³/сут', 'label_gdi_y': 'ΔP², (кгс/см²)²',
            'label_gdi_title': 'ГДИ, скв. {скважина}', 'label_gdi_legend': 'Исключенные точки=Отброшено'}
    after = chart(form)
    assert not any('Установившиеся' in t for t in texts(after)) and len(texts(after)) == len(texts(before))
    assert 'Дебит Q' in str(after) and 'ГДИ, скв. 31' in str(after)
    png = client.post(f'/api/projects/{pid}/export/preview', json={'form': form, 'chart': name})
    assert png.status_code == 200 and png.content[:4] == b'\x89PNG'
    bad = client.post(f'/api/projects/{pid}/export/preview', json={'form': {**base, 'label_gdi_template': '{нет}'}, 'chart': name})
    assert bad.status_code == 400 and 'Неизвестное поле легенды' in bad.json()['error']
    from atlas import chart_labels
    assert chart_labels.gdi_label('10.12.2023 · Установившиеся отборы · 2', '{дата} · {метод} · {исследование}') == '10.12.2023 · Установившиеся отборы · 2'
    assert chart_labels.gdi_label('10.12.2023 · Изохронный', '{дата} · {метод} · {исследование}') == '10.12.2023 · Изохронный'

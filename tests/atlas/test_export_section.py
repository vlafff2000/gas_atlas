"""«Экспорт»: перечень графиков, архивы и Word — код 5.8 (reporting.plan, export_plan, export_word);
форма с полями виджетов 5.8 даёт те же options, что собирает ``export_panel`` 5.8."""
import io
import json
import zipfile

import pandas as pd
import pytest
from starlette.testclient import TestClient

import atlas.api_projects as api_projects
from atlas.engine.core import reporting
from atlas.engine.core.bulk_export import export_plan, migrate_preset
from atlas.engine.core.config import ordered
from atlas.engine.core.storage import Store
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
                       dates=[str(r.date.min().date()), str(r.date.max().date())], view='separate', split=form['response_split'],
                       level_band='auto')      # ≈ 5.8: уровень на двух шкалах отдельной полосой (docs/parity/response.md)
        out[module] = cfg
        out['modules'].append(module)
    out['wells'] = ordered(selected)
    return out


def test_form_gives_58_options_and_plan(env):
    client, pid, projects, _ = env
    data = projects.data(pid)
    options, frames, raw = options_from(FORM, data)
    expected = options58(data, FORM)
    options['production'].pop('season_titles')      # ≈ 5.8: подписи «в сезон отбора …» только в 6
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
    from atlas.engine.core.demo import well_demo_frames
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
    pages = -(-charts // 6)
    assert xml.count('<w:tbl>') == 1 and xml.count('pageBreakBefore') == pages - 1       # все графики приложения — в единой таблице
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
        xml = docx.read('word/document.xml').decode('utf-8')
        assert xml.count('<w:tbl>') == 1
        sizes[per] = xml.count('pageBreakBefore') + 1
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
    assert preview['layout_checks'] == [] and word['layout_checks'] == []      # нарисованное под ячейку проверку проходит
    narrow = client.post(f'/api/projects/{pid}/export/word-preview', json={'form': {**form, 'word_orientation': 'portrait', 'word_columns': 3, 'word_per_page': 0}}).json()
    assert [c['code'] for c in narrow['layout_checks']] == ['narrow'] and narrow['layout_checks'][0]['items']      # третья часть листа: график уже 60 мм
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


def test_excel_look(env):
    """Вид «как в Excel»: выключен по умолчанию, работает в предпросмотре, архиве и Word, ошибка при неизвестном виде."""
    from atlas.engine.core.export import XL_PALETTE, figure_bytes
    from atlas.engine.core.fonts import family_for
    client, pid, _, store = env
    form = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31']}
    name = client.post(f'/api/projects/{pid}/export/plan', json={'form': form}).json()['charts'][0]['name']
    shot = lambda f: client.post(f'/api/projects/{pid}/export/preview', json={'form': f, 'chart': name})
    plain, excel = shot(form), shot({**form, 'look': 'excel'})
    assert plain.status_code == excel.status_code == 200 and plain.content != excel.content
    assert shot({**form, 'look': 'excel', 'font': 'calibri', 'font_size': 10}).status_code == 200
    assert shot({**form, 'look': 'word'}).status_code == 400
    assert XL_PALETTE[0] == '#4472C4' and family_for('calibri')[0] in ('Calibri', 'Carlito')
    word = client.post(f'/api/projects/{pid}/export/word', json={'form': {**form, 'look': 'excel'}}).json()
    assert word['completed'] == 1 and not word['errors']
    zipped = client.post(f'/api/projects/{pid}/export/archive', json={'form': {**form, 'look': 'excel', 'formats': ['png']}}).json()
    assert zipped['files'] and not zipped['errors']


def test_chart_format_per_dataset(env):
    """Общие наклон X, шапка и легенда — для всех графиков; толщина, маркеры, цвет и скрытие — по наборам данных каждого типа."""
    import plotly.graph_objects as go
    from atlas.engine.core.export import figure_bytes
    from atlas import chart_format
    client, pid, _, store = env
    fig = go.Figure([go.Scatter(x=[1, 2, 3], y=[1, 2, 3], mode='lines+markers', name='Пластовое давление объекта'),
                     go.Scatter(x=[1, 2, 3], y=[3, 2, 1], mode='lines+markers', name='№ 31')])
    rules = '[{"match": "объекта", "color": "#ff0000", "width": 4, "marker": 0}, {"match": "№ 31", "marker": 6, "width": 3}, {"match": "нет такого", "hide": true}]'
    form = {'fmt_angle': '45', 'fmt_title': 'hide', 'fmt_legend': 'right', 'fmt_response_series': rules}
    found = chart_format.configs(form)
    assert chart_format.for_module(found, 'response')['series'] and 'series' not in chart_format.for_module(found, 'gdi')
    assert chart_format.for_module(found, 'gdi') == {'angle': '45', 'title': 'hide', 'legend': 'right'}
    out = chart_format.apply(fig, chart_format.for_module(found, 'response'))
    first, second = out.data
    assert first.line.color == '#ff0000' and first.line.width == 4 and first.mode == 'lines'      # маркеры убраны только у «объекта»
    assert second.mode == 'lines+markers' and second.marker.size == 12 and second.line.width == 3 and second.visible is None
    assert out.layout.meta['format'] == {'title': 'hide', 'angle': '45', 'legend': 'right'} and fig.data[0].line.width is None
    for look in ('default', 'excel'):
        assert figure_bytes(out, 'png', 150, 160, look=look)[:4] == b'\x89PNG'
    for bad in ({'fmt_angle': '13'}, {'fmt_response_series': '[{"match":"a","color":"red"}]'}, {'fmt_response_series': '{'},
                {'fmt_response_series': '[{"match":"a","width":99}]'}):
        with pytest.raises(chart_format.FormatError):
            chart_format.configs(bad)
    base = {**FORM, 'modules': ['response'], 'response_wells': ['31']}
    name = client.post(f'/api/projects/{pid}/export/plan', json={'form': base}).json()['charts'][0]['name']
    shot = lambda f: client.post(f'/api/projects/{pid}/export/preview', json={'form': f, 'chart': name})
    plain = shot(base)
    assert shot({**base, 'fmt_angle': '45', 'fmt_legend': 'top', 'fmt_response_series': '[{"match": "давление", "width": 4, "marker": 0}]'}).content != plain.content
    assert shot({**base, 'fmt_angle': '13'}).status_code == 400
    names = client.post(f'/api/projects/{pid}/export/series', json={'form': base}).json()['series']
    assert 'уровень' in ' '.join(names['response']).lower() and 'Сумма УВ' in names['ggh']


def test_histogram_export_with_format_rules(env):
    """«Гистограммы»: правила оформления по наборам данных (цвет, толщина, скрытие) не падают на столбцах и меняют рисунок."""
    import plotly.graph_objects as go
    from atlas import chart_format
    client, pid, _, _ = env
    fig = go.Figure([go.Bar(x=['31', '45'], y=[1, 2], name='2024-2025'), go.Scatter(x=[1, 2], y=[1, 2], mode='lines', name='линия')])
    out = chart_format.apply(fig, {'series': [{'match': '2024', 'color': '#ff0000', 'width': 3, 'marker': 6}]})
    assert out.data[0].marker.color == '#ff0000' and out.data[1].line.width is None
    base = {'modules': ['histograms'], 'histograms_wells': ['31', '45', '70'], 'formats': ['svg'], 'dpi': 300, 'width': 160}
    name = client.post(f'/api/projects/{pid}/export/plan', json={'form': base}).json()['charts'][0]['name']
    shot = lambda f: client.post(f'/api/projects/{pid}/export/preview', json={'form': f, 'chart': name})
    plain = shot(base)
    assert plain.status_code == 200, plain.text
    rule = '[{"match": "2025", "color": "#ff0000"}, {"match": "2024", "hide": true}]'
    styled = shot({**base, 'fmt_histograms_series': rule})
    assert styled.status_code == 200, styled.text
    assert styled.content != plain.content
    assert client.post(f'/api/projects/{pid}/export/archive', json={'form': {**base, 'fmt_histograms_series': rule}}).json()['errors'] == []


def test_pack_and_ggh_use_export_settings(env):
    """Пакет по фонду и ГГХ принимают общие настройки выгрузки: вид, шрифт, подписи и оформление наборов данных."""
    client, pid, _, store = env
    pack = {'pack_kinds': ['withdrawal'], 'pack_formats': ['docx'], 'pack_per_page': 6, 'look': 'excel', 'fmt_legend': 'hide',
            'fmt_production_series': '[{"match": "скв", "width": 3}]'}
    done = client.post(f'/api/projects/{pid}/export/pack', json={'form': pack})
    assert done.status_code in (200, 400)
    if done.status_code == 200:
        assert done.json()['completed'] > 0
    from atlas import ggh_report
    import pandas as pd
    frame = pd.DataFrame({'date': pd.to_datetime(['2020-01-01', '2021-01-01', '2022-01-01']), 'hc': [10, 20, 30], 'he': [1, 2, 3], 'gas': [5, 6, 7]})
    base = ggh_report.figure_png(frame, '1', 100)
    styled = ggh_report.figure_png(frame, '1', 100, 'times', {'look': 'excel', 'title': 'hide', 'angle': '90', 'font_size': 14,
                                                              'series': [{'match': 'he', 'hide': True}, {'match': 'сумма', 'width': 3, 'marker': 0}]})
    assert base[:4] == styled[:4] == b'\x89PNG' and base != styled


def test_pack_and_ggh_own_labels_and_axes(env):
    """У пакета по фонду и ГГХ свои подписи и оси (как у остальных типов графиков); пакет наследует настройки «Производительности»."""
    from atlas import api_export, ggh_report
    form = api_export.pack_form({'fmt_production_series': 'A', 'fmt_pack_series': 'B', 'label_pack_title': 'T', 'fmt_pack_axes': ''})
    assert form['fmt_production_series'] == 'B' and form['label_production_title'] == 'T' and 'fmt_production_axes' not in form
    assert api_export.pack_form({'fmt_production_series': 'A'})['fmt_production_series'] == 'A'
    style = api_export.ggh_style({'label_ggh_title': 'Скв {скважина}', 'label_ggh_y': 'Y', 'fmt_ggh_axes': '{"y": {"min": 0, "max": 50, "major": 10}}'}, None)
    assert style['labels'] == {'title': 'Скв {скважина}', 'y': 'Y'} and style['axes']['y']['max'] == 50
    frame = pd.DataFrame({'date': pd.to_datetime(['2020-01-01', '2021-01-01', '2022-01-01']), 'hc': [10, 20, 30], 'he': [1, 2, 3], 'gas': [5, 6, 7]})
    plain = ggh_report.figure_png(frame, '1', 100)
    own = ggh_report.figure_png(frame, '1', 100, 'times', style)
    assert own[:4] == b'\x89PNG' and own != plain


def test_pack_and_ggh_ids_in_modules_are_ignored_by_plan(env):
    """«Пакет по фонду» и «ГГХ» включаются в список модулей формы, но перечень графиков строится по остальным."""
    client, pid, _, _ = env
    base = client.post(f'/api/projects/{pid}/export/plan', json={'form': {'modules': ['production']}}).json()
    mixed = client.post(f'/api/projects/{pid}/export/plan', json={'form': {'modules': ['production', 'pack', 'ggh']}}).json()
    assert mixed['modules'] == ['production'] and mixed['charts'] == base['charts']


def test_zero_width_keeps_markers_and_season_titles(env):
    """Толщина 0 выключает линию, маркеры остаются; подписи поскважинных графиков и скрытие нейтральных периодов."""
    import plotly.graph_objects as go
    from atlas.engine.modules import charts
    from atlas import chart_format
    from atlas.modules._production import visible_periods
    fig = go.Figure([go.Scatter(x=[1, 2, 3], y=[1, 2, 3], mode='lines+markers', name='Набор')])
    cfg = chart_format.for_module(chart_format.configs({'fmt_gdi_series': '[{"match": "набор", "width": 0}]'}), 'gdi')
    assert chart_format.apply(fig, cfg).data[0].mode == 'markers'
    assert charts.season_title('540', 'withdrawal', ['2025-2026']) == 'Производительность скважины № 540 в сезон отбора 2025-2026'
    assert charts.season_title('540', 'injection', ['2025']) == 'Производительность скважины № 540 в сезон закачки 2025'
    periods = ['2024-2025', 'Нейтральный период Весна 2025', 'Вне сезона 2025']
    assert visible_periods(periods, {}) == ['2024-2025']
    assert visible_periods(periods, {'show_neutral_periods': True}) == periods


def test_extras_preview_lists_and_renders_pack_charts(env):
    """Предпросмотр пакета по фонду: перечень графиков и картинка одного из них."""
    client, pid, _, _ = env
    url = f'/api/projects/{pid}/export'
    none = client.post(url + '/extras', json={'form': {'modules': ['production']}}).json()
    assert none['charts'] == []
    listed = client.post(url + '/extras', json={'form': {'modules': ['pack'], 'pack_kinds': ['withdrawal']}}).json()['charts']
    assert listed and all(c['module'] == 'pack' for c in listed)
    png = client.post(url + '/extras-preview', json={'form': {'modules': ['pack']}, 'chart': listed[0]['name']})
    assert listed[0]['name'].startswith('Пакет · ')
    assert png.status_code == 200 and png.content[:4] == b'\x89PNG'
    assert client.post(url + '/extras-preview', json={'form': {'modules': ['pack']}, 'chart': 'нет'}).status_code == 404


def test_chart_format_single_chart_override(env):
    """Свои цвет и оси одного графика из семейства: перекрывают настройки типа, остальные графики не меняются."""
    import plotly.graph_objects as go
    from atlas import chart_format
    client, pid, _, _ = env
    fig = go.Figure([go.Scatter(x=[1, 2], y=[1, 2], mode='lines', name='№ 31')])
    form = {'fmt_response_series': '[{"match": "№ 31", "color": "#00ff00", "width": 2}]', 'fmt_response_axes': '{"y": {"min": 0, "max": 10}}',
            'fmt_overrides': '{"график А": {"series": [{"match": "№ 31", "color": "#ff0000"}], "axes": {"y": {"max": 50}}}, "пустой": {}}'}
    own = chart_format.parse_overrides(form['fmt_overrides'])
    assert list(own) == ['график А']
    cfg = chart_format.merge(chart_format.for_module(chart_format.configs(form), 'response'), own['график А'])
    assert cfg['axes']['y'] == {'max': 50.0, 'dates': False} and len(cfg['series']) == 2
    out = chart_format.apply(fig, cfg)
    assert out.data[0].line.color == '#ff0000' and out.data[0].line.width == 2
    for bad in ('{', '[1]', '{"a": {"series": [{"match": "x", "color": "red"}]}}'):
        with pytest.raises(chart_format.FormatError):
            chart_format.parse_overrides(bad)
    base = {**FORM, 'modules': ['response'], 'response_wells': ['31']}
    name = client.post(f'/api/projects/{pid}/export/plan', json={'form': base}).json()['charts'][0]['name']
    shot = lambda f, n=name: client.post(f'/api/projects/{pid}/export/preview', json={'form': f, 'chart': n})
    plain = shot(base)
    mine = {**base, 'fmt_overrides': json.dumps({name: {'axes': {'y': {'min': 0, 'max': 500}}}})}
    assert shot(mine).content != plain.content
    other = {**base, 'fmt_overrides': json.dumps({'другой': {'axes': {'y': {'min': 0, 'max': 500}}}})}
    assert shot(other).content == plain.content
    assert shot({**base, 'fmt_overrides': '{'}).status_code == 400
    names = client.post(f'/api/projects/{pid}/export/series', json={'form': base, 'chart': name}).json()
    assert names['chart'] and 'уровень' in ' '.join(names['chart']).lower()


def test_well_charts_always_in_natural_number_order(env):
    """По умолчанию графики скважин в выгрузке идут по возрастанию номера («2» раньше «10»), каким бы ни был порядок выбора в форме."""
    client, pid, _, _ = env
    form = {**FORM, 'modules': ['production'], 'production_wells': ['132', '45', '31', '70']}
    names = [c['name'] for c in client.post(f'/api/projects/{pid}/export/plan', json={'form': form}).json()['charts']]
    wells = [n.split(' · ', 1)[1] for n in names if n.startswith('Отбор · ')]
    assert len(wells) >= 2
    assert wells == ordered(wells)


def test_export_wells_in_number_order(env):
    """Выгрузки идут по возрастанию номера скважины, даже если в форме их выбрали в другом порядке."""
    client, pid, _, _ = env
    wells = ['540', '70', '31', '45']
    for module in ('histograms', 'production'):
        form = {'modules': [module], f'{module}_wells': wells, 'formats': ['svg']}
        if module == 'histograms':
            form['histograms_wells'] = wells
        names = [c['name'] for c in client.post(f'/api/projects/{pid}/export/plan', json={'form': form}).json()['charts']]
        kinds = {n.split(' · ')[0] for n in names}
        for kind in kinds:
            part = [int(n.split(' · ')[1]) for n in names if n.startswith(kind)]
            assert part == sorted(part, key=int), (module, kind, part)


def test_word_figures_without_captions(env):
    """«Подписи рисунков» выключены: в документе нет подписей и полей SEQ, список рисунков не выводится."""
    client, pid, _, store = env
    base = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31'], 'word_list_of_figures': True}
    def xml_of(form):
        one = client.post(f'/api/projects/{pid}/export/word', json={'form': form}).json()
        with zipfile.ZipFile(store.path(pid) / 'exports' / one['files'][0]) as z:
            return z.read('word/document.xml').decode('utf8')
    with_caption = xml_of(base)
    without = xml_of({**base, 'word_caption_show': False})
    assert 'SEQ' in with_caption and 'TOC \\h \\z \\c' in with_caption
    assert 'SEQ' not in without and 'TOC \\h \\z \\c' not in without and 'w:drawing' in without


def test_fund_pack_own_well_filter(env):
    """Пакет по фонду: свой фильтр скважин вкладки (pack_wells) сужает скважины пакета, не трогая модуль добычи."""
    from atlas.api_export import pack_options
    _, pid, projects, _ = env
    data = projects.data(pid)
    everything = options_from(pack_options({}, data), data)[0]['wells']
    assert len(everything) >= 2
    one = everything[:1]
    picked = options_from(pack_options({'pack_wells': one}, data), data)[0]['wells']
    assert picked == one
    assert options_from(pack_options({'pack_wells': []}, data), data)[0]['wells'] == []


def test_word_preview_sheet_scale_and_caption_font():
    import io
    from PIL import Image
    from atlas import word_export
    layout = word_export.Layout(caption_font='Times New Roman', caption_bold=True)
    items = [word_export.Item(name='График', before='Рисунок ', number=1, after=' – Подпись', w=100.0, h=60.0)]
    for scale in (3.0, 6.0):
        png, pages = word_export.preview_png(layout, items, 1, {}, scale=scale)
        assert pages == 1 and Image.open(io.BytesIO(png)).size == (round(210 * scale), round(297 * scale))   # A4 в заданном масштабе
    assert word_export._font(40, 'Times New Roman', True, False).getname()[0] != word_export._font(40, 'Verdana').getname()[0]


def test_word_headers_footers_and_properties():
    import io
    import zipfile
    from xml.dom import minidom
    from PIL import Image
    from atlas import word_export
    png = io.BytesIO()
    Image.new('RGB', (40, 20), 'white').save(png, 'PNG')
    items = [word_export.Item(name='Г', before='Рисунок ', number=i, after=' – п', png=png.getvalue(), w=100.0, h=50.0) for i in (1, 2)]
    form = {'word_page_numbers': True, 'word_page_number_pos': 'header-right', 'word_page_number_format': 'page', 'word_page_start': 5,
            'word_header_text': 'Отчёт {проект}', 'word_footer_text': '{дата} · стр. {страница}', 'word_hf_align': 'left',
            'word_figure_align': 'left', 'word_text_font': 'Arial', 'word_text_size': 11, 'word_title': True, 'word_title_align': 'center',
            'word_doc_title': 'Заголовок файла', 'word_doc_author': 'Автор'}
    layout = word_export.layout_from(form)
    with zipfile.ZipFile(io.BytesIO(word_export.build_docx(items, layout, 'Объект'))) as z:
        names = set(z.namelist())
        assert {'word/header1.xml', 'word/footer1.xml', 'docProps/core.xml'} <= names
        for name in names:
            if name.endswith(('.xml', '.rels')):
                minidom.parseString(z.read(name))                     # каждая часть — корректный XML
        header, footer = z.read('word/header1.xml').decode(), z.read('word/footer1.xml').decode()
        assert 'Отчёт ' in header and 'Объект' in header and 'PAGE' in header and 'w:val="right"' in header      # номер вверху справа
        assert 'PAGE' in footer
        document = z.read('word/document.xml').decode()
        assert '<w:pgNumType w:start="5"/>' in document and 'rIdHeader' in document and '<w:jc w:val="left"/>' in document
        assert 'Arial' in z.read('word/styles.xml').decode() and 'Заголовок файла' in z.read('docProps/core.xml').decode()
    for bad in ({'word_page_number_pos': 'middle'}, {'word_text_font': 'Comic'}, {'word_page_start': 0}, {'word_page_start': 3, 'word_footer_text': 'из {страниц}'},
                {'word_page_start': 3, 'word_page_numbers': True, 'word_page_number_format': 'of'}):
        with pytest.raises(word_export.LayoutError):
            word_export.layout_from(bad)
    # без колонтитулов лишних частей нет
    with zipfile.ZipFile(io.BytesIO(word_export.build_docx(items, word_export.layout_from({}), 'Объект'))) as z:
        assert not {'word/header1.xml', 'word/footer1.xml', 'docProps/core.xml'} & set(z.namelist())
    png2, pages = word_export.preview_png(layout, items, 1, {}, project='Объект')
    assert pages >= 1 and png2[:4] == b'\x89PNG'


def test_long_chart_title_wraps_instead_of_being_cut():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from atlas.engine.core.export import fit_title
    f = plt.figure(figsize=(170 / 25.4, 116 / 25.4))
    long = 'Производительность скважины № 31 в сезоны отбора 2023-2024, 2024-2025, 2025-2026'
    wrapped = fit_title(f, long, 12)
    assert '\n' in wrapped and wrapped.replace('\n', ' ') == long      # перенос по словам, текст не меняется
    assert fit_title(f, 'Скважина № 31', 12) == 'Скважина № 31'          # короткое название не трогаем
    assert fit_title(f, 'Две\nстроки', 12) == 'Две\nстроки'              # своё разбиение сохраняется
    plt.close(f)


def test_quality_report_for_the_plan(env):
    """«Проверить качество»: по каждому графику плана находки проверки (atlas/chart_qc.py), файлы не создаются.
    Узкая ширина даёт мелкий шрифт после уменьшения, обычная — чистый отчёт."""
    client, pid, _, store = env
    base = {**FORM, 'modules': ['gdi'], 'gdi_wells': ['31', '70']}
    ok = client.post(f'/api/projects/{pid}/export/quality', json={'form': base}).json()
    assert ok['checked'] >= 2 and ok['errors'] == [] and ok['with_findings'] == len(ok['charts'])
    wide = client.post(f'/api/projects/{pid}/export/quality', json={'form': {**base, 'width': 300}}).json()
    assert wide['with_findings'] == wide['checked'] > 0
    one = wide['charts'][0]
    assert one['name'] and {f['code'] for f in one['findings']} == {'small-font'} and 'после уменьшения' in one['findings'][0]['text']
    assert not (store.path(pid) / 'exports').exists() or not list((store.path(pid) / 'exports').glob('*.zip'))      # файлов не появилось


def test_word_narrow_cell_uses_compact_chart(monkeypatch):
    """Две-три колонки на листе: график строится компактно (шрифт под ширину ячейки), а не обычным 12 пт, который сжимал область осей в щель."""
    import atlas.engine.core.export as export
    from atlas import word_export
    seen = []
    real = export.figure_bytes
    monkeypatch.setattr(export, 'figure_bytes', lambda *a, **k: (seen.append((a[3], a[4], k.get('compact'))), real(*a, **k))[1])
    import plotly.graph_objects as go
    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[1, 3, 2], name='а'))
    fig.update_layout(title='Производительность скважины № 31 в сезоны отбора 2023-2024, 2024-2025, 2025-2026')
    for columns in (1, 2):
        layout = word_export.layout_from({'word_columns': columns})
        word_export.render_png(fig, layout, 8.0)
    (w1, h1, c1), (w2, h2, c2) = seen[0], seen[1]
    assert not c1 and c2 and h2 and h2 / w2 <= word_export.COMPACT_ASPECT + 0.01


def test_branch_format_applies_to_multiple_wells_and_saved_files(env):
    client, pid, _, store = env
    url = f'/api/projects/{pid}/export'
    form = {
        **FORM,
        'fmt_response_doc': {'series': {'Уровень жидкости|line': {'color': '#a31bc8'}}},
        'fmt_gdi_doc': {
            'chart': {'plot_background': '#fcdda2'},
            'axes': {'x': {'min': '0', 'max': '100', 'step': '25'}},
            'series': {'Замеры|points': {'color': '#123abc', 'size': 12}},
        },
    }
    plan = client.post(url + '/plan', json={'form': form}).json()
    studies = [c for c in plan['charts'] if c['module'] == 'gdi']
    assert len(studies) == 2
    for c in studies:
        r = client.post(url + '/chart', json={'form': form, 'chart': c['name'], 'module': 'gdi', 'for_format': True})
        assert r.status_code == 200, r.text
        assert any(s.get('format_label') == 'Замеры' and s['ids'] for s in r.json()['series'])
    client.post(url + '/memory', json={'form': form, 'tab': 'gdi'}).raise_for_status()
    assert client.get(url + '/memory').json()['form']['fmt_gdi_doc'] == form['fmt_gdi_doc']
    response = client.post(url + '/archive', json={'form': form})
    assert response.status_code == 200, response.text
    result = response.json()
    assert not result['errors'], result['errors']
    formatted = response_levels = unformatted = 0
    for name in result['files']:
        if not name.endswith('.zip'):
            continue
        with zipfile.ZipFile(store.path(pid) / 'exports' / name) as archive:
            for member in archive.namelist():
                if member.endswith('.svg'):
                    svg = archive.read(member)
                    if b'#fcdda2' in svg:
                        assert b'#123abc' in svg
                        formatted += 1
                    elif b'#a31bc8' in svg:
                        response_levels += 1
                    else:
                        unformatted += 1
    assert formatted == len(studies)
    assert response_levels == sum(c['module'] == 'response' and c['name'].endswith(' · уровень') for c in plan['charts'])
    assert response_levels > 1 and unformatted


def test_response_export_uses_filtered_series_and_fits_all_axes(env):
    from xml.etree import ElementTree

    from atlas.domain import DatasetKind

    client, pid, projects, store = env
    dates = pd.date_range('2025-01-01', periods=6, freq='MS')
    frames = {
        'response': pd.DataFrame({
            'well': ['31'] * 3 + ['45'] * 3, 'horizon': ['А'] * 6, 'date': dates,
            'pressure': [10, 123456, 17, 30, 32, 36], 'level': [9, 19, 29, 90, 110, 120],
        }),
        'pressure_survey': pd.DataFrame({
            'well': '47', 'group': 'ГСП-1', 'date': dates, 'p_res': [14, 234567, 16, 39, 42, 44],
        }),
        'object_pressure': pd.DataFrame({'date': dates, 'pressure': 345678}),
    }
    settings = store.manifest(pid)['settings']
    store.commit(pid, frames=frames, settings=settings)
    url = f'/api/projects/{pid}/export'
    form = {'modules': ['response'], 'response_split': 'well', 'response_view': 'combined',
            'formats': ['svg', 'csv'], 'dpi': 300,
            'fmt_response_doc': {'chart': {'y_fit': 'data-exact', 'y_intervals': 7}},
            'fmt_response_axes': {'y': {'min': 0, 'max': 999}, 'y2': {'min': 0, 'max': 999}}}
    names = [row['name'] for row in client.post(url + '/plan', json={'form': form}).json()['charts']]
    assert names == ['31 · уровень и давление', '45 · уровень и давление']

    def chart(name, values=form):
        reply = client.post(url + '/chart', json={'form': values, 'chart': name})
        assert reply.status_code == 200, reply.text
        return reply.json()

    # Прогреваем тот же график до исключения и используем тот же выбор после пересборки проекта.
    assert chart(names[0])['y']['maximum'] >= 234567
    raw = projects.data(pid).raw
    point = raw[DatasetKind.RESPONSE].loc[lambda d: d.pressure.eq(123456), '_point_id'].item()
    survey = raw[DatasetKind.PRESSURE_SURVEY].loc[lambda d: d.p_res.eq(234567), '_point_id'].item()
    for kind, identifier in [('response', point + ':pressure'), ('pressure_survey', survey)]:
        r = client.post(f'/api/projects/{pid}/exclusions', json={'dataset': kind, 'add': [identifier]})
        assert r.json()['added'] == 1, r.text

    ranges_with_seven = []
    for exclusions in (True, False):
        selected = {**form, 'exclusions': exclusions}
        ranges_with_seven = []
        for name, expected in zip(names, (((10, 17), (9, 29)), ((30, 44), (90, 120)))):
            shown = chart(name, selected)
            ranges = []
            for side, limits in zip(('y', 'y2'), expected):
                axis = shown[side]
                bounds = (axis['minimum'], axis['maximum'])
                assert bounds[0] <= limits[0] <= limits[1] <= bounds[1]
                assert all(float(v).is_integer() for v in (*bounds, axis['step']))
                assert (bounds[1] - bounds[0]) / axis['step'] == pytest.approx(7)
                ranges.append(bounds)
                samples = [v for s in shown['series'] if s['axis'] == side for v in s['y'] if v is not None]
                assert (min(samples), max(samples)) == limits
            ranges_with_seven.append(ranges)
            assert shown['y2']['inverse']
        series = chart(names[0], selected)['series']
        assert all(point + ':pressure' not in (s['ids'] or []) for s in series)
        assert any(point + ':level' in (s['ids'] or []) and 19 in s['y'] for s in series)
        assert next(s['y'] for s in series if s['name'] == 'Пластовое давление объекта') == [14, 16]

    auto = chart(names[0], {**form, 'fmt_response_doc': {'chart': {'y_fit': 'auto', 'y_intervals': 6}}})
    for name in ('y', 'y2'):
        axis = auto[name]
        assert (axis['maximum'] - axis['minimum']) / axis['step'] == pytest.approx(6)
        assert all(float(axis[key]).is_integer() for key in ('minimum', 'maximum', 'step'))

    four = chart(names[0], {**form, 'fmt_response_doc': {'chart': {'y_fit': 'data-exact', 'y_intervals': 4}}})
    for name, step_7 in zip(('y', 'y2'), ((b-a)/7 for a,b in ranges_with_seven[0])):
        axis = four[name]
        assert (axis['maximum'] - axis['minimum']) / axis['step'] == pytest.approx(4)
        assert float(axis['step']).is_integer() and axis['step'] != pytest.approx(step_7)

    download = client.post(url + '/archive', json={'form': {**form, 'exclusions': False}})
    assert download.status_code == 200, download.text
    assert not download.json()['errors']
    with zipfile.ZipFile(store.path(pid) / 'exports' / download.json()['files'][0]) as archive:
        names = archive.namelist()
        svgs = sorted(name for name in names if name.endswith('.svg'))
        assert len(svgs) == 2
        namespace = {'svg': 'http://www.w3.org/2000/svg'}
        for path, expected in zip(svgs, ranges_with_seven):
            root = ElementTree.fromstring(archive.read(path))
            for index, limits in enumerate(expected, start=2):
                axis = root.find(f".//svg:g[@id='matplotlib.axis_{index}']", namespace)
                ticks = [float(t.text.replace(',', '.')) for t in axis.findall('.//svg:text', namespace)[:-1]]
                assert len(ticks) == 8
                assert all(v.is_integer() for v in ticks)
                assert (min(ticks), max(ticks)) == limits
        chart_data = [archive.read(name) for name in names if name.endswith('.csv')]
        assert chart_data and all(forbidden not in payload for payload in chart_data
                                  for forbidden in (b'123456', b'234567', b'345678'))


def test_response_pressure_sources_are_independently_formatted(env):
    client, pid, _, store = env
    dates = pd.date_range('2025-01-01', periods=2, freq='MS')
    frame = pd.DataFrame({
        'well': ['31', '31', '45', '45'], 'horizon': ['А'] * 4, 'date': list(dates) * 2,
        'pressure': [50, 55, 70, 75], 'level': [9, 19, 29, 39],
    })
    settings = {**store.manifest(pid)['settings'], 'manometer_wells': ['45']}
    store.commit(pid, frames={'response': frame}, settings=settings)
    url = f'/api/projects/{pid}/export'
    pressure_labels = {31: 'Давление (пересчет)', 45: 'Давление (глубинный манометр)'}
    form = {
        'modules': ['response'], 'response_split': 'well', 'response_view': 'pressure',
        'formats': ['svg'], 'dpi': 300,
        'fmt_response_doc': {'series': {
            'Пластовое давление|line': {'color': '#aabbcc', 'width': 3},
            pressure_labels[45] + '|line': {'color': '#ff1133'},
        }},
    }
    chart_names = client.post(url + '/plan', json={'form': form}).json()['charts']
    for entry, (well, expected) in zip(chart_names, pressure_labels.items(), strict=True):
        assert entry['name'].startswith(f'{well} · ')
        r = client.post(url + '/chart', json={'form': form, 'chart': entry['name'], 'module': 'response', 'for_format': True})
        assert r.status_code == 200, r.text
        assert [(s['name'], s['format_label']) for s in r.json()['series']] == [(expected, expected)]

    download = client.post(url + '/archive', json={'form': form})
    assert download.status_code == 200, download.text
    assert not download.json()['errors']
    with zipfile.ZipFile(store.path(pid) / 'exports' / download.json()['files'][0]) as archive:
        svgs = sorted(name for name in archive.namelist() if name.endswith('.svg'))
        assert len(svgs) == 2
        for i, expected in enumerate((b'#aabbcc', b'#ff1133')):
            svg = archive.read(svgs[i])
            assert expected in svg
            assert (b'#ff1133' if i == 0 else b'#aabbcc') not in svg
            assert b'stroke-width: 1.8' in svg  # Толщина из прежнего общего оформления сохранена.

    combined = {**form, 'response_split': 'horizon', 'response_view': 'combined'}
    entry = client.post(url + '/plan', json={'form': combined}).json()['charts'][0]
    r = client.post(url + '/chart', json={'form': combined, 'chart': entry['name'], 'module': 'response', 'for_format': True})
    assert r.status_code == 200, r.text
    assert {s['format_label'] for s in r.json()['series']} == {'Уровень жидкости', *pressure_labels.values()}

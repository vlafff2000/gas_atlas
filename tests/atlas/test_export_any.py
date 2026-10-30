"""«Экспорт» → «Любой график»: реестр графиков разделов и выгрузка одного графика с ручными настройками."""
import pytest
from starlette.testclient import TestClient

import atlas.api_projects as api_projects
from atlas.api import create_app
from atlas.contract import ParamError
from atlas.export_any import settings_of
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    client = TestClient(create_app(Projects(tmp_path / 'storage')))
    return client, client.post('/api/projects/demo').json()['id']


PARAMS = {'wells': ['31', '70']}
MODULE = 'gdi'


def first_chart(client, pid, module=MODULE):
    found = client.post(f'/api/projects/{pid}/export/any/charts', json={'module': module, 'params': PARAMS}).json()
    assert found['charts'], found
    return found['charts'][0]


def test_registry_lists_modules_and_charts(env):
    client, pid = env
    mods = client.get(f'/api/projects/{pid}/export/any/modules').json()['modules']
    ids = {m['id'] for m in mods}
    assert {'production', 'gdi'} <= ids and all('ready' in m for m in mods)
    chart = first_chart(client, pid)
    assert chart['kind'] == 'chart' and chart['series'] > 0 and 'y' in chart['axes']


def test_file_png_size_and_title(env):
    client, pid = env
    chart = first_chart(client, pid)
    def png(settings):
        r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': MODULE, 'params': PARAMS, 'chart': chart['id'], 'settings': settings})
        assert r.status_code == 200, r.text
        return r
    small = png({'dpi': 150, 'width': 100, 'height': 80, 'chart': {'title': 'Мой заголовок', 'legend': 'hide', 'grid': 'none'}})
    wide = png({'dpi': 150, 'width': 200, 'height': 80, 'axes': {'y': {'min': '0', 'max': '500'}}})
    assert small.content[:4] == b'\x89PNG' and small.headers['content-type'] == 'image/png'
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(wide.content)).width > Image.open(io.BytesIO(small.content)).width


def test_file_csv_and_unknown_chart(env):
    client, pid = env
    chart = first_chart(client, pid)
    r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': MODULE, 'params': PARAMS, 'chart': chart['id'], 'settings': {'format': 'csv'}})
    assert r.status_code == 200 and 'csv' in r.headers['content-type']
    r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': MODULE, 'params': PARAMS, 'chart': 'нет такого'})
    assert r.status_code == 404


@pytest.mark.parametrize('bad', [{'format': 'bmp'}, {'dpi': 111}, {'width': 5}, {'font': 'comic'}, {'look': 'neon'},
                                 {'chart': {'background': 'red'}}, {'axes': {'y': {'font': 'x'}}}])
def test_settings_validated(bad):
    with pytest.raises(ParamError):
        settings_of(bad)


def test_size_preset_and_manual_override():
    assert settings_of({'size': 'a4-half'})['width'] == 170 and settings_of({'size': 'a4-half'})['height'] == 100
    assert settings_of({'size': 'a4-half', 'width': 120})['width'] == 120


def test_an_chart_with_table_settings(env):
    """Графики АН со столбцами и таблицей под графиком: размер, шрифт, высота строк и показ таблицы меняют рисунок."""
    import io
    from PIL import Image
    client, pid = env
    params = {'kind': 'withdrawal', 'periods': ['2023-2024']}
    found = client.post(f'/api/projects/{pid}/export/any/charts', json={'module': 'an_report', 'params': params}).json()
    withtable = [c for c in found['charts'] if c['table'] and c['special']]
    assert withtable, [c['id'] for c in found['charts']]
    def shot(settings):
        r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': 'an_report', 'params': params, 'chart': withtable[0]['id'], 'settings': {'dpi': 150, **settings}})
        assert r.status_code == 200, r.text
        return Image.open(io.BytesIO(r.content))
    base = shot({})
    assert shot({'width': 100, 'height': 80}).width < base.width      # поля обрезаются по содержимому, поэтому не равенство
    assert shot({'table': {'show': False}}).height < base.height
    assert shot({'table': {'row': 2, 'font_size': 12}, 'font': 'times'}).height > base.height


def test_series_look_and_hidden(env):
    """Вид ряда и скрытие ряда из настроек действуют на файл; реестр отдаёт ряды с их текущим цветом."""
    import io
    from PIL import Image
    client, pid = env
    chart = first_chart(client, pid)
    item = chart['items'][0]
    assert item['color'].startswith('#') and item['key'].endswith(item['kind'])
    def shot(view):
        r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': MODULE, 'params': PARAMS, 'chart': chart['id'],
                                                                      'settings': {'dpi': 150, 'view': view}})
        assert r.status_code == 200, r.text
        return Image.open(io.BytesIO(r.content)).convert('RGB').tobytes()
    base = shot({})
    assert shot({'looks': {item['key']: {'color': '#ff00ff', 'width': 5}}}) != base
    assert shot({'hidden': [item['group']]}) != base


def test_histogram_xlsx_has_well_labels_and_plain_legend(env, tmp_path):
    """Гистограммы в Excel: подписи скважин (или периодов) по оси X и имена рядов в легенде без единиц."""
    import io
    import openpyxl
    from atlas.modules._production import PRODUCTION, groups_of, periods_of, wells_of
    client, pid = env
    data = Projects(tmp_path / 'storage').data(pid)
    frame = data[PRODUCTION]
    params = {'kind': 'withdrawal', 'groups': groups_of(frame, data.mapping), 'wells': wells_of(frame)[:3], 'periods': periods_of(frame, 'withdrawal')[-2:]}
    for axis in ('well', 'period'):
        p = {**params, 'axis': axis}
        chart = client.post(f'/api/projects/{pid}/export/any/charts', json={'module': 'histograms', 'params': p}).json()['charts'][0]
        r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': 'histograms', 'params': p, 'chart': chart['id'], 'settings': {'format': 'xlsx'}})
        assert r.status_code == 200, r.text
        book = openpyxl.load_workbook(io.BytesIO(r.content))
        for series in book['График']._charts[0].series:
            assert series.cat is not None and series.cat.numRef.f.startswith("'Данные'!$A$")     # подписи из первой колонки
            assert 'тыс' not in str(book['Данные'][series.tx.strRef.f.split('!')[1]].value)


def test_grid_minor_lines_and_axis_text_style(env):
    """Сетка: толщина и цвет основной сетки, доп. линии скрываются и показываются; оси — жирный и курсив."""
    client, pid = env
    chart = first_chart(client, pid)
    def png(settings):
        r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': MODULE, 'params': PARAMS, 'chart': chart['id'], 'settings': settings})
        assert r.status_code == 200, r.text
        return r.content
    base = png({'dpi': 150, 'chart': {'grid': 'both'}})
    minor = png({'dpi': 150, 'chart': {'grid': 'both', 'minor_grid': 'show', 'minor_grid_color': '#ff0000', 'minor_grid_width': 2}})
    hidden = png({'dpi': 150, 'chart': {'grid': 'both', 'minor_grid': 'hide'}})
    styled = png({'dpi': 150, 'chart': {'grid': 'both', 'grid_width': 3, 'grid_color': '#00ff00'},
                  'axes': {'y': {'title_bold': True, 'title_italic': True, 'tick_bold': True, 'tick_italic': True}}})
    assert minor != base and minor != hidden and styled not in (base, minor)


@pytest.mark.parametrize('bad', [{'grid_width': 9}, {'minor_grid': 'maybe'}, {'minor_grid_color': 'red'}])
def test_grid_settings_validated(bad):
    from atlas.chart_style import clean_chart
    with pytest.raises(ParamError):
        clean_chart(bad)


def test_manual_bar_color_survives_excel_look(env):
    """Гистограмма по годам: ручной цвет года остаётся в файле и при виде «как Excel»; остальные годы — палитра Excel, без пропусков."""
    import re
    client, pid = env
    groups = client.post('/api/modules/production/options', json={'project': pid, 'param': 'groups', 'params': {}}).json()
    params = dict(kind='withdrawal', groups=groups, wells=['31', '45', '540'], periods=['2023-2024', '2024-2025', '2025-2026'],
                  hist_size='Все', direction='number', axis='well')
    found = client.post(f'/api/projects/{pid}/export/any/charts', json={'module': 'histograms', 'params': params}).json()
    chart = found['charts'][0]
    manual = next(i for i in chart['items'] if i['name'] == '2024-2025')
    view = {'looks': {manual['key']: {'color': '#123456'}}}

    def fills(look):
        r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': 'histograms', 'params': params, 'chart': chart['id'],
                                                                      'settings': {'format': 'svg', 'look': look, 'view': view}})
        assert r.status_code == 200, r.text
        svg = r.content.decode('utf8')
        return set(re.findall(r'fill: ?(#[0-9a-fA-F]{6})', svg)) | set(re.findall(r'fill="(#[0-9a-fA-F]{6})"', svg))

    assert '#123456' in fills('default')
    assert '#123456' in fills('excel')


def test_saved_builder_layouts_are_charts(env):
    """Сохранённые макеты конструктора доступны как «раздел»: каждый макет — график; имя файла задаёт инженер."""
    client, pid = env
    ids = lambda: {m['id'] for m in client.get(f'/api/projects/{pid}/export/any/modules').json()['modules']}
    assert 'builder-saved' not in ids()
    layout = {'series': [{'dataset': 'production', 'y': 'q', 'wells': ['31']}], 'title': 'Дебит 31'}
    assert client.post(f'/api/projects/{pid}/builder/layouts', json={'name': 'Дебит', 'layout': layout}).status_code == 200
    assert 'builder-saved' in ids()
    found = client.post(f'/api/projects/{pid}/export/any/charts', json={'module': 'builder-saved', 'params': {}}).json()
    assert len(found['charts']) == 1 and found['charts'][0]['id'].startswith('layout-')
    r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': 'builder-saved', 'params': {}, 'chart': found['charts'][0]['id'],
                                                                'settings': {'dpi': 150, 'filename': 'мой/график'}})
    assert r.status_code == 200 and r.content[:4] == b'\x89PNG'
    assert 'filename*=UTF-8' in r.headers['content-disposition'] and '%2F' not in r.headers['content-disposition'].split("''")[1]


def test_facets_listed_and_special_style_applied():
    """Признаки рядов отдаются реестру; у тепловой карты действуют размер текста в ячейках и общее оформление (фон, заголовок)."""
    import io
    from PIL import Image
    from atlas.contract import Axis, Chart, HeatMap, Series
    from atlas.export_any import describe, export
    chart = Chart('h', 'Карта', Axis('Сезон'), Axis('ГСП'),
                  series=[Series('a', [1, 2], [1, 2], facets={'Период': '2023'}), Series('b', [1, 2], [2, 3], facets={'Период': '2024'})])
    assert describe(chart)['facets'] == [{'name': 'Период', 'values': ['2023', '2024']}]
    heat = Chart('heat', 'Карта', Axis('Сезон'), Axis('ГСП'), heat=HeatMap(['ГСП-1'], ['2023', '2024'], [[1.0, 2.0]], [['1', '2']]))
    def shot(settings):
        content, name, _, _ = export(heat, {'dpi': 150, **settings})
        return Image.open(io.BytesIO(content)).convert('RGB')
    plain = shot({})
    painted = shot({'cell_size': 20, 'chart': {'background': '#ffeecc'}})
    assert plain.getpixel((2, 2)) == (255, 255, 255) and painted.getpixel((2, 2)) == (255, 238, 204)


def test_special_chart_legend_position_applies(env):
    """Положение легенды у столбцов с сегментами (АН): «снизу», «сверху», «справа» дают разные картинки, а не всегда «справа»."""
    client, pid = env
    params = {'kind': 'withdrawal', 'periods': ['2025-2026'], 'class_chart': 'box'}
    found = client.post(f'/api/projects/{pid}/export/any/charts', json={'module': 'an_report', 'params': params}).json()['charts']
    assert any(c['id'].startswith('an-class-share') for c in found)       # график классов доступен при выбранном виде «Классы производительности»
    chart = next(c['id'] for c in found if c['id'].startswith('an-class-share'))
    sizes = {}
    for place in ('bottom', 'top', 'right'):
        r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': 'an_report', 'params': params, 'chart': chart,
                                                                      'settings': {'dpi': 150, 'chart': {'legend': place}}})
        assert r.status_code == 200, r.text
        sizes[place] = r.content
    assert len(set(sizes.values())) == 3

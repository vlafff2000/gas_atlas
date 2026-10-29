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

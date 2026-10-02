from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from app.core.storage import Store
from app.core.demo import demo_frames
from app.core import config

APP=Path(__file__).resolve().parents[1]/'app/main.py'

@pytest.fixture
def ui(tmp_path,monkeypatch):
    root=tmp_path/'ui'; monkeypatch.setattr(config,'STORAGE',root)
    store=Store(root); pid=store.create('Проверка интерфейса',demo=True)
    store.commit(pid,demo_frames(),settings={**config.DEFAULT_SETTINGS,'working_horizons':['Окский']})
    at=AppTest.from_file(str(APP),default_timeout=30).run()
    assert not at.exception
    return at

@pytest.mark.parametrize('page',['Импорт данных','Динамика','ГДИ','Реагирование','Аналитика фонда','Группы','Экспорт','Исключенные точки','Настройки'])
def test_each_page(ui,page):
    ui.sidebar.radio[0].set_value(page).run()
    assert not ui.exception

def test_empty_project_create(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'STORAGE',tmp_path/'empty')
    at=AppTest.from_file(str(APP),default_timeout=30).run(); assert not at.exception
    at.text_input[0].set_value('Новый объект')
    next(b for b in at.button if b.label=='Создать').click().run()
    assert not at.exception and at.title[0].value=='Новый объект'

def test_import_paste_apply(ui):
    ui.sidebar.radio[0].set_value('Импорт данных').run()
    ui.text_area[0].set_value('Скважина\tДата\tQ\tРпл\tРзаб\n999\t01.01.2026\t100\t75\t70\n').run()
    next(b for b in ui.button if b.label=='Проверить файлы').click().run()
    assert not ui.exception
    next(b for b in ui.button if b.label=='Применить загрузку').click().run()
    assert not ui.exception
    ui.sidebar.radio[0].set_value('ГДИ').run()
    assert '999' in ui.multiselect[0].options

def test_export_generation(ui):
    ui.sidebar.radio[0].set_value('Экспорт').run()
    next(x for x in ui.multiselect if x.label=='Модули').set_value(['gdi'])
    next(x for x in ui.multiselect if x.label=='Скважины').set_value(['31'])
    next(x for x in ui.multiselect if x.label=='Форматы графиков').set_value(['svg'])
    next(b for b in ui.button if b.label=='Сформировать архив').click().run(timeout=40)
    assert not ui.exception and len(ui.success)>0

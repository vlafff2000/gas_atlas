from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from app.core.storage import Store
from app.core.demo import demo_frames
from app.core import config
from app.ui import navigation

APP=Path(__file__).resolve().parents[1]/'app/main.py'

@pytest.fixture
def ui(tmp_path,monkeypatch):
    root=tmp_path/'ui'; monkeypatch.setattr(config,'STORAGE',root)
    store=Store(root); pid=store.create('Проверка интерфейса',demo=True)
    store.commit(pid,demo_frames(),settings={**config.DEFAULT_SETTINGS,'working_horizons':['Окский'],'visible_pages':navigation.PAGES})
    at=AppTest.from_file(str(APP),default_timeout=30).run()
    assert not at.exception
    return at

@pytest.mark.parametrize('page',['Импорт данных','Производительность скважин','ГДИ','Графики реагирования','Аналитика фонда','Группы','Экспорт','Исключенные точки','Настройки'])
def test_each_page(ui,page):
    ui.sidebar.radio[0].set_value(page).run()
    assert not ui.exception

def test_empty_project_create(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'STORAGE',tmp_path/'empty')
    at=AppTest.from_file(str(APP),default_timeout=30).run(); assert not at.exception
    at.text_input[0].set_value('Новый объект')
    next(b for b in at.button if b.label=='Создать').click().run()
    assert not at.exception and [p['name'] for p in Store(config.STORAGE).list()]==['Новый объект']

def test_import_paste_apply(ui):
    ui.sidebar.radio[0].set_value('Импорт данных').run()
    ui.text_area[0].set_value('Скважина\tДата\tQ\tРпл\tРзаб\n999\t01.01.2026\t100\t75\t70\n').run()
    next(b for b in ui.button if b.label=='Проверить файлы').click().run()
    assert not ui.exception
    next(b for b in ui.button if b.label=='Применить загрузку').click().run()
    assert not ui.exception
    assert any('Данные сохранены' in s.value for s in ui.success),([e.value for e in ui.error],[w.value for w in ui.warning],[s.value for s in ui.success])

def test_export_generation(ui):
    ui.sidebar.radio[0].set_value('Экспорт').run()
    next(x for x in ui.checkbox if x.label=='Включить ГДИ в выгрузку').set_value(True).run()
    next(x for x in ui.multiselect if x.label=='Форматы графиков').set_value(['svg'])
    next(b for b in ui.button if b.label=='Сформировать архив').click().run(timeout=60)
    assert not ui.exception and len(ui.success)>0

def test_crossplot_page_with_pressure_data(tmp_path,ui):
    from tools.make_pressure_samples import make_book
    from app.ui import pressure_quick_import as q
    files={}
    for i in range(2):
        path=tmp_path/('Объект_{}.xlsx'.format(i+1));make_book(path,i,6,30);files[str(path)]=(path.name,path.read_bytes())
    cache={sha:q.parse_file(n,c) for sha,(n,c) in files.items()}
    data,*_=q.assemble(q.build_rows(files,cache,{},'P'),cache,'first')
    store=Store(config.STORAGE);pid=store.list()[0]['id']
    store.commit(pid,{**demo_frames(),'pressure_match':data},action='test')
    ui.sidebar.radio[0].set_value('Кроссплот давлений').run()
    assert not ui.exception
    assert [m.value for m in ui.metric][:1]==['720']
    for tab in ['Динамика','Распределения','Объекты','Статистика','Кроссплот']:
        next(r for r in ui.radio if r.label=='Представление').set_value(tab).run()
        assert not ui.exception,tab

def test_crossplot_import_lives_in_import_section(ui):
    ui.sidebar.radio[0].set_value('Кроссплот давлений').run()
    assert not ui.exception and not any(r.label=='Способ загрузки' for r in ui.radio)
    next(b for b in ui.button if b.label=='Открыть импорт данных давлений').click().run()
    assert not ui.exception and ui.sidebar.radio[0].value=='Импорт данных'
    assert any(r.label=='Способ загрузки' for r in ui.radio)

def test_crossplot_demo_variant_in_demo_project(ui):
    ui.sidebar.radio[0].set_value('Импорт данных').run()
    next(r for r in ui.radio if r.label=='Раздел импорта').set_value('Данные давлений (кроссплот)').run()
    next(s for s in ui.selectbox if s.label=='Вариант').set_value('objects').run()
    next(b for b in ui.button if b.label=='Загрузить вариант в демонстрационный проект').click().run(timeout=60)
    assert not ui.exception
    data=Store(config.STORAGE).load(Store(config.STORAGE).list()[0]['id'])[1]['pressure_match']
    assert data.object.nunique()==3
    ui.sidebar.radio[0].set_value('Кроссплот давлений').run()
    assert not ui.exception and int(ui.metric[0].value)>0

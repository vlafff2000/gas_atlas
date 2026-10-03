from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

import hashlib
import datetime as dt
import json
import shutil
import tempfile
import numpy as np
import pandas as pd
import streamlit as st
from app.core.config import VERSION,STORAGE,DEFAULT_SETTINGS,MODULES,ordered
from app.core.storage import Store
from app.core.demo import demo_frames,well_demo_frames
from app.core import exclusions,reporting
from app.core.export import csv_bytes,xlsx_bytes,figure_bytes,export_zip,safe_name
from app.modules import production,gdi,response,charts,group_analysis
from app.ui.theme import apply,heading
from app.ui.point_tools import PointControls
from app.core.performance import context,select_wells,index_for,chart_cache
from app.core.logging_utils import setup,show_error
from app.ui.selection import choose_group_wells,histogram_size,parse_wells,checklist,paginate
from app.ui import navigation
from app.ui.filters import filter_bar

st.set_page_config(page_title='Газовый атлас',page_icon='◈',layout='wide',initial_sidebar_state='expanded',menu_items={})
apply(); store=Store(STORAGE);log_path=setup(ROOT)
for queued,target in [('next_project','project_select'),('next_nav','nav')]:
    if queued in st.session_state: st.session_state[target]=st.session_state.pop(queued)

def plot(fig,key):
    return point_controls.plot(charts.style_figure(fig,chart_style,copy_figure=False),key,copy_figure=False)

def show_frame(df,limit=5000):
    if len(df)>limit: st.caption(f'Показаны первые {limit:,} из {len(df):,} строк. Экспорт содержит весь выбранный набор.')
    st.dataframe(df.head(limit),hide_index=True,use_container_width=True)

def metrics(frames):
    values=[('Скважин',len(catalog['wells'])),('Динамика',m['tables'].get('production',0)),('Точек ГДИ',m['tables'].get('gdi',0)),('Замеров уровней',m['tables'].get('response',0))]
    for c,(label,n) in zip(st.columns(4),values): c.metric(label,f'{n:,}'.replace(',',' '))

def make_demo():
    pid=store.create('Демонстрационный объект',demo=True)
    settings={**DEFAULT_SETTINGS,'working_horizons':['Окский']}
    from app.core import pressure_demo
    frames=well_demo_frames();frames['pressure_match']=pressure_demo.frame()
    store.commit(pid,frames,settings=settings,action='Загрузка демонстрационных данных')
    st.session_state['next_project']=pid; st.rerun()

projects=store.list()
with st.sidebar:
    st.markdown('## ◈ Газовый атлас')
    st.caption('Исследования фонда скважин')
    pids=[p['id'] for p in projects]; names={p['id']:p['name'] for p in projects}
    if pids:
        if st.session_state.get('project_select') not in pids: st.session_state['project_select']=pids[0]
        pid=st.selectbox('Проект',pids,format_func=lambda p:names[p],key='project_select')
    else: pid=None
    with st.expander('Новый проект'):
        with st.form('new_project'):
            name=st.text_input('Название объекта')
            if st.form_submit_button('Создать',type='primary'):
                if name.strip():
                    st.session_state['next_project']=store.create(name); st.rerun()
                else: st.error('Введите название объекта')
    pages=navigation.visible(store.manifest(pid).get('settings',{})) if pid else navigation.DEFAULT
    if st.session_state.get('nav') in navigation.ALIASES:st.session_state['nav']=navigation.ALIASES[st.session_state['nav']]
    if st.session_state.get('nav') not in pages:st.session_state['nav']=pages[0]
    page=st.radio('Раздел',pages,key='nav',label_visibility='collapsed')
    fast_mode=st.toggle('Быстрый просмотр',value=True,key='fast_mode',help='Использовать подготовленные индексы, расчеты и графики. После изменения данных или исключений результаты обновляются автоматически.')
    memory_mode=st.selectbox('Хранение данных',['ram','hybrid'],format_func=lambda x:'Весь активный проект в RAM' if x=='ram' else 'Гибридный: модули по мере открытия',key='memory_mode')
    memory_budget=st.number_input('Лимит предварительной загрузки, ГБ',min_value=0.5,max_value=64.,value=2.,step=0.5,key='memory_budget',help='Если оценка памяти выше лимита, используется гибридный режим. Лимит относится к предварительной загрузке, а не ко всему процессу Python.')
    from app.ui.filters import pin_toggle
    pin_toggle()
    click_edit=st.toggle('Исключать точки кликом',value=False,key='click_edit',help='Клик по измеренной точке исключает ее из расчетов. Вернуть точки можно в разделе «Исключенные точки».')
    st.divider(); st.caption('Локальная работа · версия '+VERSION)

if not pid:
    heading('Ваш объект. Все исследования.','Создайте проект или откройте демонстрационный набор, чтобы ознакомиться с возможностями.')
    if st.button('Открыть демонстрационный объект',type='primary'): make_demo()
    st.info('Динамика отбора и закачки, анализ ГДИ и реагирование контрольных горизонтов — в одном проекте.')
    restore=st.file_uploader('Открыть резервную копию или старый проект .gas.json',type=['zip','json'])
    if restore:
        from app.ui.import_editor import preview_project
        preview_project(restore)
    if restore and st.button('Восстановить'):
        try:
            st.session_state['next_project']=store.import_legacy(restore.getvalue()) if restore.name.endswith('.json') else store.restore(restore.getvalue())
            st.rerun()
        except Exception as e: show_error(str(e))
    st.stop()

m=store.manifest(pid); settings={**DEFAULT_SETTINGS,**m['settings']};m['settings']=settings;revision=m['revision']
active_module={'Производительность скважин':'production','Гистограммы по эксплуатации скважин':'production','ГДИ':'gdi','Графики реагирования':'response'}.get(page)
prepare_key=pid+'_prepared_'+str(active_module)
prepare_signature=json.dumps([m.get('snapshot'),sorted(settings.get('excluded_points',{})),settings['season_start'],settings['season_end']],default=str)
progress=st.progress(0,text='Чтение структуры проекта…') if st.session_state.get(prepare_key)!=prepare_signature else None
with st.spinner('Подготовка данных и индексов…'):
    project,raw_frames,frames=context(STORAGE,pid,m,fast_mode)
    if memory_mode=='ram' and fast_mode:
        loaded=project.preload(settings,int(memory_budget*1024**3))
        if not loaded:st.info('Оценка памяти проекта выше лимита предварительной загрузки. Используется гибридный режим; лимит можно увеличить в боковой панели.')
    catalog=project.catalog()
    if progress:progress.progress(.4,text='Подготовка выбранного раздела…')
    if active_module in frames:active_data=frames[active_module]
    if progress:progress.progress(1.,text='Данные готовы');progress.empty()
    st.session_state[prepare_key]=prepare_signature
with st.sidebar.expander('Память и скорость'):
    info=project.diagnostics();st.caption('В RAM: '+str(len(info['loaded']))+'/'+str(info['modules'])+' модулей. Исходные таблицы: '+str(round(info['raw_bytes']/1024**2,1))+' МБ (без индексов и графиков).')
    st.caption('Чтений таблиц с диска: '+str(info['disk_reads'])+'; подготовок: '+str(info['view_builds'])+'; попаданий в кэш: '+str(info['view_hits']))
    def release_memory():
        project.release();st.session_state['memory_mode']='hybrid'
        for suffix in ('exp_report','exp_archive','exp_word_ready','passport_ready'):
            st.session_state.pop(pid+'_'+suffix,None)
    st.button('Освободить память проекта',on_click=release_memory)
mapping={w:dict(value) for w,value in catalog['mapping'].items()}
for w,value in m['groups'].items():mapping.setdefault(w,{}).update(value)
chart_style={**{'grid':True,'legend':True,'points':True},**settings.get('chart_style',{})}
with st.sidebar.expander('Оформление графиков'):
    st.checkbox('Стиль первой версии',value=True,key='classic_ui')
    for field,label in [('points','Показывать точки'),('legend','Легенда'),('grid','Сетка')]:
        chart_style[field]=st.checkbox(label,chart_style.get(field,True),key=pid+'_style_'+field)
    if st.button('Сохранить оформление',key=pid+'_style_save'):
        store.commit(pid,settings={**settings,'chart_style':chart_style},expected=revision,action='Оформление графиков');st.rerun()
key=lambda value:pid+'_'+value
if page!='Экспорт':st.session_state.pop(key('exp_focus_module'),None)
point_controls=PointControls(store,pid,revision,settings,raw_frames,click_edit)
point_controls.notify()
viewer_configs=st.session_state.setdefault(key('viewer_configs'),{})
viewer_configs['style']=chart_style
if settings.get('excluded_points'):
    st.caption(f'Ручной фильтр: исключено {len(settings["excluded_points"])} показателей. Исходные значения сохранены; восстановление — в разделе «Исключенные точки».')
if click_edit:st.info('Режим исключения включен: нажмите на измеренную точку. Расчетная кривая сама по себе не исключается.')
if m['demo']: st.warning('ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ. Для рабочих файлов создайте отдельный проект.')

def remember_panel(name,value):
    cfg={**settings,'panels':{**settings.get('panels',{}),name:value}}
    store.commit(pid,settings=cfg,expected=revision,action='Сохранение фильтров'); st.success('Фильтры сохранены')

@st.fragment
def quick_download(fig,name):
    with st.expander('Скачать этот график'):
        c1,c2,c3=st.columns(3)
        fmt=c1.selectbox('Формат',['svg','pdf','png'],key=key(name+'_fmt'))
        dpi=c2.selectbox('DPI',[300,600,1200],key=key(name+'_dpi'))
        if c3.button('Подготовить файл',key=key(name+'_prepare')):
            try:
                b=figure_bytes(charts.style_figure(fig,chart_style),fmt,dpi)
                st.download_button('Скачать '+fmt.upper(),b,safe_name(name)+'.'+fmt,key=key(name+'_download'))
            except Exception as e: show_error(str(e))

def empty(module):
    if module not in frames or frames[module].empty:
        st.info('Данные этого модуля еще не загружены. Откройте «Импорт данных».'); return True
    return False

if page=='Обзор':
    heading(m['name'],'Единый проект: исходные файлы, расчеты и настройки сохраняются на вашем компьютере.')
    metrics(frames)
    left,right=st.columns([2,1])
    with left:
        st.subheader('Состав проекта')
        rows=[]
        for mod,info in catalog['modules'].items():
            rows.append({'Модуль':MODULES[mod],'Строк':info['rows'],'Скважин':len(info['wells']),'С':info['start'],'По':info['end']})
        if rows: show_frame(pd.DataFrame(rows))
        else: st.info('Откройте «Импорт данных» и загрузите книгу Excel или текстовую таблицу.')
        st.subheader('История действий')
        history=store.history(pid); show_frame(history,100)
        calc=history[history['Действие'].eq('Расчет ГДИ')]
        if not calc.empty:
            chosen=st.selectbox('Открыть параметры расчета',calc.index.tolist(),format_func=lambda i:calc.loc[i,'Дата'])
            if st.button('Открыть расчет ГДИ'):
                details=json.loads(calc.loc[chosen,'Подробности'])
                st.session_state[key('gdi_wells')]=details['wells']; st.session_state[key('gdi_n')]=details['n']; st.session_state['next_nav']='ГДИ'; st.rerun()
    with right:
        st.subheader('Рабочие правила')
        st.write('Последний период — красный, предыдущие — синий, зеленый и оранжевый.')
        st.write('Средний дебит учитывает дни с положительным расходом. Накопленный объем считается по всему объекту.')
        st.write('Уровень жидкости отображается с перевернутой осью глубины.')
        if st.button('Создать отдельный демопроект'): make_demo()

elif page=='Импорт данных':
    from app.ui.general_import import render as import_page
    heading('Импорт данных','Простой режим: перетащите все файлы сразу. Подробный: настройка шапки и колонок каждого листа. Данные давлений для кроссплота — отдельный подраздел.')
    from app.ui.pressure_panel import IMPORT_SECTIONS,import_panel as pressure_import
    section=st.radio('Раздел импорта',IMPORT_SECTIONS,horizontal=True,key=key('import_section'),label_visibility='collapsed')
    if section==IMPORT_SECTIONS[0]:import_page(store,pid,m,raw_frames,key,ROOT,show_frame)
    else:pressure_import(store,pid,m,raw_frames,key)

elif page in ('Производительность скважин','Гистограммы по эксплуатации скважин'):
    from app.ui.production_view import render as production_view
    heading(page,'Сравнение периодов и расходов выбранных скважин и групп.')
    if not empty('production'):
        production_view(frames['production'],raw_frames,catalog,settings,mapping,point_controls,key,viewer_configs,chart_style,click_edit,quick_download,remember_panel,page=='Гистограммы по эксплуатации скважин')

elif page=='ГДИ':
    heading('Газодинамические исследования','ΔP² = Рпл² − Рзаб² = aQ + bQ². Коэффициенты БД и расчетные значения доступны для сравнения.')
    if not empty('gdi'):
        data=frames['gdi']; all_wells=ordered(catalog['modules']['gdi']['wells'])
        with filter_bar(pin=False):
            a,b,c=st.columns([2,1,1])
            saved=settings.get('panels',{}).get('gdi',{})
            with a:ws=checklist('Скважины',all_wells,[w for w in saved.get('wells',all_wells[:1]) if w in all_wells],key('gdi_wells'),lambda x:'№ '+x)
            n=b.selectbox('Последние даты исследований',[1,2,3,0],index=[1,2,3,0].index(saved.get('n',3)),format_func=lambda x:'Все' if x==0 else str(x),key=key('gdi_n'))
            orientation=c.selectbox('Оси',['standard','swapped'],index=0 if saved.get('orientation','standard')=='standard' else 1,format_func=lambda x:'X = Q, Y = ΔP²' if x=='standard' else 'X = ΔP², Y = Q')
            a,b,c=st.columns(3);curves=a.checkbox('Расчетные кривые',saved.get('curves',True));db_curves=b.checkbox('Кривые по коэффициентам БД',saved.get('db_curves',True));crosshair=c.checkbox('Перекрестная линейка',saved.get('crosshair',True))
            seasons=ordered(data.season[data.season.ne('')]) if 'season' in data else []
            season_filter=checklist('Сезоны из исходного файла (пусто — все)',seasons,[],key('gdi_seasons')) if seasons else []
            viewer_configs['gdi']={'wells':ws,'n':n,'orientation':orientation,'curves':curves,'db_curves':db_curves,'crosshair':crosshair,'seasons':season_filter}
            show_excluded=st.checkbox('Показывать исключенные точки',saved.get('show_excluded',True))
            viewer_configs['gdi']['show_excluded']=show_excluded
        chosen=gdi.select_studies(data,ws,n,season_filter)
        original_gdi=gdi.select_studies(raw_frames['gdi'],ws,n,season_filter)
        if chosen.empty: st.info('Выберите скважины с данными.')
        else:
            result=gdi.analyze(chosen,settings['r2_threshold'])
            for well in paginate(ws,'Страница графиков ГДИ',key('gdi_page')):
                fig=charts.gdi_chart(chosen,well,settings['r2_threshold'],orientation,curves,db_curves,crosshair,raw_df=original_gdi,show_excluded=show_excluded)
                plot(fig,key('gdi_'+well)); quick_download(fig,'ГДИ_'+well)
            st.subheader('Коэффициенты и качество')
            labels={'well':'Скважина','date':'Дата','method':'Метод','study':'Исследование','source':'Выбрано','r2':'R²','q_observed':'Qmax наблюд., тыс. м³/сут','q_free':'Qсв при Рзаб=0, тыс. м³/сут','note':'Замечания','points':'Всего точек','fit_points':'Точек подбора'}
            show_frame(result.rename(columns=labels))
            st.caption('Qmax наблюд. — максимальный измеренный расход. Qсв — формальная экстраполяция при Рзаб=0 в принятой системе давлений, не допустимый режим эксплуатации. Он не выводится без Рпл или при плохом качестве подбора. Две точки не дают независимой проверки качества модели.')
            st.download_button('Таблица ГДИ · XLSX',xlsx_bytes({'ГДИ':result.rename(columns=labels)}),'GDI_results.xlsx')
            if st.button('Сохранить расчет в историю'):
                store.event(pid,'Расчет ГДИ',{'wells':ws,'n':n,'threshold':settings['r2_threshold'],'seasons':season_filter})
                remember_panel('gdi',viewer_configs['gdi'])
            st.subheader('Сравнение с предыдущим исследованием')
            compare=gdi.comparisons(chosen); show_frame(compare)
            with st.expander('Динамика трех последних исследований'): show_frame(gdi.compare_three(chosen))
            st.caption('Сравнение по точкам выполняется в общем диапазоне расходов при совпадающем методе и номере исследования. Порог изменения ΔP² — 10%. Причины изменения по этим данным автоматически не устанавливаются.')
        from app.ui.extras import outlier_panel
        outlier_panel(chosen,point_controls,key)
        point_controls.tools('gdi',gdi.select_studies(raw_frames['gdi'],ws,n,season_filter))

elif page=='Графики реагирования':
    heading('Реагирование горизонтов','Сравнение скважин внутри горизонта; уровень и приведенное давление на одной диаграмме или отдельно.')
    if not empty('response'):
        d=frames['response'];hs=ordered(d.horizon);saved=settings.get('panels',{}).get('response',{})
        with filter_bar(pin=False):
            a,b=st.columns(2)
            with a:working=checklist('Рабочие горизонты',hs,[h for h in settings.get('working_horizons',[]) if h in hs],key('working_horizons'))
            with b:selected=checklist('Показывать горизонты',hs,[h for h in saved.get('horizons',hs) if h in hs],key('response_horizons'))
            if st.button('Сохранить рабочие горизонты'):
                store.commit(pid,settings={**settings,'working_horizons':working},expected=revision,action='Выбор рабочих горизонтов');st.success('Сохранено')
            wells=ordered(d.loc[d.horizon.isin(selected),'well'])
            ws=checklist('Скважины',wells,[w for w in saved.get('wells',wells[:10]) if w in wells],key('response_wells'),lambda x:'№ '+x)
            default_span=saved.get('dates',[d.date.min().date(),d.date.max().date()])
            span=st.date_input('Период',tuple(pd.Timestamp(v).date() for v in default_span),key=key('response_dates'))
            a,b=st.columns(2)
            modes=['separate','combined','level','pressure'];splits=['horizon','all','well']
            view=a.selectbox('Вид графиков',modes,index=modes.index(saved.get('view','separate')),format_func=lambda x:{'separate':'Уровень и давление отдельно','combined':'Уровень + давление (две шкалы Y)','level':'Только уровень','pressure':'Только давление'}[x],key=key('response_view'))
            split=b.selectbox('Построение',splits,index=splits.index(saved.get('split','horizon')),format_func=lambda x:{'horizon':'Отдельно по горизонтам','all':'Все выбранные на одной диаграмме','well':'Отдельно по скважинам'}[x],key=key('response_split'))
            st.caption('При совмещении давление — слева, уровень — справа с обратной шкалой. В графиках по скважине: объект — красный, уровень — мятный, ГДМ — фиолетовый, пересчет — синий.')
            cfg={'wells':ws,'horizons':selected,'working':working,'dates':[str(v) for v in span],'view':view,'split':split}
            viewer_configs['response']=cfg
            if st.button('Сохранить параметры графиков'):remember_panel('response',cfg)
        f=d[d.horizon.isin(selected)&d.well.isin(ws)]
        original=raw_frames['response'];original=original[original.horizon.isin(selected)&original.well.isin(ws)]
        if len(span)==2:
            f=f[f.date.between(pd.Timestamp(span[0]),pd.Timestamp(span[1]))]
            original=original[original.date.between(pd.Timestamp(span[0]),pd.Timestamp(span[1]))]
        if f.empty:st.info('Нет замеров в выбранном диапазоне.')
        else:
            row=st.columns(3);row[0].metric('Горизонтов',f.horizon.nunique());row[1].metric('Скважин',f.well.nunique());row[2].metric('Действующих уровней',f.level.notna().sum())
            sets={'Все выбранные':f} if split=='all' else {str(label):part for label,part in f.groupby('horizon' if split=='horizon' else 'well')}
            for label,part in paginate(list(sets.items()),'Страница графиков реагирования',key('response_page'),format_func=lambda item:item[0]):
                for metric in (['level','pressure'] if view=='separate' else [view]):
                    if metric!='combined' and (metric not in part or not part[metric].notna().any()):continue
                    title=label+' · '+{'level':'уровень','pressure':'давление','combined':'уровень и давление'}[metric]
                    fig=charts.response_chart(part,working,metric,charts.response_title(ordered(part.well),label,split),color_map=charts.well_colors(d.well),object_pressure=frames.get('object_pressure'),manometer_wells=settings.get('manometer_wells',[]),by_well=split=='well',pressure_horizons=ordered(raw_frames['response'].loc[raw_frames['response'].pressure.notna(),'horizon']) if 'pressure' in raw_frames['response'] else [])
                    plot(fig,key('response_'+label+'_'+metric));quick_download(fig,title)

            st.download_button('Выбранные замеры · CSV',csv_bytes(exclusions.public_table(f)),'response.csv')
        point_controls.tools('response',original)
        if 'object_pressure' in raw_frames:point_controls.tools('object_pressure',suffix='давление объекта')

elif page=='Исключенные точки':
    heading('Исключенные точки','Восстановите выбранные показатели, отмените последнее исключение или верните весь исходный набор.')
    point_controls.manager()

elif page=='Кроссплот давлений':
    from app.ui.pressure_panel import render as pressure_panel
    heading('Кроссплот давлений','Сопоставление факта и моделей по скважинам, датам, группам и объектам.')
    pressure_panel(store,pid,m,frames,raw_frames,mapping,point_controls,key,chart_style,viewer_configs,quick_download)

elif page=='Поскважинный анализ':
    from app.ui.well_dashboard import render as well_dashboard
    heading('Поскважинный анализ','Сезоны эксплуатации, условия работы, продуктивность, вода, забой и конструкция.')
    well_dashboard(frames,raw_frames,settings,mapping,catalog,point_controls,key,chart_style,viewer_configs)

elif page=='Аналитика фонда':
    heading('Аналитика фонда','Сводные показатели по выбранным данным. Рейтинг динамики взвешен по числу активных дней.')
    metrics(frames)
    if 'production' in frames:
        d=production.periods(frames['production'],settings['season_start'],settings['season_end'])
        kind=st.selectbox('Режим',['withdrawal','injection'],format_func=lambda x:'Отбор' if x=='withdrawal' else 'Закачка')
        ps=st.multiselect('Периоды',ordered(d.loc[d.kind.eq(kind),'period']),default=ordered(d.loc[d.kind.eq(kind),'period']))
        f=d[d.kind.eq(kind)&d.period.isin(ps)]
        if not f.empty:
            stats=group_analysis.ranking(f,mapping)
            show_frame(stats); st.download_button('Рейтинг · CSV',csv_bytes(stats),'ranking.csv')
    if 'gdi' in frames:
        st.subheader('Качество последних ГДИ')
        latest=gdi.analyze(gdi.select_studies(frames['gdi'],ordered(frames['gdi'].well),1),settings['r2_threshold'])
        show_frame(latest[['well','date','points','r2','source','note']])
        with st.expander('Проверка выполнения программы'):
            planned=st.text_area('Номера скважин программы, через пробел или перенос строки')
            span=st.date_input('Период программы',(dt.date.today().replace(month=1,day=1),dt.date.today()))
            if planned and len(span)==2:
                import re
                ws=ordered(re.split(r'[\s,;]+',planned.strip()))
                program=group_analysis.program(frames['gdi'],ws,span[0],span[1])
                show_frame(program); st.download_button('Выполнение программы',csv_bytes(program),'program.csv')

elif page=='Группы':
    heading('Группы и подгруппы','Назначьте состав вручную или распределите скважины по среднему дебиту внутри каждой группы.')
    wells=ordered(catalog['wells'])
    if not wells: st.info('Сначала загрузите данные.')
    else:
        groupdf=pd.DataFrame([{'Скважина':w,'Группа':mapping.get(w,{}).get('group','Без группы'),'Подгруппа':mapping.get(w,{}).get('subgroup','')} for w in wells])
        edited=st.data_editor(groupdf,disabled=['Скважина'],hide_index=True,use_container_width=True,key=key('group_editor'))
        if st.button('Сохранить назначения',type='primary'):
            saved={str(r['Скважина']):{'group':str(r['Группа'] or 'Без группы'),'subgroup':str(r['Подгруппа'] or '')} for _,r in edited.fillna('').iterrows()}
            store.commit(pid,groups=saved,expected=revision,action='Назначение групп'); st.rerun()
        st.download_button('Выгрузить назначения',csv_bytes(edited),'groups.csv')
        if 'production' in frames:
            st.subheader('Автоматические подгруппы')
            a,b,c=st.columns(3); kind=a.selectbox('Режим',['withdrawal','injection']); size=b.number_input('Скважин в подгруппе',min_value=1,max_value=100,value=8); direction=c.selectbox('Сортировка',['desc','asc','number'],format_func=lambda v:{'desc':'По убыванию дебита','asc':'По возрастанию дебита','number':'По номеру'}[v])
            d=production.periods(frames['production'],settings['season_start'],settings['season_end']); options=ordered(d.loc[d.kind.eq(kind),'period']); ps=st.multiselect('Периоды расчета',options,default=options)
            parts=production.partitions(d,mapping,kind,ps,wells,'auto',int(size),direction)
            show_frame(pd.DataFrame([{'Подгруппа':k,'Скважины':', '.join(ws)} for k,ws in parts.items()]))
            if parts and ps:
                first=next(iter(parts)); plot(charts.histogram(d,kind,ps,parts[first],title=first),key('groups_preview'))
            if st.button('Применить автоматические подгруппы',disabled=not ps):
                new=dict(mapping)
                for label,ws in parts.items():
                    for w in ws: new[w]={**new.get(w,{}),'subgroup':label.rsplit(' / ',1)[1]}
                store.commit(pid,groups=new,expected=revision,action='Автоматические подгруппы'); st.rerun()

elif page=='Экспорт':
    heading('Экспорт результатов','Параметры просмотра, ручной фильтр и предпросмотр каждой диаграммы перед выгрузкой.')
    from app.ui.export_panel import render as render_export
    render_export(store,pid,m,frames,raw_frames,mapping,viewer_configs,point_controls,key)

elif page in ('История фильтра','Паспорт скважины','Проекты'):
    from app.ui.extras import render_extra
    render_extra(page,store,pid,m,frames,raw_frames,mapping,point_controls,key,log_path)

elif page=='Настройки':
    heading('Настройки проекта','Правила периодов, резервные копии и восстановление.')
    with st.form('settings'):
        a,b,c=st.columns(3)
        start=a.number_input('Первый месяц сезона отбора',1,12,int(settings['season_start']))
        end=b.number_input('Последний месяц сезона отбора',1,12,int(settings['season_end']))
        threshold=c.number_input('Порог R²',min_value=0.,max_value=1.,value=float(settings['r2_threshold']),step=.01)
        manometers=st.text_input('Скважины с глубинными манометрами (через запятую)',value=', '.join(settings.get('manometer_wells',[])))
        st.caption('Явный сезон в исходной таблице имеет приоритет над правилом месяцев. Закачка группируется по году. Изменение порога применяется к следующему расчету ГДИ.')
        if st.form_submit_button('Сохранить правила',type='primary'):
            store.commit(pid,settings={**settings,'season_start':start,'season_end':end,'r2_threshold':threshold,'manometer_wells':parse_wells(manometers)},expected=revision,action='Изменение правил'); st.rerun()
    st.subheader('Разделы меню')
    selected_pages=checklist('Показывать разделы',navigation.PAGES,[navigation.ALIASES.get(p,p) for p in settings.get('visible_pages',navigation.DEFAULT)],key('visible_pages'))
    st.caption('Настройки остаются доступными при любом выборе. Скрытые разделы сохраняют данные и параметры.')
    if st.button('Сохранить состав меню',key=key('menu_save')):
        store.commit(pid,settings={**settings,'visible_pages':selected_pages,'pressure_module_menu_seen':True},expected=revision,action='Состав меню');st.rerun()
    if st.button('Восстановить меню по умолчанию',key=key('menu_default')):
        store.commit(pid,settings={**settings,'visible_pages':navigation.DEFAULT},expected=revision,action='Состав меню');st.session_state.pop(key('visible_pages'),None);st.rerun()
    st.subheader('Резервная копия проекта')
    include_originals=st.checkbox('Включить исходные файлы',True)
    if st.button('Подготовить копию проекта'):
        content=store.backup(pid,include_originals)
        st.download_button('Скачать резервную копию',content,safe_name(m['name'])+'.gasatlas.zip')
    uploaded=st.file_uploader('Восстановить копию или перенести старый .gas.json как отдельный проект',type=['zip','json'])
    if uploaded:
        from app.ui.import_editor import preview_project
        preview_project(uploaded)
    if uploaded and st.button('Восстановить копию'):
        try:
            st.session_state['next_project']=store.import_legacy(uploaded.getvalue()) if uploaded.name.endswith('.json') else store.restore(uploaded.getvalue())
            st.rerun()
        except Exception as e: show_error('Не удалось восстановить: '+str(e))
    if log_path.exists():st.download_button('Скачать журнал ошибок',log_path.read_bytes(),'gas_atlas.log')
    st.caption('Проекты автоматически сохраняются после импорта и изменения настроек. Для переноса на другой компьютер используйте резервную копию.')

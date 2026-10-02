import numpy as np
import pandas as pd
import streamlit as st
from app.core.config import ordered
from app.ui.selection import checklist
from app.ui.point_tools import LABELS as INPUT_LABELS
from app.core.export import csv_bytes
from app.core.performance import select_wells
from app.modules import charts,well_analysis,well_charts,gdi

SECTIONS=['Эксплуатация','Продуктивность и ГДИ','Контроль воды','Забой и шаблонировка','Конструкция','Выводы и качество']

def number(value,precision=1):
    return f'{float(value):,.{precision}f}'.replace(',',' ') if pd.notna(value) and np.isfinite(value) else 'Нет данных'

def render(frames,raw_frames,settings,mapping,catalog,point_controls,key,style,viewer):
    allw=ordered(catalog['wells'])
    if not allw:st.info('Загрузите данные скважин через «Импорт данных».');return
    groups=ordered(mapping.get(w,{}).get('group','Без группы') for w in allw)
    a,b,c=st.columns([1,1,2])
    group=a.selectbox('Группа анализа',['Все группы']+groups,key=key('dash_group'))
    wells=[w for w in allw if group=='Все группы' or mapping.get(w,{}).get('group','Без группы')==group]
    well_key=key('dash_well')
    if st.session_state.get(well_key) not in wells:st.session_state[well_key]=wells[0]
    well=b.selectbox('Скважина анализа',wells,key=well_key)
    kind=c.selectbox('Режим эксплуатации',['withdrawal','injection'],format_func=lambda x:'Отбор' if x=='withdrawal' else 'Закачка',key=key('dash_kind'))
    context=well_analysis.dataset(frames,settings,mapping);daily=context['daily']
    chosen=daily[daily.well.eq(well)&daily.kind.eq(kind)] if not daily.empty else daily
    periods=chosen.groupby('period').date.max().sort_values().index.tolist() if not chosen.empty else []
    period_key=key('dash_periods')
    if period_key in st.session_state:st.session_state[period_key]=[p for p in st.session_state[period_key] if p in periods]
    ps=checklist('Периоды анализа',periods,periods[-3:],period_key)
    a,b=st.columns(2)
    methods=ordered(select_wells(frames['gdi'],[well]).method) if 'gdi' in frames else []
    method_key=key('dash_method');choices=['Все методы']+methods
    if st.session_state.get(method_key) not in choices:st.session_state[method_key]=choices[0]
    method=a.selectbox('Метод ГДИ',choices,key=method_key)
    threshold=b.number_input('Порог изменения для выводов, %',min_value=1.,max_value=80.,value=10.,step=1.,key=key('dash_threshold'))
    with st.expander('Параметры сравнения ГДИ'):
        fixed=st.checkbox('Задать общий ΔP² вручную',False,key=key('dash_fixed_dp2'))
        delta=st.number_input('Общий ΔP²',min_value=.001,value=500.,step=10.,key=key('dash_dp2')) if fixed else None
        st.caption('Автоматически выбирается середина общего измеренного диапазона надежных исследований одного метода. Вне диапазона или при отсутствии его пересечения сравнение не рассчитывается. Минимум три разных положительных Q и R² не ниже порога проекта.')
    maxdate=max((info['end'] for info in catalog['modules'].values() if pd.notna(info.get('end'))),default=pd.Timestamp.today())
    asof=st.date_input('Дата состояния скважины',value=pd.Timestamp(maxdate).date(),key=key('dash_asof'),help='Эксплуатация и исследования ограничиваются этой датой. Для забоя, воды и конструкции показывается последнее известное состояние на дату.')
    analysis=well_analysis.analyze(frames,settings,mapping,well,kind,ps if periods else None,delta,threshold,None if method=='Все методы' else method,asof)
    analysis=dict(analysis)
    original=select_wells(raw_frames['gdi'],[well]) if 'gdi' in raw_frames else pd.DataFrame()
    if not original.empty:
        original=original[original.date.le(pd.Timestamp(asof))]
        if method!='Все методы':original=original[original.method.eq(method)]
        if ps and not analysis['daily'].empty:
            mask=pd.Series(False,index=original.index)
            for _,g in analysis['daily'].groupby('period'):mask|=original.date.between(g.date.min(),g.date.max())
            original=original[mask]
    analysis['gdi_raw']=original
    dashboard_settings=dict(settings)
    viewer['well_dashboard']={**viewer.get('well_dashboard',{}),'wells':[well],'kind':kind,'periods':ps,'delta':delta,'threshold':threshold,'method':None if method=='Все методы' else method,'asof':str(asof)}
    stats=analysis['seasons'];data=analysis['daily']
    st.subheader('Скважина №'+well+' · '+mapping.get(well,{}).get('group','Без группы'))
    cols=list(st.columns(3))+list(st.columns(3))
    cols[0].metric('Газ за выбранные периоды, млн м³',number(stats.gas_volume.sum(min_count=1) if not stats.empty else np.nan,3))
    cols[1].metric('Средний суточный объем, тыс. м³',number(data.loc[data.active,'gas_volume_m3'].mean()/1000 if not data.empty else np.nan,2))
    cols[2].metric('Отработанные дни',number(stats.active_days.sum() if not stats.empty else np.nan,0))
    cols[3].metric('Известные часы работы',number(stats.hours.sum(min_count=1) if not stats.empty else np.nan,1))
    cols[4].metric('Последний отбитый забой, м',number(analysis['bottom'].iloc[-1].bottom_m if not analysis['bottom'].empty else np.nan,1))
    water=analysis['water'];last=water.iloc[-1] if not water.empty else None
    state='Неизвестно' if last is None else 'Есть' if last['Состояние'] in ('Вода измерена','Вода отмечена') else 'Не отмечена' if last['Признак']=='Нет' else 'Замер равен нулю'
    cols[5].metric('Вода по последнему контролю',state,help='Нет наблюдений' if last is None else last['Дата'].strftime('%d.%m.%Y')+'; состояние относится к дате наблюдения.')
    gasdays=int(data.gas_volume_m3.notna().sum()) if not data.empty else 0
    knownhours=int(data.work_hours.notna().sum()) if not data.empty else 0
    st.caption('Данные газа: '+str(gasdays)+' суток; часы известны: '+str(knownhours)+' суток. Дата состояния: '+pd.Timestamp(asof).strftime('%d.%m.%Y')+'.')
    missing=[title for module,title in [('operations','суточные часы и вода'),('water','контроль воды'),('bottom','замеры забоя'),('construction','конструкция')] if module not in frames]
    if missing:st.info('Для полного анализа не загружены: '+', '.join(missing)+'. Шаблоны доступны в «Импорт данных».')
    st.caption('Объемы относятся к загруженным наблюдениям. Приоритет: явный суточный объем из эксплуатации, затем суточный расход из динамики × 1 день. Расход в часы работы = объем × 24 / известные часы. Пропуски не считаются нулем или простоем. Группы используются в текущем составе проекта.')
    section=st.radio('Раздел анализа',SECTIONS,horizontal=True,key=key('dash_section'))
    available=well_charts.available(analysis)
    def plot(name):
        if name not in available:return
        fig=charts.style_figure(well_charts.build(analysis,name,dashboard_settings),style,copy_figure=False)
        point_controls.plot(fig,key('dash_'+name),allow_edit=False,copy_figure=False)
    def table(d):
        st.dataframe(d,hide_index=True,use_container_width=True)
    if section=='Эксплуатация':
        alignment=st.radio('Начало отсчета сезонов',['well','object'],format_func=lambda x:'Первый замер скважины = 0' if x=='well' else 'Первый день данных объекта',horizontal=True,key=key('dash_alignment'))
        dashboard_settings['dashboard_alignment']=alignment;viewer['well_dashboard']['alignment']=alignment
        if data.empty:st.info('Нет суточных данных для выбранного режима и периодов.')
        else:
            choices=[n for n in ('daily','daily_mixed','shares','cumulative','cumulative_axis','seasonal','aligned','hours','pressures','specific') if n in available]
            selected_graphs=checklist('Графики эксплуатации',choices,[n for n in ('daily','cumulative') if n in choices],key('dash_operating_charts'),lambda x:well_charts.LABELS[x])
            for name in selected_graphs:plot(name)
            st.caption('По умолчанию первый фактический замер скважины каждого сезона расположен в нуле. Можно выбрать общую привязку к началу наблюдений объекта. Среднее за 7 дней строится при наличии минимум трех наблюдений; отсутствующие даты остаются пропусками.')
            if st.checkbox('Показать сезонные показатели',False,key=key('dash_season_table')):table(stats.rename(columns=well_analysis.SEASON_LABELS))
            st.download_button('Сезонные показатели · CSV',csv_bytes(stats.rename(columns=well_analysis.SEASON_LABELS)),'well_'+well+'_seasons.csv',key=key('dash_season_csv'))

            if 'specific' in available:st.caption('Q/ΔP² — условный показатель для сопоставления режимов. Здесь Q рассчитан только для суток с известными часами и объемом, давления относятся к тем же суткам. Он зависит от режима и не является самостоятельным доказательством изменения проницаемости.')
    elif section=='Продуктивность и ГДИ':
        with st.expander('Настройки индикаторных диаграмм ГДИ',expanded=True):
            a,b=st.columns(2)
            n=a.selectbox('Последние даты ГДИ',[0,1,2,3],format_func=lambda x:'Все' if x==0 else str(x),key=key('dash_gdi_n'))
            orientation=b.selectbox('Оси ГДИ',['standard','swapped'],format_func=lambda x:'X = Q, Y = ΔP²' if x=='standard' else 'X = ΔP², Y = Q',key=key('dash_gdi_orientation'))
            a,b,c=st.columns(3)
            curves=a.checkbox('Расчетные кривые ГДИ',True,key=key('dash_gdi_curves'));db=b.checkbox('Кривые по коэффициентам БД',True,key=key('dash_gdi_db'));crosshair=c.checkbox('Перекрестная линейка ГДИ',True,key=key('dash_gdi_crosshair'))
            show=st.checkbox('Показывать исключенные точки ГДИ',True,key=key('dash_gdi_excluded'))
            seasons=ordered(original.season[original.season.ne('')]) if not original.empty and 'season' in original else []
            selected=checklist('Сезоны ГДИ (пусто — все)',seasons,[],key('dash_gdi_seasons')) if seasons else []
            cfg={'n':n,'orientation':orientation,'curves':curves,'db_curves':db,'crosshair':crosshair,'show_excluded':show,'seasons':selected}
            dashboard_settings['dashboard_gdi']=cfg;viewer['well_dashboard']['gdi']=cfg
        if analysis['gdi'].empty:st.info('Нет ГДИ в выбранном диапазоне периодов.')
        else:
            plot('gdi');plot('gdi_history')
            controls=original[original.season.isin(selected)] if selected else original
            point_controls.tools('gdi',gdi.select_studies(controls,[well],n),suffix='поскважинный анализ')
            labels={'date':'Дата','method':'Метод','study':'Исследование','a':'a','b':'b','r2':'R²','distinct_q':'Разных Q','reliable':'Достаточно данных',
                    'reference_dp2':'Общий ΔP²','q_reference':'Q при общем ΔP², тыс. м³/сут','q_free':'Формальный Qсв','note':'Примечание'}
            table(analysis['gdi_history'][list(labels)].rename(columns=labels))
            st.caption('Используется прежняя модель ГДИ ΔP²=aQ+bQ². Достоверность сравнения зависит от одинаковых условий исследований и применимости модели. Qсв зависит также от пластового давления; выводы основаны на Q при общем ΔP².')
    elif section=='Контроль воды':
        plot('water');plot('water_log')
        if analysis['water'].empty:st.info('Наличие воды неизвестно: загрузите контроль воды или суточный объем воды.')
        else:table(analysis['water'])
        if not data.empty and data.water_factor.notna().any():
            table(data[['date','gas_volume_m3','water_volume_m3','water_factor']].rename(columns={'date':'Дата','gas_volume_m3':'Газ, м³','water_volume_m3':'Вода, м³','water_factor':'Вода, м³ / млн м³ газа'}))
        if 'response' in frames:
            r=select_wells(frames['response'],[well]);r=r[r.level.notna()]
            if not r.empty:
                fig=charts.response_chart(r,settings.get('working_horizons',[]),'level')
                point_controls.plot(charts.style_figure(fig,style,copy_figure=False),key('dash_levels'),copy_figure=False)
                st.caption('Уровни относятся к указанным горизонтам этой скважины. Положительный уровень жидкости сам по себе не устанавливает обводненность добываемого газа.')
    elif section=='Забой и шаблонировка':
        plot('bottom')
        if analysis['bottom'].empty:st.info('Загрузите даты и измеренные глубины забоя. Диаметр шаблона, метод и комментарий можно указать дополнительно.')
        else:table(analysis['bottom'].drop(columns=['_point_id'],errors='ignore').rename(columns=INPUT_LABELS))
    elif section=='Конструкция':
        plot('construction')
        if analysis['construction'].empty:st.info('Нет снимка конструкции на выбранную дату. Одна строка шаблона — один элемент или интервал; все элементы снимка имеют одну дату.')
        else:
            st.caption('Снимок от '+analysis['construction'].date.max().strftime('%d.%m.%Y')+'. Глубины привязаны к единому нулю, указанному в вашей документации. Элементы с неизвестным диаметром показаны условной шириной.')
            table(analysis['construction'].drop(columns=['_point_id'],errors='ignore').rename(columns=INPUT_LABELS))
    else:
        for _,row in analysis['signals'].iterrows():
            with st.container(border=True):
                st.markdown('**'+str(row.iloc[0])+'**');st.write(str(row.iloc[2]));st.caption('Основание: '+str(row.iloc[1]));st.caption('Проверить: '+str(row.iloc[3]))
        st.download_button('Выводы и основания · CSV',csv_bytes(analysis['signals']),'well_'+well+'_analysis.csv',key=key('dash_signals_csv'))
    if st.checkbox('Показать исходные данные и ручной фильтр',False,key=key('dash_raw_controls')):
        st.caption('Графики дашборда содержат производные показатели. Измерения можно исключить в таблицах ниже; анализ пересчитается. Клик по исходным точкам также доступен в основных вкладках.')
        for module in ('production','operations','water','bottom','construction'):
            if module in raw_frames:
                point_controls.tools(module,lambda module=module:select_wells(raw_frames[module],[well]),suffix='анализ №'+well+' '+module)
    def to_export():
        for field in ('n','orientation','curves','db','crosshair','excluded','seasons'):st.session_state.pop(key('exp_dashboard_gdi_'+field),None)
        st.session_state[key('exp_modules')]=['well_dashboard'];st.session_state[key('exp_wells')]=[well]
        for module in ('production','histograms','gdi','response','object_pressure','operations','water','bottom','construction','well_dashboard','pressure_match'):st.session_state[key('exp_'+module+'_enabled')]=module=='well_dashboard'
        st.session_state[key('exp_dashboard_wells')]=[well]
        for field,value in viewer['well_dashboard'].items():
            if field!='wells':st.session_state[key('exp_dashboard_'+field)]=value
        st.session_state['nav']='Экспорт'
    st.button('Перенести анализ этой скважины в экспорт',key=key('dash_to_export'),on_click=to_export)

import copy
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from app.core import exclusions,reporting
from app.core.config import ordered,MODULES
from app.core.history import comparison,filter_details
from app.core.logging_utils import show_error
from app.core.export import safe_name
from app.modules import gdi,production
from app.ui.theme import heading


def outlier_panel(chosen,controls,key):
    with st.expander('Подсказки выбросов ГДИ'):
        st.caption('Кривая по остальным точкам сравнивается с проверяемой точкой. Это рекомендация для проверки инженером; исключение применяется только вашей кнопкой.')
        threshold=st.number_input('Порог отклонения, %',5,100,15,5,key=key('outlier_threshold'))
        if st.button('Найти возможные выбросы',key=key('outlier_search')):
            with st.spinner('Проверка точек ГДИ…'):
                result=gdi.outlier_suggestions(chosen,threshold)
            st.session_state[key('outlier_result')]=(controls.revision,result)
        cached=st.session_state.get(key('outlier_result'))
        if cached and cached[0]==controls.revision:
            result=cached[1]
            if result.empty:st.info('Точек, соответствующих критериям подсказки, не найдено.');return
            table=result[['id','well','date','q','dp2','deviation_percent','r2_without_point']].rename(columns={'well':'Скважина','date':'Дата','deviation_percent':'Отклонение, %','r2_without_point':'R² без точки'})
            table.insert(0,'Исключить',False)
            edited=st.data_editor(table,hide_index=True,use_container_width=True,disabled=[c for c in table if c!='Исключить'],column_config={'id':None},key=key('outlier_editor_'+str(controls.revision)))
            def exclude():
                ids=edited.loc[edited['Исключить'],'id']
                entries=[exclusions.entry(controls.raw,'gdi',identifier,reason='Подсказка выброса подтверждена инженером') for identifier in ids]
                if entries:controls.change(added=entries)
            st.button('Исключить подтвержденные точки',on_click=exclude,key=key('outlier_apply'))


def render_extra(page,store,pid,m,frames,raw,mapping,controls,key,log_path):
    settings=m['settings'];revision=m['revision']
    if page=='История фильтра':
        heading('История фильтра','Состояния исключений и расчетные параметры ГДИ до и после изменения.')
        history=store.history(pid);records=[]
        for _,row in history.iterrows():
            details=json.loads(row['Подробности'])
            if 'before_exclusions' in details:records.append((row,details))
        if not records:st.info('История начнет заполняться при исключении или восстановлении точек в v5.3.');return
        i=st.selectbox('Изменение',range(len(records)),format_func=lambda i:records[i][0]['Дата']+' · '+records[i][0]['Действие'])
        row,details=records[i]
        st.write('Добавлено исключений:',len(details.get('added_ids',[])),'Восстановлено:',len(details.get('removed_ids',[])))
        values=comparison(details)
        if not values.empty:st.dataframe(values,hide_index=True,use_container_width=True)
        state=st.radio('Состояние для восстановления',['До изменения','После изменения'],horizontal=True)
        target=details['before_exclusions' if state=='До изменения' else 'after_exclusions']
        st.caption(f'В выбранном состоянии исключено показателей: {len(target)}.')
        if st.button('Восстановить выбранное состояние фильтра',type='primary'):
            cfg=copy.deepcopy(settings);cfg['excluded_points']=target
            old=settings.get('excluded_points',{});added=[v for k,v in target.items() if k not in old];removed=[k for k in old if k not in target]
            try:
                detail=filter_details(raw,settings,cfg,added,removed)
                store.commit(pid,settings=cfg,expected=revision,action='Восстановление фильтра',details=detail);st.rerun()
            except Exception as error:show_error(str(error))
    elif page=='Проекты':
        heading('Проекты','Название, копии, сохраненные параметры и готовые выгрузки проекта.')
        st.dataframe(pd.DataFrame([{'Проект':x['name'],'Версия':x['version'],'Обновлен':x['updated'],'Строк данных':sum(x['tables'].values())} for x in store.list()]),hide_index=True,use_container_width=True)
        name=st.text_input('Название текущего проекта',m['name'],key=key('rename_text'))
        if st.button('Переименовать проект'):
            try:store.rename(pid,name,revision);st.rerun()
            except Exception as error:show_error(str(error))
        if st.button('Создать копию проекта с данными и настройками'):
            try:
                with st.spinner('Копирование проекта…'):new=store.restore(store.backup(pid,True))
                st.session_state['next_project']=new;st.rerun()
            except Exception as error:show_error(str(error))
        st.subheader('Сохраненные выгрузки')
        exports=store.exports(pid)
        if not exports:st.info('Архивы, Word-отчеты и PDF-паспорта появятся здесь после формирования.')
        else:
            selected=st.selectbox('Файл',exports,format_func=lambda p:p.name)
            if st.button('Подготовить сохраненный файл'):
                st.download_button('Скачать сохраненный файл',selected.read_bytes(),selected.name)
        with st.expander('Сохраненные параметры просмотра'):st.json(settings.get('panels',{}))
        if log_path.exists():st.download_button('Скачать журнал ошибок',log_path.read_bytes(),'gas_atlas.log')
    elif page=='Паспорт скважины':
        from app.core.documents import passport_pdf
        heading('Паспорт скважины','Динамика, ГДИ, реагирование, расчетные параметры и комментарий инженера в PDF.')
        wells=ordered({w for d in raw.values() if 'well' in d for w in d.well.unique()})
        if not wells:st.info('Сначала загрузите данные скважин.');return
        well=st.selectbox('Скважина для паспорта',wells,key=key('passport_well'))
        modules=st.multiselect('Разделы паспорта',[x for x in frames if x!='object_pressure'],default=[x for x in frames if x!='object_pressure'],format_func=lambda x:MODULES[x])
        comment=st.text_area('Комментарий инженера',settings.get('well_comments',{}).get(well,''),height=160,key=key('comment_'+well))
        if st.button('Сохранить комментарий'):
            cfg=copy.deepcopy(settings);cfg.setdefault('well_comments',{})[well]=comment
            store.commit(pid,settings=cfg,expected=revision,action='Комментарий инженера');st.rerun()
        options={'modules':modules,'wells':[well],'apply_exclusions':True,'style':settings.get('chart_style',{}),
                 'gdi':{'wells':[well],'n':3,'show_excluded':True},'response':{'wells':[well],'view':'combined','split':'well'}}
        if 'production' in modules:
            d=production.periods(frames['production'],settings['season_start'],settings['season_end']);periods={}
            for kind,label in [('withdrawal','Отбор'),('injection','Закачка')]:
                available=ordered(d.loc[d.kind.eq(kind),'period']);periods[kind]=st.multiselect(label+': периоды паспорта',available,default=available[-2:])
            options['production']={'wells':[well],'periods':periods,'view':'mixed','split':'well'}
        passport_signature=json.dumps([well,revision,options,comment],sort_keys=True,ensure_ascii=False)
        if st.button('Создать паспорт',type='primary',disabled=not modules):
            try:
                with st.spinner('Формирование паспорта…'):
                    figures,tables=reporting.build(frames,mapping,settings,options,raw)
                    bar=st.progress(0.);content=passport_pdf(m['name'],well,figures,tables,settings,comment,bar.progress);bar.empty()
                    path=store.save_export(pid,'Паспорт_скважины_'+safe_name(well)+'.pdf',content,options)
                    st.session_state[key('passport_ready')]=(passport_signature,content,path.name)
            except Exception as error:show_error('Не удалось создать паспорт: '+str(error))
        ready=st.session_state.get(key('passport_ready'))
        if ready and ready[0]==passport_signature:st.download_button('Скачать паспорт PDF',ready[1],ready[2],mime='application/pdf')

import streamlit as st
from app.core.config import ordered
from app.core.performance import index_for,select_wells
from app.core.export import csv_bytes
from app.modules import production,charts,group_analysis
from app.ui.selection import checklist,histogram_size,paginate


def render(d,raw,catalog,settings,mapping,controls,key,viewer,style,edit,quick_download,remember_panel,histograms=False):
    module_wells=ordered(catalog['modules']['production']['wells'])
    groups=ordered(mapping.get(w,{}).get('group','Без группы') for w in module_wells)
    mode='individual' if histograms else st.radio('Представление',['individual','groups'],format_func=lambda x:'Отдельные скважины' if x=='individual' else 'Суммарные показатели групп',horizontal=True,key=key('prod_mode'))
    if mode=='groups':
        kind=st.selectbox('Режим группы',['withdrawal','injection'],format_func=lambda x:'Отбор' if x=='withdrawal' else 'Закачка',key=key('group_kind'))
        pschoices=ordered(index_for(d).periods.get(kind,[])) if index_for(d) else ordered(d.loc[d.kind.eq(kind),'period'])
        cols=st.columns(3)
        with cols[0]:gs=checklist('Группы',groups,groups,key('group_selected'))
        with cols[1]:ps=checklist('Периоды',pschoices,pschoices[-3:],key('group_periods'))
        choices=[w for w in module_wells if mapping.get(w,{}).get('group','Без группы') in gs]
        with cols[2]:overlay=checklist('Скважины поверх суммы',choices,[],key('group_overlay'),lambda x:'№ '+x)
        metric=st.selectbox('Показатель группы',['daily','cumulative','active'],format_func=lambda x:{'daily':'Суточный суммарный расход','cumulative':'Накопленный объем','active':'Работающие скважины'}[x],key=key('group_metric'))
        viewer['group_totals']={'wells':choices,'groups':gs,'periods':{kind:ps},'split':'group_total','metric':metric,'overlay':overlay}
        st.caption('Сумма включает все скважины выбранной группы. Выбор кривых наложения не меняет сумму. Неполные наблюдения отмечены в подсказках; пропущенные даты не считаются простоями.')
        if not ps or not gs:st.info('Выберите группы и периоды.');return
        for group in paginate(gs,'Страница групп',key('group_page')):
            fig=charts.style_figure(group_analysis.figure(d,mapping,group,kind,ps,overlay,metric),style,copy_figure=False)
            controls.plot(fig,key('group_chart_'+group),allow_edit=False,copy_figure=False);quick_download(fig,'Группа_'+group)
            if st.checkbox('Показать расчетные показатели · '+group,key=key('group_table_'+group)):
                table,_=group_analysis.daily(d,mapping,group,kind,ps)
                table=table.rename(columns={'date':'Дата','period':'Период','total':'Суммарный расход, м³/сут','observed':'Скважин с данными','active':'Работают','cumulative':'Объем, млн м³','coverage':'Покрытие, %','expected':'Всего скважин'})
                st.dataframe(table,hide_index=True,use_container_width=True);st.download_button('Таблица группы · CSV',csv_bytes(table),'group_'+group+'.csv',key=key('group_csv_'+group))
        return
    prefix='hist' if histograms else 'prod'
    two=st.toggle('Две независимые панели',value=False,key=key(prefix+'_two_panels'))
    containers=st.columns(2) if two else [st.container()]
    for idx,container in enumerate(containers):
        with container:
            suffix=prefix+'_'+str(idx);saved=settings.get('panels',{}).get(suffix,settings.get('panels',{}).get('prod_'+str(idx),{}))
            kind=st.selectbox('Режим',['withdrawal','injection'],format_func=lambda x:'Отбор' if x=='withdrawal' else 'Закачка',key=key(suffix+'_kind'))
            pschoices=ordered(index_for(d).periods.get(kind,[])) if index_for(d) else ordered(d.loc[d.kind.eq(kind),'period'])
            columns=st.columns(3)
            with columns[0]:gs=checklist('Группы',groups,[g for g in saved.get('groups',groups) if g in groups],key(suffix+'_groups'))
            choices=[w for w in module_wells if mapping.get(w,{}).get('group','Без группы') in gs]
            with columns[1]:ws=checklist('Скважины',choices,[w for w in saved.get('wells',choices[:10]) if w in choices],key(suffix+'_wells'),lambda x:'№ '+x)
            with columns[2]:ps=checklist('Периоды',pschoices,[p for p in saved.get('periods',pschoices[-3:]) if p in pschoices],key(suffix+'_periods'))
            if histograms:
                view='hist';histaxis=st.selectbox('Ось гистограммы',['well','period'],format_func=lambda x:'Скважины' if x=='well' else 'Периоды',key=key(suffix+'_axis'))
                hsize=st.selectbox('Скважин на одной гистограмме',['Авто','10','20','50','Все'],key=key(suffix+'_hist_size'))
            else:
                view=st.selectbox('График',['curve','time'],format_func=lambda x:'Q / накопленный объем объекта' if x=='curve' else 'Q / дата',key=key(suffix+'_view'))
                histaxis='well';hsize='Авто'
            direction=st.selectbox('Порядок скважин',['number','desc','asc'],format_func=lambda x:{'number':'По номеру','desc':'Больший дебит слева','asc':'Больший дебит справа'}[x],key=key(suffix+'_sort'))
            ws=production.rank_wells(d,kind,ps,ws,direction)
            cfg={'kind':kind,'periods':ps,'wells':ws,'groups':gs,'view':view,'direction':direction,'histaxis':histaxis,'hist_size':hsize,'two':two}
            viewer[suffix]=cfg
            if st.button('Сохранить фильтры',key=key(suffix+'_save')):remember_panel(suffix,cfg)
            if not ws or not ps:st.info('Выберите скважины и периоды.');continue
            if histograms:
                size=histogram_size(hsize,len(ws));parts=[ws[i:i+size] for i in range(0,len(ws),size)]
                for i,part in enumerate(paginate(parts,'Страница гистограмм',key(suffix+'_page'))):
                    fig=charts.histogram(d,kind,ps,part,histaxis);controls.plot(charts.style_figure(fig,style,copy_figure=False),key(suffix+'_chart_'+str(i)),allow_edit=False,copy_figure=False);quick_download(fig,suffix+'_histogram_'+str(i))
            else:
                fig=charts.production_curve(d,kind,ps,ws,'date' if view=='time' else 'cumulative',editable=edit)
                controls.plot(charts.style_figure(fig,style,copy_figure=False),key(suffix+'_chart'),copy_figure=False);quick_download(fig,suffix+'_curve')
            def original_points():
                source=raw.project.prepared('production',{**settings,'excluded_points':{}},st.session_state.get('fast_mode',True))
                part=select_wells(source,ws);return part[part.kind.eq(kind)&part.period.isin(ps)]
            controls.tools('production',original_points,suffix=('гистограммы ' if histograms else 'производительность ')+str(idx+1))
            if st.checkbox('Показать расчетные значения',False,key=key(suffix+'_table')):
                values=production.averages(d,kind,ps,ws);st.dataframe(values,hide_index=True,use_container_width=True)
                st.download_button('CSV со средними',csv_bytes(values),suffix+'_averages.csv',key=key(suffix+'_csv'))
    if not histograms:st.caption('Накопление по всему загруженному объекту в пределах периода. Подсказки отмечают пропуски. Экспорт использует все исходные точки.')

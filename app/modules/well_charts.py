from app.core.performance import cached_analysis_chart
"""Well dashboard figures use the same traces for screen and static export."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from app.modules import charts

LABELS={'daily':'Суточный газ: скважина, группа и объект','shares':'Доля скважины в группе и объекте',
 'cumulative':'Накопленный объем скважины, группы и объекта','pressures':'Расход и давления эксплуатации',
 'seasonal':'Объем и отработанные дни по сезонам','aligned':'Сопоставление сезонов по времени',
 'cumulative_axis':'Расход / накопленный объем объекта за сезон','daily_mixed':'Скважина — столбцы, группа и объект — линии',
 'hours':'Часы работы и расход в часы работы','specific':'Расход относительно ΔP²',
 'water':'Вода и суточный объем газа','water_log':'Наблюдения воды','gdi':'Индикаторные диаграммы ГДИ',
 'gdi_history':'Отдача при одинаковом ΔP²','bottom':'История отбитого забоя','construction':'Конструкция скважины'}

def _base(a,name,x,y):
    fig=charts.base('Скважина №'+a['well']+' · '+LABELS[name],x,y)
    fig.update_layout(meta={'module':'well_dashboard','wells':[a['well']],'periods':a['periods']},hovermode='x unified')
    return fig

def _line(fig,x,y,name,color='#16746C',secondary=False,markers=False):
    fig.add_trace(go.Scatter(x=x,y=y,name=name,mode='lines+markers' if markers else 'lines',
        yaxis='y2' if secondary else 'y',line={'color':color,'dash':'solid'},connectgaps=False,meta={'selectable':False}))

def _second(fig,title,reversed_axis=False):
    fig.update_layout(yaxis2={'title':title,'overlaying':'y','side':'right','showgrid':False,
                              'autorange':'reversed' if reversed_axis else True})

def available(a):
    d=a['daily'];keys=[]
    if not d.empty:
        keys+=['daily','daily_mixed','shares','cumulative','cumulative_axis','seasonal','aligned']
        if any(d[c].notna().any() for c in ('p_res','p_bh','p_wellhead','p_line')):keys.append('pressures')
        if d.work_hours.notna().any():keys.append('hours')
        if d.specific_q.notna().any():keys.append('specific')
        if d.water_volume_m3.notna().any():keys.append('water')
    if not a['gdi'].empty:keys.append('gdi')
    if not a['gdi_history'].empty and a['gdi_history'].q_reference.notna().any():keys.append('gdi_history')
    if not a['bottom'].empty:keys.append('bottom')
    if not a['water'].empty:keys.append('water_log')
    if not a['construction'].empty:keys.append('construction')
    return keys

@cached_analysis_chart
def build(a,name,settings=None):
    settings=settings or {};d=a['daily']
    if name=='gdi':
        cfg=settings.get('dashboard_gdi',{})
        from app.modules import gdi
        selected=gdi.select_studies(a['gdi'],[a['well']],cfg.get('n',0),cfg.get('seasons'))
        original=gdi.select_studies(a.get('gdi_raw',a['gdi']),[a['well']],cfg.get('n',0),cfg.get('seasons'))
        fig=charts.gdi_chart(selected,a['well'],settings.get('r2_threshold',.95),cfg.get('orientation','standard'),cfg.get('curves',True),cfg.get('db_curves',True),cfg.get('crosshair',True),raw_df=original,show_excluded=cfg.get('show_excluded',True))
        fig.update_layout(title='Скважина №'+a['well']+' · ГДИ',meta={'module':'well_dashboard','wells':[a['well']]})
        return fig
    if name=='daily':
        fig=_base(a,name,'Дата','Суточный объем скважины, тыс. м³');fig.update_xaxes(type='date')
        calendar=pd.date_range(d.date.min(),d.date.max());s=d.set_index('date').reindex(calendar)
        _line(fig,calendar,s.gas_volume_m3/1000,'Скважина')
        _line(fig,calendar,s.gas_volume_m3.rolling(7,min_periods=3).mean()/1000,'Среднее за 7 календарных дней','#D97706')
        _second(fig,'Суточный объем группы / объекта, тыс. м³')
        _line(fig,calendar,s.group_volume/1000,'Группа','#2563EB',True)
        _line(fig,calendar,s.object_volume/1000,'Объект','#8B5CF6',True)
    elif name=='shares':
        fig=_base(a,name,'Дата','Доля суточного объема, %');fig.update_xaxes(type='date')
        _line(fig,d.date,d.share_group,'В группе');_line(fig,d.date,d.share_object,'В объекте','#2563EB')
    elif name=='cumulative':
        fig=_base(a,name,'Дата','Наблюдаемый накопленный объем скважины, млн м³');fig.update_xaxes(type='date')
        _line(fig,d.date,d.gas_volume_m3.cumsum()/1e6,'Скважина');_second(fig,'Наблюдаемый накопленный объем группы / объекта, млн м³')
        _line(fig,d.date,d.group_volume.cumsum()/1e6,'Группа','#2563EB',True);_line(fig,d.date,d.object_volume.cumsum()/1e6,'Объект','#8B5CF6',True)
    elif name=='pressures':
        fig=_base(a,name,'Дата','Суточный объем газа, тыс. м³');fig.update_xaxes(type='date')
        _line(fig,d.date,d.gas_volume_m3/1000,'Газ');_second(fig,'Давление, кгс/см²')
        labels={'p_res':'Пластовое','p_bh':'Забойное','p_wellhead':'Устьевое','p_line':'В шлейфе'}
        for i,(field,label) in enumerate(labels.items()):
            if d[field].notna().any():_line(fig,d.date,d[field],label,list(charts.well_colors(labels).values())[i],True)
    elif name=='seasonal':
        fig=_base(a,name,'Период','Объем газа, млн м³');s=a['seasons']
        fig.add_trace(go.Bar(x=s.period,y=s.gas_volume,name='Объем газа',marker_color='#16746C'))
        _second(fig,'Отработанные дни');_line(fig,s.period,s.active_days,'Дни','#D97706',True,True)
    elif name=='cumulative_axis':
        fig=_base(a,name,'Накопленный объем объекта за сезон, млн м³','Суточный объем, тыс. м³')
        for period,g in d.groupby('period',sort=False):
            _line(fig,g.object_cumulative,g.gas_volume_m3/1000,str(period),charts.well_colors(d.period)[period])
        fig.update_xaxes(rangemode='tozero')
    elif name=='daily_mixed':
        fig=_base(a,name,'Дата','Суточный объем скважины, тыс. м³');fig.update_xaxes(type='date')
        fig.add_trace(go.Bar(x=d.date,y=d.gas_volume_m3/1000,name='Скважина',marker_color='#16746C',meta={'selectable':False}))
        _second(fig,'Суточный объем группы / объекта, тыс. м³')
        _line(fig,d.date,d.group_volume/1000,'Группа','#2563EB',True)
        _line(fig,d.date,d.object_volume/1000,'Объект','#8B5CF6',True)
    elif name=='aligned':
        anchor=settings.get('dashboard_alignment','well')
        fig=_base(a,name,'Дни от первого замера скважины в сезоне' if anchor=='well' else 'Дни от первой записи объекта в сезоне','Суточный объем, тыс. м³')
        for i,(period,g) in enumerate(d.groupby('period',sort=False)):
            # Calendar span is aligned to observed object data, rather than a fictional full season.
            valid=g[g.gas_volume_m3.notna()]
            if valid.empty:continue
            start=valid.date.min() if anchor=='well' else g.period_start.min()
            g=g[g.date.ge(start)].sort_values('date');x=(g.date-start).dt.days
            _line(fig,x,g.gas_volume_m3/1000,period,charts.well_colors(d.period)[period])
        fig.update_xaxes(rangemode='tozero')
    elif name=='hours':
        fig=_base(a,name,'Дата','Часы работы за сутки');fig.update_xaxes(type='date')
        fig.add_trace(go.Bar(x=d.date,y=d.work_hours,name='Часы',marker_color='#16746C'))
        _second(fig,'Расход в часы работы, тыс. м³/сут');_line(fig,d.date,d.q_work,'Расход','#D97706',True)
    elif name=='specific':
        fig=_base(a,name,'Дата','Q в часы работы / ΔP²');fig.update_xaxes(type='date')
        _line(fig,d.date,d.specific_q,'Удельный расход',markers=True)
    elif name=='water':
        fig=_base(a,name,'Дата','Суточный объем газа, тыс. м³');fig.update_xaxes(type='date')
        _line(fig,d.date,d.gas_volume_m3/1000,'Газ');_second(fig,'Измеренный суточный объем воды, м³')
        _line(fig,d.date,d.water_volume_m3,'Вода','#2563EB',True,True)
    elif name=='water_log':
        w=a['water'];fig=_base(a,name,'Дата наблюдения','Измеренная вода, м³ за сутки');fig.update_xaxes(type='date')
        measured=w[w.Величина.notna()]
        if measured.empty:
            fig.update_yaxes(title='Признак воды: 1 = Да, 0 = Нет')
            known=w[w.Признак.isin(['Да','Нет'])]
            _line(fig,known['Дата'],known.Признак.map({'Да':1.,'Нет':0.}),'Признак',markers=True)
        else:
            _second(fig,'Измеренный расход воды, м³/сут')
            for unit,g in measured.groupby('Единица'):
                _line(fig,g['Дата'],g.Величина,unit,'#2563EB' if unit=='м³/сут' else '#16746C',unit=='м³/сут',True)
    elif name=='gdi_history':
        fig=_base(a,name,'Дата исследования','Q при общем ΔP², тыс. м³/сут');fig.update_xaxes(type='date')
        h=a['gdi_history']
        for method,g in h[h.q_reference.notna()].groupby('method',dropna=False):
            _line(fig,g.date,g.q_reference,f'{method or "Метод не указан"}; ΔP²={g.reference_dp2.iloc[0]:.3g}',markers=True)
    elif name=='bottom':
        fig=_base(a,name,'Дата замера','Отбитый забой, м');fig.update_xaxes(type='date');fig.update_yaxes(autorange='reversed')
        b=a['bottom'];_line(fig,b.date,b.bottom_m,'Отбитый забой',markers=True)
        c=a['construction']
        if not c.empty:
            depth=c.bottom_m.max();_line(fig,[b.date.min(),b.date.max()],[depth,depth],'Низ актуальной конструкции','#8B5CF6')
    elif name=='construction':
        fig=_base(a,name,'Поперечная координата, мм (при известном диаметре)','Глубина, м');fig.update_yaxes(autorange='reversed')
        c=a['construction'];colors=charts.well_colors(c.element)
        fallback=c.diameter_mm.max() if c.diameter_mm.notna().any() else 200
        for i,(_,r) in enumerate(c.iterrows()):
            width=r.diameter_mm if pd.notna(r.diameter_mm) else fallback*.35
            x=[-width/2,-width/2,width/2,width/2,-width/2];y=[r.top_m,r.bottom_m,r.bottom_m,r.top_m,r.top_m]
            label=f'{r.element}: {r.top_m:g}–{r.bottom_m:g} м'+(f'; Ø{width:g} мм' if pd.notna(r.diameter_mm) else '; диаметр не задан')
            _line(fig,x,y,label,colors[r.element],markers=r.top_m==r.bottom_m)
        if not a['bottom'].empty:
            depth=a['bottom'].iloc[-1].bottom_m
            _line(fig,[-fallback*.65,fallback*.65],[depth,depth],'Отбитый забой','#DC3545')
        fig.update_layout(hovermode='closest');fig.update_xaxes(zeroline=False)
    else:raise ValueError('Неизвестный график анализа: '+name)
    return fig

def tables(a):
    out={'Сезоны_'+a['well']:a['seasons'].rename(columns=__import__('app.modules.well_analysis',fromlist=['SEASON_LABELS']).SEASON_LABELS),
         'Выводы_'+a['well']:a['signals'],'Вода_'+a['well']:a['water']}
    for label,field in [('Суточные','daily'),('ГДИ','gdi_history'),('Забой','bottom'),('Конструкция','construction')]:
        if not a[field].empty:out[label+'_'+a['well']]=a[field].drop(columns=['_point_id'],errors='ignore')
    return out

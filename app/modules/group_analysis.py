"""Group totals use all assigned wells; overlays do not change the sum."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from app.core.config import ordered
from app.core.performance import select_wells,cached_chart
from app.modules import charts,production


def daily(df,mapping,group,kind,periods):
    wells=ordered(w for w in df.well.unique() if mapping.get(w,{}).get('group','Без группы')==group)
    d=select_wells(df,wells);d=d[d.kind.eq(kind)&d.period.isin(periods)]
    parts=[]
    for period,g in d.groupby('period',sort=False):
        if (g.date.max()-g.date.min()).days>3660:raise ValueError('Период группы охватывает более 10 лет. Проверьте сезоны.')
        calendar=pd.date_range(g.date.min(),g.date.max())
        # Explicit exclusions remain NaN; only observed measurements contribute.
        valid=g.q.notna()&~g.get('_excluded',pd.Series(False,index=g.index)).fillna(False)
        values=g.q.where(valid)
        work=g[['date','well']].assign(q=values,active=values.gt(0),observed=values.notna())
        a=work.groupby('date').agg(total=('q',lambda x:x.sum(min_count=1)),observed=('observed','sum'),active=('active','sum')).reindex(calendar)
        a['cumulative']=a.total.cumsum()/1e6;a['coverage']=a.observed/len(wells)*100
        a['period']=period;a['date']=calendar;a['expected']=len(wells);parts.append(a.reset_index(drop=True))
    return (pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()),wells


@cached_chart
def figure(df,mapping,group,kind,periods,overlay=None,metric='daily',interactive=True):
    a,wells=daily(df,mapping,group,kind,periods)
    ytitle={'daily':'Суммарный расход, тыс. м³/сут','cumulative':'Накопленный объем, млн м³','active':'Работающих скважин с наблюдениями'}[metric]
    fig=charts.base('Группа '+group,'Дата',ytitle);fig.update_xaxes(type='date');fig.update_layout(meta={'module':'production','wells':wells,'periods':list(periods),'group':group,'group_total':True,'kind':kind})
    colors=production.period_colors(df,kind);palette=charts.well_colors(wells)
    for period,g in a.groupby('period',sort=False) if not a.empty else []:
        g=g.copy();g['value']=g.total/1000 if metric=='daily' else g.cumulative if metric=='cumulative' else g.active.where(g.observed.gt(0))
        if interactive:g=charts.decimate(g,'value')
        fig.add_trace(go.Scatter(x=g.date,y=g.value,name='Сумма · '+period,mode='lines',line={'width':3,'color':colors.get(period)},connectgaps=False,meta={'selectable':False},customdata=np.column_stack([g.observed,g.expected,g.coverage]),hovertemplate='%{x|%d.%m.%Y}<br>Сумма: %{y:.3f}<br>Наблюдений: %{customdata[0]} / %{customdata[1]} скважин<br>Покрытие: %{customdata[2]:.1f}%<extra>%{fullData.name}</extra>'))
    if metric!='active':
        d=select_wells(df,[w for w in (overlay or []) if w in wells]);d=d[d.kind.eq(kind)&d.period.isin(periods)]
        for (well,period),g in d.groupby(['well','period'],sort=False):
            calendar=pd.date_range(g.date.min(),g.date.max());g=g.set_index('date').reindex(calendar)
            values=g.q.where(~g.get('_excluded',pd.Series(False,index=g.index)).fillna(False))
            g['value']=values/1000 if metric=='daily' else values.cumsum()/1e6;g['date']=calendar
            if interactive:g=charts.decimate(g,'value')
            fig.add_trace(go.Scatter(x=g.date,y=g.value,name='№ '+well+' · '+period,mode='lines',line={'width':1.4,'color':palette[well]},connectgaps=False,meta={'selectable':False},hovertemplate='%{x|%d.%m.%Y}<br>%{y:.3f}<extra>%{fullData.name}</extra>'))
    fig.update_yaxes(rangemode='tozero');return fig

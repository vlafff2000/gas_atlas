import numpy as np
import pandas as pd
import plotly.graph_objects as go
import colorsys
from app.core.config import COLORS, ordered
from app.core.exclusions import point_id
from .production import curve_data, averages, period_colors
from .gdi import KEYS, analyze_study, prepare
from app.core.performance import cached_chart

DASH=['solid','dash','dot','dashdot','longdash']

def well_colors(wells):
    colors={}
    for i,well in enumerate(ordered(wells)):
        if i<len(COLORS):color=COLORS[i]
        else:
            rgb=colorsys.hls_to_rgb(((i-len(COLORS))*.61803398875+.08)%1,.40,.68)
            color='#'+''.join('{:02x}'.format(int(v*255)) for v in rgb)
        colors[well]=color
    return colors

def base(title,x,y):
    fig=go.Figure()
    fig.update_layout(template='plotly_white',title={'text':title,'font':{'size':19}},
        font={'family':'Segoe UI, Arial, sans-serif','size':13,'color':'#203c48'},
        margin={'l':65,'r':35,'t':65,'b':85},height=530,
        paper_bgcolor='white',plot_bgcolor='white',xaxis_title=x,yaxis_title=y,
        hovermode='closest',legend={'orientation':'h','y':-.23,'x':0,'font':{'size':11}},
        separators=', ',uirevision=title)
    fig.update_xaxes(gridcolor='#edf1f2',zerolinecolor='#bacbd0')
    fig.update_yaxes(gridcolor='#edf1f2',zerolinecolor='#bacbd0')
    return fig

def decimate(d,column,limit=5000):
    if len(d)<=limit: return d
    if limit<4:limit=4
    indices={0,len(d)-1};vals=d[column].to_numpy(dtype=float)
    # Preserve a gap as well as extrema; an excluded observation must not become a zero.
    for chunk in np.array_split(np.arange(len(d)),max(1,limit//3-1)):
        finite=chunk[np.isfinite(vals[chunk])];missing=chunk[~np.isfinite(vals[chunk])]
        if len(finite):indices.update([int(finite[np.argmin(vals[finite])]),int(finite[np.argmax(vals[finite])])])
        if len(missing):indices.add(int(missing[0]))
    return d.iloc[sorted(indices)]

@cached_chart
def production_curve(df,kind,ps,wells,xmode='cumulative',title=None,interactive=True,editable=False,point_budget=20000):
    fig=base(title or well_title(wells),
        'Накопленный объем объекта, млн м³' if xmode=='cumulative' else 'Дата','Суточный расход, тыс. м³/сут')
    d=curve_data(df,kind,ps,wells);colors=period_colors(df,kind);palette=well_colors(wells)
    fig.update_layout(meta={'module':'production','wells':list(wells),'periods':list(ps),'kind':kind})
    if d.empty:return fig
    groups=d.groupby(['well','period'],sort=False)
    limit=min(5000,max(4,point_budget//max(1,groups.ngroups))) if point_budget else 5000
    for (well,p),g in groups:
        if interactive:g=decimate(g,'q',limit)
        identifiers=g['_point_id'].where(~g.missing,'')
        custom=np.column_stack([identifiers,g.date.dt.strftime('%d.%m.%Y'),g.cumulative,
            g.missing.map({True:'Нет записи: показан 0',False:'Измерение'}),g.file,g.sheet,g['_row']])
        trace=go.Scattergl if interactive and len(d)>10000 else go.Scatter
        fig.add_trace(trace(x=g.cumulative if xmode=='cumulative' else g.date,y=g.q,
            name=str(p) if len(wells)==1 else f'№ {well} · {p}',mode='lines+markers' if editable else 'lines',
            line={'color':palette[well] if len(ps)==1 else colors[p],'width':2,'dash':'solid' if len(ps)==1 else DASH[wells.index(well)%len(DASH)]},marker={'size':6},
            meta={'module':'production','selectable':True},customdata=custom,connectgaps=False,
            hovertemplate=f'<b>Скважина {well} · {p}</b><br>Дата: %{{customdata[1]}}<br>Суточный расход: %{{y:.2f}} тыс. м³/сут<br>Накопленный: %{{customdata[2]:.2f}} млн м³<br>%{{customdata[3]}}<br>%{{customdata[4]}} / %{{customdata[5]}} / строка %{{customdata[6]}}<extra></extra>'))
    fig.update_yaxes(rangemode='tozero')
    if xmode=='cumulative':
        maximum=float(d.cumulative.max())
        step=1000 if maximum>=1000 else 100 if maximum>=300 else 50 if maximum>=150 else 20 if maximum>=60 else 10 if maximum>=30 else 5 if maximum>=15 else 1 if maximum>=3 else None
        fig.update_xaxes(dtick=step,tickformat=',.0f' if maximum>=3 else '.2f',rangemode='tozero')
    return fig

@cached_chart
def histogram(df,kind,ps,wells,axis='well',title=None):
    fig=base(title or well_title(wells),'Скважина' if axis=='well' else 'Период','Средний расход, тыс. м³/сут')
    data=averages(df,kind,ps,wells);colors=period_colors(df,kind)
    fig.update_layout(meta={'module':'production','wells':list(wells),'periods':list(ps),'kind':kind,'histogram':True})
    if data.empty:return fig
    for i,key in enumerate(ps if axis=='well' else wells):
        d=data[data.period.eq(key)] if axis=='well' else data[data.well.eq(key)]
        order=wells if axis=='well' else ps
        d=d.set_index('well' if axis=='well' else 'period').reindex(order).reset_index()
        custom=np.column_stack([d.active,d.zero,d.volume])
        fig.add_trace(go.Bar(x=d.iloc[:,0].astype(str),y=d.value,name=('Средний расход' if len(wells)==1 and axis=='period' else str(key)),marker_color=colors.get(key,COLORS[i%len(COLORS)]),
            customdata=custom,meta={'selectable':False},
            hovertemplate='%{x}<br>Средний: %{y:.2f} тыс. м³/сут<br>Активных дней: %{customdata[0]}<br>Нулевых записей: %{customdata[1]}<br>Объем: %{customdata[2]:.3f} млн м³<extra>%{fullData.name}</extra>'))
    fig.update_layout(barmode='group');fig.update_xaxes(type='category',categoryorder='array',categoryarray=wells if axis=='well' else ps)
    return fig

@cached_chart
def gdi_chart(df,well,threshold=.95,orientation='standard',curves=True,db_curves=True,crosshair=True,raw_df=None,show_excluded=True):
    swapped=orientation=='swapped'
    fig=base(well_title([well]),
        'ΔP²' if swapped else 'Q, тыс. м³/сут','Q, тыс. м³/сут' if swapped else 'ΔP²')
    d=prepare(df);d=d[d.well.eq(well)]
    ds=sorted(d.date.unique(),reverse=True);palette={date:COLORS[i%len(COLORS)] for i,date in enumerate(ds)}
    for i,(key,g) in enumerate(d.groupby(KEYS,sort=False,dropna=False)):
        _,date,method,study=key;color=palette[date];r=analyze_study(g,threshold)
        label=date.strftime('%d.%m.%Y')+(' · '+method if method else '')+(' · '+study if study else '')
        ids=g['_point_id'] if '_point_id' in g else pd.Series('',index=g.index)
        fig.add_trace(go.Scatter(x=g.dp2 if swapped else g.q,y=g.q if swapped else g.dp2,mode='markers',name=label,legendgroup=label,
            marker={'color':color,'size':9,'symbol':['circle','square','diamond','triangle-up'][i%4]},
            meta={'module':'gdi','selectable':True},customdata=np.column_stack([ids,g.q,g.dp2]),
            hovertemplate=label+'<br>Q: %{customdata[1]:.3f} тыс. м³/сут<br>ΔP²: %{customdata[2]:.3f}<extra></extra>'))
        q=np.linspace(0,max(float(g.q.max()),1)*1.05,240)
        for show,a,b,r2,suffix,dash in [(curves,r['a_calc'],r['b_calc'],r['r2_calc'],'расчет','solid'),
                                      (db_curves,r['a_db'],r['b_db'],r['r2_db'],'БД','dash')]:
            if not show or a is None or b is None:continue
            y=a*q+b*q*q
            hover=label+f' · {suffix}<br>a = {a:.6g}<br>b = {b:.6g}'
            if r2 is not None:hover+=f'<br>R² = {r2:.4f}'
            hover+='<br>Q: %{customdata[0]:.3f} тыс. м³/сут<br>ΔP²: %{customdata[1]:.3f}<extra></extra>'
            fig.add_trace(go.Scatter(x=y if swapped else q,y=q if swapped else y,mode='lines',
                name=label+' · '+suffix,legendgroup=label,showlegend=False,line={'color':color,'width':1.8,'dash':dash},
                customdata=np.column_stack([q,y]),meta={'module':'gdi','selectable':False},hovertemplate=hover))
    fig.update_layout(meta={'module':'gdi','wells':[well]},height=600,margin={'l':65,'r':30,'t':55,'b':55},
        legend={'orientation':'h','y':-.13,'x':0,'yanchor':'top','font':{'size':10},'groupclick':'togglegroup'})
    if show_excluded and raw_df is not None and '_point_id' in raw_df:
        excluded=raw_df[raw_df.well.eq(well)&~raw_df['_point_id'].isin(df.get('_point_id',[]))]
        if not excluded.empty:
            fig.add_trace(go.Scatter(x=excluded.dp2 if swapped else excluded.q,y=excluded.q if swapped else excluded.dp2,mode='markers',name='Исключенные точки',
                marker={'size':10,'color':'#969da5','symbol':'circle-open','line':{'width':2}},meta={'module':'gdi','selectable':False},
                hovertemplate='Исключено из расчета<br>X: %{x:.3f}<br>Y: %{y:.3f}<extra></extra>'))
    fig.update_xaxes(rangemode='tozero');fig.update_yaxes(rangemode='tozero')
    if crosshair:
        fig.update_xaxes(showspikes=True,spikemode='across+toaxis',spikesnap='hovered data',spikedash='dot',spikecolor='#637782',spikethickness=1)
        fig.update_yaxes(showspikes=True,spikemode='across+toaxis',spikesnap='hovered data',spikedash='dot',spikecolor='#637782',spikethickness=1)
        fig.update_layout(hoverdistance=30,spikedistance=-1)
    return fig

def well_title(wells,group=None):
    if len(wells)==1:return 'Скважина №'+str(wells[0])
    if group:return 'Группа '+str(group)
    return 'Скважины №'+', '.join(map(str,wells))


def style_figure(figure,style=None,copy_figure=True):
    style=style or {};fig=go.Figure(figure) if copy_figure else figure
    fig.update_layout(showlegend=style.get('legend',True))
    fig.update_xaxes(showgrid=style.get('grid',True))
    fig.update_yaxes(showgrid=style.get('grid',True))
    if 'yaxis2' in fig.layout and fig.layout.yaxis2.overlaying:fig.layout.yaxis2.showgrid=False
    if not style.get('points',True):
        for trace in fig.data:
            if trace.type=='bar':continue
            if 'markers' in (trace.mode or ''):
                if 'lines' in trace.mode:trace.mode='lines'
                else:trace.visible=False
    # A study still needs one legend item when measured markers are hidden.
    if not style.get('points',True):
        visible_groups=set(t.legendgroup for t in fig.data if t.visible is not False and t.showlegend is not False)
        for trace in fig.data:
            if isinstance(trace.meta,dict) and trace.meta.get('module')=='gdi' and trace.visible is not False and trace.legendgroup and trace.legendgroup not in visible_groups:
                trace.showlegend=True;trace.name=trace.legendgroup;visible_groups.add(trace.legendgroup)
    return fig


@cached_chart
def response_chart(df,working,metric='level',title=None,interactive=True,color_map=None,
                   object_pressure=None,manometer_wells=None,by_well=False,pressure_horizons=None):
    wells=ordered(df.well) if 'well' in df else []
    manometer=set(manometer_wells or [])
    pressure_horizons=set(pressure_horizons if pressure_horizons is not None else df.loc[df.pressure.notna(),'horizon'].unique() if 'pressure' in df else [])
    pressure_enabled=bool(set(df.horizon).intersection(pressure_horizons)) if not df.empty else False
    dual=metric=='combined' and pressure_enabled
    fig=base(title or well_title(wells),'Дата','Пластовое давление, кгс/см²' if metric=='pressure' or dual else 'Уровень жидкости, м')
    fig.update_layout(meta={'module':'response','wells':wells,'horizons':ordered(df.horizon) if 'horizon' in df else [],'metric':metric})
    fig.update_xaxes(type='date')
    if df.empty:return fig
    palette=color_map or well_colors(wells)
    legends=set()
    metrics=['level','pressure'] if metric=='combined' else [metric]
    for (h,w),g in df.groupby(['horizon','well'],sort=True):
        semantic=by_well and h in pressure_horizons
        for field in metrics:
            if field not in g or not g[field].notna().any():continue
            data=g.sort_values('date')
            if interactive:data=decimate(data,field)
            ids=data['_point_id'].map(lambda value:point_id('response',value,field)) if '_point_id' in data else pd.Series('',index=data.index)
            unit='м' if field=='level' else 'кгс/см²'
            suffix='уровень жидкости' if field=='level' else 'давление (глубинный манометр)' if w in manometer else 'давление (пересчет)'
            color=('#32BDA4' if field=='level' else '#8B5CF6' if w in manometer else '#2563EB') if semantic else palette[w]
            marker={'size':6,'symbol':'circle' if field=='level' else 'diamond','color':color}
            if field=='level' and semantic:marker.update(color='white',line={'color':color,'width':1.8})
            fig.add_trace(go.Scatter(x=data.date,y=data[field],mode='lines+markers',
                name=suffix.capitalize() if by_well and len(wells)==1 else '№ '+str(w),
                legendgroup=('well_'+str(w)+'_'+field+'_'+h if by_well else 'well_'+str(w)),
                showlegend=(h,w,field) not in legends if by_well else w not in legends,
                line={'color':color,'width':2,'dash':'solid'},marker=marker,
                yaxis='y2' if dual and field=='level' else 'y',connectgaps=False,
                customdata=np.column_stack([ids]),meta={'module':'response','metric':field,'selectable':True},
                hovertemplate=f'{h} · скв. {w} · {suffix}<br>Дата: %{{x|%d.%m.%Y}}<br>Значение: %{{y:.2f}} {unit}<extra></extra>'))
            legends.add((h,w,field) if by_well else w)
    if pressure_enabled and metric in ('pressure','combined') and object_pressure is not None and not object_pressure.empty:
        data=object_pressure.sort_values('date')
        data=data[data.date.between(df.date.min(),df.date.max())]
        if interactive:data=decimate(data,'pressure')
        if not data.empty:
            ids=data['_point_id'] if '_point_id' in data else pd.Series('',index=data.index)
            fig.add_trace(go.Scatter(x=data.date,y=data.pressure,mode='lines+markers',name='Пластовое давление объекта',
                line={'color':'#DC3545','width':2,'dash':'solid'},marker={'size':5,'color':'#DC3545'},
                meta={'module':'object_pressure','metric':'pressure','selectable':True},customdata=np.column_stack([ids]),
                hovertemplate='Пластовое давление объекта<br>%{x|%d.%m.%Y}<br>%{y:.2f} кгс/см²<extra></extra>'))
    if metric=='level' or (metric=='combined' and not dual):fig.update_layout(yaxis={'autorange':'reversed'})
    if dual:
        fig.update_layout(yaxis={'autorange':True,'title':'Пластовое давление, кгс/см²'},
            yaxis2={'title':'Уровень жидкости, м','overlaying':'y','side':'right','showgrid':False,'autorange':'reversed'},margin={'r':85})
    return fig


def response_title(wells,label=None,split='horizon'):
    return 'Горизонт '+str(label) if split=='horizon' else well_title(wells)

import numpy as np
import pandas as pd
from app.core import exclusions,reporting
from app.core.demo import demo_frames
from app.core.storage import Store
from app.core.config import DEFAULT_SETTINGS
from app.core.export import figure_bytes
from app.modules import gdi,production,charts


def outlier_frames():
    q=np.array([20.,50.,80.,120.,180.]);y=.7*q+.012*q*q;y[-1]*=1.4
    d=pd.DataFrame(dict(well='31',date=pd.Timestamp('2026-01-01'),q=q,dp2=y,method='',study='',p_res=75.))
    return exclusions.identify_frames({'gdi':d})

def test_exclusion_rebuilds_gdi_and_restores_exactly():
    raw=outlier_frames();original=raw['gdi'].copy();before=gdi.analyze(raw['gdi']).iloc[0]
    identifier=raw['gdi']._point_id.iloc[-1];entry=exclusions.entry(raw,'gdi',identifier)
    active=exclusions.apply(raw,{'excluded_points':{identifier:entry}})
    after=gdi.analyze(active['gdi']).iloc[0]
    assert after.points==4 and np.allclose([after.a_calc,after.b_calc],[.7,.012],rtol=1e-6)
    assert not np.isclose(before.b_calc,after.b_calc)
    pd.testing.assert_frame_equal(original,raw['gdi'])
    pd.testing.assert_frame_equal(gdi.analyze(exclusions.apply(raw,{})['gdi']),gdi.analyze(original))

def test_production_exclusion_is_a_gap_and_changes_volumes_and_means():
    source=pd.DataFrame(dict(well=['1','1','2'],date=pd.to_datetime(['2025-11-01','2025-11-02','2025-11-01']),q=[1000.,3000.,5000.],kind='withdrawal'))
    raw=exclusions.identify_frames({'production':source});identifier=raw['production']._point_id.iloc[0]
    cfg={'excluded_points':{identifier:exclusions.entry(raw,'production',identifier)}}
    active=production.periods(exclusions.apply(raw,cfg)['production'])
    curve=production.curve_data(active,'withdrawal',['2025-2026'],['1'])
    assert np.isnan(curve.q.iloc[0]) and not curve.missing.iloc[0]
    assert curve.cumulative.tolist()==[.005,.008]
    avg=production.averages(active,'withdrawal',['2025-2026'],['1']).iloc[0]
    assert avg.value==3 and avg.active==1 and avg.zero==0

def test_response_exclusion_is_metric_specific():
    raw=exclusions.identify_frames(demo_frames());row=raw['response'].iloc[0]
    identifier=exclusions.point_id('response',row._point_id,'level')
    cfg={'excluded_points':{identifier:exclusions.entry(raw,'response',identifier,'level')}}
    active=exclusions.apply(raw,cfg)['response']
    assert np.isnan(active.level.iloc[0]) and active.pressure.iloc[0]==row.pressure
    assert raw['response'].level.iloc[0]==row.level

def test_identifiers_survive_reordering_and_backup(tmp_path):
    raw=outlier_frames();source=raw['gdi'];reordered=exclusions.identify(source.iloc[::-1],'gdi')
    assert dict(zip(source.q,source._point_id))==dict(zip(reordered.q,reordered._point_id))
    identifier=source._point_id.iloc[-1]
    settings={**DEFAULT_SETTINGS,'excluded_points':{identifier:exclusions.entry(raw,'gdi',identifier)}}
    store=Store(tmp_path);pid=store.create('v5');store.commit(pid,raw,settings=settings)
    restored=store.restore(store.backup(pid));manifest,data=store.load(restored)
    assert len(exclusions.apply(exclusions.identify_frames(data),manifest['settings'])['gdi'])==4
    assert manifest['settings']['excluded_points'][identifier]['q']==180

def test_export_controls_remove_both_curves_and_apply_exclusions():
    raw=outlier_frames();identifier=raw['gdi']._point_id.iloc[-1]
    settings={**DEFAULT_SETTINGS,'excluded_points':{identifier:exclusions.entry(raw,'gdi',identifier)}}
    options={'modules':['gdi'],'wells':['31'],'gdi':{'wells':['31'],'n':0,'curves':False,'db_curves':False,'orientation':'swapped'},'apply_exclusions':True}
    figures,tables=reporting.build(exclusions.apply(raw,settings),{},settings,options)
    figure=next(iter(figures.values()))
    assert len(figure.data)==1 and figure.data[0].mode=='markers' and len(figure.data[0].x)==4
    assert figure.layout.xaxis.title.text=='ΔP²' and 'R²' not in figure.data[0].name
    assert tables['ГДИ'].points.iloc[0]==4 and len(tables['Исключенные_точки'])==1

def test_combined_response_has_independent_axes_in_svg():
    d=demo_frames()['response'];d=d[d.horizon.eq('Окский')]
    figure=charts.response_chart(d,['Окский'],'combined')
    assert figure.layout.yaxis.autorange=='reversed' and figure.layout.yaxis2.autorange is True
    assert {t.yaxis for t in figure.data}=={'y','y2'}
    assert all(t.line.dash=='solid' for t in figure.data)
    assert len({t.line.color for t in figure.data})==3
    svg=figure_bytes(figure,'svg',300,220).decode()
    assert 'Уровень жидкости, м' in svg and 'Рпл привед., кгс/см²' in svg
    assert 'watermark' not in svg.lower() and 'OpenAI' not in svg

def test_gdi_curve_tooltip_ruler_and_clean_legend():
    figure=charts.gdi_chart(outlier_frames()['gdi'],'31')
    assert figure.layout.yaxis.title.text=='ΔP²'
    assert figure.layout.xaxis.showspikes and figure.layout.yaxis.showspikes
    for trace in figure.data:
        assert 'R²' not in trace.name and 'кгс²' not in trace.name
        if trace.mode=='lines':assert 'a = ' in trace.hovertemplate and 'b = ' in trace.hovertemplate

def test_well_colors_are_unique_and_reused_across_metrics():
    palette=charts.well_colors([str(i) for i in range(40)])
    assert len(set(palette.values()))==40
    d=demo_frames()['response'];fig=charts.response_chart(d,[],'combined',color_map=charts.well_colors(d.well))
    colors={}
    for trace in fig.data:
        well=trace.name.split('№ ')[1].split(' · ')[0]
        if well in colors:assert colors[well]==trace.line.color
        colors[well]=trace.line.color

def test_decimation_keeps_exclusion_gap():
    d=pd.DataFrame({'q':np.sin(np.arange(12000)/40)});d.loc[7000,'q']=np.nan
    small=charts.decimate(d,'q')
    assert len(small)<=5000 and 7000 in small.index and small.q.isna().any()

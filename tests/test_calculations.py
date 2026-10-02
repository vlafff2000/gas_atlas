import io
import zipfile
import numpy as np
import pandas as pd
from PIL import Image
from app.core.loader import numeric,dates,merge_frames
from app.core.demo import demo_frames
from app.modules import production,gdi,response,charts
from app.core.export import figure_bytes,export_zip

def test_pressure_difference():
    assert abs(75.4**2-71.01**2-642.7399)<1e-8

def test_fit_known_coefficients():
    q=np.array([20,50,80,120,180],float); y=.7*q+.012*q*q
    a,b,r=gdi.fit(q,y)
    assert np.allclose([a,b,r],[.7,.012,1],rtol=1e-7)

def test_singular_and_zero_rates():
    assert gdi.fit([1,1],[10,20])==(None,None,None)
    assert gdi.fit([0,10],[0,5])==(None,None,None)

def test_db_priority_and_poor_fit():
    q=np.array([20,50,80,120,180],float); y=.7*q+.012*q*q
    d=pd.DataFrame(dict(q=q,dp2=y,a_db=.71,b_db=.012,p_res=75.))
    r=gdi.analyze_study(d); assert r['source']=='БД'
    d['a_db']=30;d['b_db']=1
    r=gdi.analyze_study(d); assert r['source']=='Расчет'
    assert abs(r['a']-.7)<1e-6

def test_free_flow_root_and_missing_pressure():
    q=gdi.free_flow(.7,.012,75)
    assert abs(.7*q+.012*q*q-75**2)<1e-8
    assert gdi.free_flow(-1,2,75) is None
    d=pd.DataFrame(dict(q=[20.,50.,80.],dp2=[18.8,65,132.8]))
    assert gdi.analyze_study(d)['q_free'] is None

def test_pair_sort_preserves_measurements():
    d=pd.DataFrame(dict(q=[3.,1.,2.],dp2=[30.,25.,10.]))
    status,delta=gdi.compare_pair(d,d.iloc[::-1]); assert status=='Без изменений' and abs(delta)<1e-12
    improved=d.copy(); improved.dp2*=.7
    assert gdi.compare_pair(improved,d)[0]=='Улучшение'

def small_production():
    return production.periods(pd.DataFrame([
        dict(well='1',date=pd.Timestamp('2025-11-01'),q=1000.,kind='withdrawal'),
        dict(well='2',date=pd.Timestamp('2025-11-01'),q=2000.,kind='withdrawal'),
        dict(well='1',date=pd.Timestamp('2025-11-03'),q=0.,kind='withdrawal'),
        dict(well='2',date=pd.Timestamp('2025-11-03'),q=5000.,kind='withdrawal')]))

def test_object_accumulation_and_missing_days():
    d=small_production(); c=production.curve_data(d,'withdrawal',['2025-2026'],['1'])
    assert np.allclose(c.cumulative,[.003,.003,.008])
    assert c.q.tolist()==[1,0,0]; assert c.missing.tolist()==[False,True,False]
    full=production.curve_data(d,'withdrawal',['2025-2026'],['1','2'])
    assert np.allclose(c.cumulative,full[full.well.eq('1')].cumulative)

def test_average_excludes_zero_and_missing():
    a=production.averages(small_production(),'withdrawal',['2025-2026'],['1','2','3'])
    assert a.value.iloc[0]==1.; assert a.value.iloc[1]==3.5; assert a.missing.iloc[2]

def test_seasons_and_colors():
    d=demo_frames()['production']; d=production.periods(d)
    colors=production.period_colors(d,'withdrawal')
    assert colors['2025-2026']=='#dc3545' and colors['2024-2025']=='#2563eb'
    sample=pd.DataFrame([dict(date=pd.Timestamp('2026-07-01'),well='1',q=1,kind='withdrawal')])
    assert production.periods(sample).period.iloc[0]=='Вне сезона 2026'

def test_numeric_and_dates():
    assert numeric(pd.Series(['29,4 м','10-20 м','сухо','-3.5']),level=True).fillna(-999).tolist()==[29.4,-999,-999,-3.5]
    values=dates(pd.Series(['11.01.04','2026-09-29',46023,'31.02.2025']))
    assert values[0]==pd.Timestamp('2004-01-11') and values[1]==pd.Timestamp('2026-09-29') and pd.isna(values[3])

def test_duplicate_daily_not_sum():
    d=small_production(); incoming=d.iloc[:1].copy(); incoming.q=4000
    merged,n=merge_frames(d,incoming,'production','new')
    assert len(merged)==4 and merged[merged.well.eq('1')].q.sum()==4000
    old,_=merge_frames(d,incoming,'production','old'); assert old[old.well.eq('1')].q.sum()==1000

def test_gdi_replace_entire_study():
    d=demo_frames()['gdi'].query('well=="31"'); incoming=d[d.date.eq(d.date.max())].iloc[:2].copy()
    merged,_=merge_frames(d,incoming,'gdi','new')
    assert len(merged[merged.date.eq(d.date.max())])==2

def test_response_reverse_and_color():
    d=demo_frames()['response']; d=d[d.horizon.eq('Окский')]; fig=charts.response_chart(d,['Окский'])
    assert fig.layout.yaxis.autorange=='reversed'
    assert len({t.line.color for t in fig.data})==3
    assert all(t.line.dash=='solid' for t in fig.data)

def test_all_exports_readable():
    d=production.periods(demo_frames()['production']); fig=charts.production_curve(d,'withdrawal',['2025-2026'],['31'])
    png=figure_bytes(fig,'png',300,180); im=Image.open(io.BytesIO(png))
    assert abs(im.info['dpi'][0]-300)<.1 and im.width==int(180/25.4*300)
    assert b'<svg' in figure_bytes(fig,'svg'); assert figure_bytes(fig,'pdf').startswith(b'%PDF')
    z=zipfile.ZipFile(io.BytesIO(export_zip({'curve':fig},{'data':d.head()},('svg',))))
    assert 'results.xlsx' in z.namelist(); assert z.testzip() is None

def test_histogram_export():
    d=small_production(); fig=charts.histogram(d,'withdrawal',['2025-2026'],['1','2'])
    assert figure_bytes(fig,'pdf').startswith(b'%PDF')

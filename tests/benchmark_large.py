"""Optional benchmark, not part of pytest. Creates only temporary test data."""
from pathlib import Path
import datetime
import json
try:
    import resource
except ImportError:
    resource=None
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.loader import load_file
from app.core.storage import Store
from app.core import exclusions
from app.modules.production import periods,curve_data

def main():
    with tempfile.TemporaryDirectory(prefix='gas_atlas_benchmark_') as directory:
        root=Path(directory);path=root/'large_input.csv';rows=1_000_000
        with path.open('w',encoding='utf8') as f:
            f.write('Скважина;Дата;Расход;Примечание\n')
            for day in range(1000):
                date=datetime.date(2023,1,1)+datetime.timedelta(days=day)
                for well in range(1,1001):
                    f.write(f'{well};{date.isoformat()};{9999+well};'+('контрольный текст '*6)+'\n')
        started=time.perf_counter();result=load_file(path);import_s=time.perf_counter()-started
        assert result.rejected==0 and len(result.frames['production'])==rows
        store=Store(root/'storage');pid=store.create('Нагрузочная проверка')
        started=time.perf_counter();store.commit(pid,result.frames);save_s=time.perf_counter()-started
        started=time.perf_counter();manifest,frames=store.load(pid);reload_s=time.perf_counter()-started
        assert len(frames['production'])==rows
        data=periods(frames['production']);curve=curve_data(data,'withdrawal',data.period.unique().tolist(),['73'])
        assert len(curve)==1000 and curve.q.max()==10.072
        started=time.perf_counter();identified=exclusions.identify_frames(frames);identity_s=time.perf_counter()-started
        last=identified['production'].iloc[-1];identifier=last['_point_id']
        started=time.perf_counter()
        filtered=exclusions.apply(identified,{'excluded_points':{identifier:exclusions.entry(identified,'production',identifier)}})
        filter_s=time.perf_counter()-started
        assert filtered['production'].q.isna().sum()==1 and not identified['production'].q.isna().any()
        assert abs(identified['production'].q.sum()-filtered['production'].q.sum()-last.q)<1e-6
        report={'rows':rows,'file_mib':path.stat().st_size/1024**2,'import_seconds':import_s,'save_seconds':save_s,
                'reload_seconds':reload_s,'identity_seconds':identity_s,'exclusion_seconds':filter_s,
                'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024 if resource else None,'result':'PASS'}
        print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()

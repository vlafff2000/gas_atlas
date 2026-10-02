"""Generate synthetic pressure workbooks (fact + model + fond sheets) for testing the crossplot import.

Usage: python tools/make_pressure_samples.py OUT_DIR [FILES] [WELLS] [DATES]
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

def make_book(path,seed,wells=12,dates=60,scenarios=('Модель 1','Модель 2')):
    rng=np.random.default_rng(seed)
    days=pd.date_range('2021-01-01',periods=dates,freq='15D')
    ids=[str(100+seed*50+i) for i in range(wells)]
    base=rng.uniform(80,140,wells)
    fact=pd.DataFrame({'Дата':days})
    for w,b in zip(ids,base):fact[w]=b+np.sin(np.arange(dates)/6)*6+rng.normal(0,1.5,dates)
    with pd.ExcelWriter(path) as xl:
        fact.to_excel(xl,sheet_name='Факт',index=False)
        for k,name in enumerate(scenarios):
            model=fact.copy()
            for w in ids:model[w]=fact[w]+rng.normal(k*1.5,3+k*2,dates)
            model.to_excel(xl,sheet_name=name,index=False)
        pd.DataFrame({'Скважина':ids,'Тип':['Действующая' if i%4 else 'Наблюдательная' for i in range(wells)]}).to_excel(xl,sheet_name='Фонд',index=False)

if __name__=='__main__':
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    files=int(sys.argv[2]) if len(sys.argv)>2 else 3
    wells=int(sys.argv[3]) if len(sys.argv)>3 else 12
    dates=int(sys.argv[4]) if len(sys.argv)>4 else 60
    for i in range(files):make_book(out/('Объект_{:02d}.xlsx'.format(i+1)),i,wells,dates)
    print('written',files,'books to',out)

"""One Excel book: statistics, reproducible percentile inputs and editable charts."""
import io
import re
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import ScatterChart,BarChart,Reference,Series
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.worksheet.datavalidation import DataValidation
from atlas.engine.core.export import safe_table


def workbook_bytes(tables,cfg=None):
    cfg=cfg or {};wb=Workbook();wb.remove(wb.active);ps=cfg.get('percentiles',[80,85,90])
    def add(title,data):
        title=re.sub(r'[\[\]:*?/\\]','_',title)[:31];base=title;i=2
        while title in wb.sheetnames:title=base[:27]+'_'+str(i);i+=1
        ws=wb.create_sheet(title);ws.append([str(c) for c in data.columns]);ws.freeze_panes='A2'
        for row in safe_table(data).itertuples(index=False,name=None):
            vals=[]
            for v in row:
                if pd.isna(v):v=None
                elif isinstance(v,np.generic):v=v.item()
                elif isinstance(v,pd.Timestamp):v=v.to_pydatetime()
                vals.append(v)
            ws.append(vals)
        for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='243247')
        for cells in ws.columns:
            letter=cells[0].column_letter;ws.column_dimensions[letter].width=min(45,max(12,max(len(str(c.value or '')) for c in cells[:100])+2))
        ws.auto_filter.ref=ws.dimensions
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value,float):c.number_format='0.000'
                elif isinstance(c.value,__import__('datetime').datetime):c.number_format='DD.MM.YYYY'
        return ws
    for name,data in tables.items():
        if len(data)>1_048_575:raise ValueError('Таблица превышает лимит Excel; используйте CSV в архиве.')
        add(name,data)
    d=tables.get('Данные кросс-плота',pd.DataFrame())
    if not d.empty:
        # Explicit helper columns remove array-formula dependencies and locale errors.
        cols={"Все данные":d.error,"Последние 3 года":d.error.where(d.recent)}
        for fond in d.fond.drop_duplicates():
            cols[str(fond)]=d.error.where(d.fond.eq(fond));cols[str(fond)+' · 3 года']=d.error.where(d.fond.eq(fond)&d.recent)
        calc=wb.create_sheet('Расчет процентилей');calc.append(['Процентиль']+list(cols));start=len(ps)+5
        calc.cell(start,1,'Наблюдения: абсолютное отклонение')
        for col,(label,values) in enumerate(cols.items(),2):
            calc.cell(start,col,label)
            for row,value in enumerate(values,start+1):calc.cell(row,col,float(value) if pd.notna(value) else None)
            from openpyxl.utils import get_column_letter
            letter=get_column_letter(col);end=start+len(values)
            for row,p in enumerate(ps,2):
                calc.cell(row,1,float(p)/100).number_format='0%'
                calc.cell(row,col,'=IF(COUNT({0}{1}:{0}{2})=0,"",_xlfn.PERCENTILE.INC({0}{1}:{0}{2},$A{3}))'.format(letter,start+1,end,row)).number_format='0.000'
        calc.freeze_panes='B2'
        # Drop-downs use hidden ranges, so long well lists and names with commas work.
        lists=wb.create_sheet('_Списки');lists.sheet_state='hidden';list_col=0
        def selector(ws,cell,values):
            nonlocal list_col
            from openpyxl.utils import get_column_letter
            list_col+=1;letter=get_column_letter(list_col)
            for n,value in enumerate(values,1):lists.cell(n,list_col,str(value))
            dv=DataValidation(type='list',formula1="'_Списки'!${0}$1:${0}${1}".format(letter,len(values)),allow_blank=False)
            ws.add_data_validation(dv);dv.add(ws[cell]);ws[cell]=str(values[0]);ws[cell].fill=PatternFill('solid',fgColor='FFF2CC')
        def add_series(chart,ws,xcol,ycol,first,last,title,points=False):
            series=Series(Reference(ws,min_col=ycol,min_row=first,max_row=last),Reference(ws,min_col=xcol,min_row=first,max_row=last),title=title)
            if points:series.graphicalProperties.line.noFill=True;series.marker.symbol='circle';series.marker.size=4
            chart.series.append(series)
        # Dynamic Excel crossplots: filter points AND percentile lines, using ordinary formulas.
        ws=wb.create_sheet('Кросс-плоты');ws['A1']='Период';selector(ws,'B1',['Все данные','Последние 3 года']);ws['D1']='Фонд';selector(ws,'E1',['Все']+list(d.fond.drop_duplicates()));row=4;position=4
        for (obj,scenario),g in d.groupby(['object','scenario'],sort=False):
            ws.cell(row,1,obj+' · '+scenario);row+=1
            for col,label in enumerate(['Факт','Модель','Скважина','Дата','Фонд','Недавняя','X графика','Y графика','Ошибка графика'],1):ws.cell(row,col,label)
            first=row+1
            for item in g.itertuples():
                row+=1
                for col,value in enumerate([float(item.fact),float(item.model),str(item.well),item.date.to_pydatetime(),item.fond,int(item.recent)],1):ws.cell(row,col,value)
                condition='AND(OR($B$1="Все данные",F{0}=1),OR($E$1="Все",E{0}=$E$1))'.format(row)
                for col,value in [(7,'A'+str(row)),(8,'B'+str(row)),(9,'ABS(B{0}-A{0})'.format(row))]:ws.cell(row,col,'=IF('+condition+','+value+','+('""' if col==9 else 'NA()')+')')
            last=row
            chart=ScatterChart();chart.title=obj+' · '+scenario;chart.x_axis.title='Фактическое давление';chart.y_axis.title='Модельное давление';chart.width=22;chart.height=14
            add_series(chart,ws,7,8,first,last,'Факт / модель',True)
            lo=float(min(g.fact.min(),g.model.min()));hi=float(max(g.fact.max(),g.model.max()));line_row=row+3
            ws.cell(line_row,1,'Линия X');ws.cell(line_row,2,'Идеальное совпадение')
            for offset,value in enumerate([lo,hi],1):ws.cell(line_row+offset,1,value);ws.cell(line_row+offset,2,value)
            add_series(chart,ws,1,2,line_row+1,line_row+2,'Идеальное совпадение')
            for n,p in enumerate(ps):
                for sign in (-1,1):
                    col=3+2*n+(sign==1);ws.cell(line_row,col,'P{:g} ({:+d})'.format(p,sign))
                    formula='_xlfn.PERCENTILE.INC(I{0}:I{1},{2})'.format(first,last,float(p)/100)
                    for offset in (1,2):ws.cell(line_row+offset,col,'=IF(COUNT(I{0}:I{1})=0,NA(),A{2}{3}{4})'.format(first,last,line_row+offset,'+' if sign==1 else '-',formula))
                    add_series(chart,ws,1,col,line_row+1,line_row+2,'P{:g} ({:+d})'.format(p,sign))
            ws.add_chart(chart,'K'+str(position));position+=29;row=line_row+5
        # Dynamic per-well analysis replaces console choice and Excel array formulas.
        for fond,subset in [('Все',d)]+[(str(f),d[d.fond.eq(f)]) for f in d.fond.drop_duplicates()]:
            sheet=wb.create_sheet(re.sub(r'[\[\]:*?/\\]','_', 'Анализ '+fond)[:31]);sheet['A1']='Скважина';selector(sheet,'B1',list(subset.well.drop_duplicates()));sheet['D1']='Период';selector(sheet,'E1',['Все данные','Последние 3 года']);sheet['G1']='Сценарий';selector(sheet,'H1',list(subset.scenario.drop_duplicates()))
            for col,label in enumerate(['Дата','Факт','Модель','Скважина','Сценарий','Недавняя','Факт графика','Модель графика','Ошибка графика'],1):sheet.cell(4,col,label)
            for row,item in enumerate(subset.itertuples(),5):
                for col,value in enumerate([item.date.to_pydatetime(),float(item.fact),float(item.model),str(item.well),item.scenario,int(item.recent)],1):sheet.cell(row,col,value)
                condition='AND(D{0}=$B$1,E{0}=$H$1,OR($E$1="Все данные",F{0}=1))'.format(row)
                for col,value in [(7,'B'+str(row)),(8,'C'+str(row)),(9,'ABS(C{0}-B{0})'.format(row))]:sheet.cell(row,col,'=IF('+condition+','+value+','+('""' if col==9 else 'NA()')+')')
            last=4+len(subset);chart=ScatterChart();chart.title='Динамика выбранной скважины';chart.x_axis.title='Дата';chart.y_axis.title='Давление';chart.width=24;chart.height=14
            chart.x_axis.numFmt='dd.mm.yyyy'
            add_series(chart,sheet,1,7,5,last,'Факт');add_series(chart,sheet,1,8,5,last,'Модель');sheet.add_chart(chart,'K8')
            cross=ScatterChart();cross.title='Кроссплот выбранной скважины';cross.x_axis.title='Фактическое давление';cross.y_axis.title='Модельное давление';cross.width=24;cross.height=14
            add_series(cross,sheet,7,8,5,last,'Факт / модель',True);sheet.add_chart(cross,'K37')
            sheet['K3']='Точек';sheet['L3']='=COUNT(I5:I{0})'.format(last)
            for n,p in enumerate(ps,4):sheet.cell(n,11,'P{:g}'.format(p));sheet.cell(n,12,'=IF(COUNT(I5:I{0})=0,"",_xlfn.PERCENTILE.INC(I5:I{0},{1}))'.format(last,float(p)/100))
            for n,(label,formula) in enumerate([('Среднее','AVERAGE'),('Медиана','MEDIAN'),('Стандартное отклонение','_xlfn.STDEV.P')],4+len(ps)):
                sheet.cell(n,11,label);sheet.cell(n,12,'=IF(COUNT(I5:I{0})=0,"",{1}(I5:I{0}))'.format(last,formula))
            bars=BarChart();bars.title='Процентили выбранной скважины';bars.add_data(Reference(sheet,min_col=12,min_row=4,max_row=3+len(ps)));bars.set_categories(Reference(sheet,min_col=11,min_row=4,max_row=3+len(ps)));bars.width=22;bars.height=10;sheet.add_chart(bars,'K66')
            sheet.freeze_panes='A5'
        # Histograms are precomputed using a shared interval grid; never depend on Excel's automatic binning.
        hist=wb.create_sheet('Гистограммы');row=1;position=1;bins=int(cfg.get('bins',20))
        for (obj,scenario,fond),g in d.groupby(['object','scenario','fond'],sort=False):
            counts,edges=np.histogram(g.error,bins=bins);hist.cell(row,1,obj+' · '+scenario+' · '+fond);row+=1;hist.append([])
            hist.cell(row,1,'Интервал');hist.cell(row,2,'Точек');startrow=row
            for n,lo,hi in zip(counts,edges[:-1],edges[1:]):row+=1;hist.cell(row,1,'{:.3g}–{:.3g}'.format(lo,hi));hist.cell(row,2,int(n))
            chart=BarChart();chart.title=obj+' · '+scenario+' · '+fond;chart.add_data(Reference(hist,min_col=2,min_row=startrow,max_row=row),titles_from_data=True);chart.set_categories(Reference(hist,min_col=1,min_row=startrow+1,max_row=row));chart.width=22;chart.height=12;hist.add_chart(chart,'D'+str(position));position+=25;row+=3
        # Summary percentile bars replicate the multi-object comparison workflow.
        summary=tables.get('Сводная объектов',pd.DataFrame());pcols=[c for c in summary if re.fullmatch(r'P[\d.]+',str(c))]
        if not summary.empty and pcols:
            chart=BarChart();chart.title='Процентили по объектам и сценариям';sheet=wb['Сводная объектов'];columns=list(summary)
            for c in pcols:chart.add_data(Reference(sheet,min_col=columns.index(c)+1,min_row=1,max_row=len(summary)+1),titles_from_data=True)
            chart.set_categories(Reference(sheet,min_col=1,min_row=2,max_row=len(summary)+1));sheet.add_chart(chart,'B'+str(len(summary)+4))
        # Box charts embedded in the same book, without requiring xlsxwriter.
        from openpyxl.drawing.image import Image as ExcelImage
        from atlas.engine.modules import pressure_match as pm
        from atlas.engine.core.export import figure_bytes
        plots=wb.create_sheet('Ящики с усами');position=1
        jobs=[('Общая статистика',d,'overall_box'),('По фондам',d,'fond_box'),('По объектам',d,'object_box')]
        wells=sorted(d.well.unique(),key=lambda w:d.loc[d.well.eq(w),'error'].median())
        for start in range(0,len(wells),50):
            selected=wells[start:start+50];jobs.append(('Скважины '+str(start+1)+'–'+str(start+len(selected)),d[d.well.isin(selected)],'box'))
        for title,subset,name in jobs:
            plots.cell(position,1,title);picture=ExcelImage(io.BytesIO(figure_bytes(pm.figure(subset,name,cfg),'png',150,220)));ratio=picture.height/picture.width;picture.width=880;picture.height=int(880*ratio);plots.add_image(picture,'A'+str(position+1));position+=int(picture.height/20)+4
    if not wb.sheetnames:wb.create_sheet('Нет данных')
    wb.calculation.fullCalcOnLoad=True;buf=io.BytesIO();wb.save(buf);return buf.getvalue()

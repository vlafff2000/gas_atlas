"""Offline DOCX report and PDF well passport, using the existing app dependencies."""
import io
import json
import string
import textwrap
import zipfile
import datetime
from xml.sax.saxutils import escape
from PIL import Image
from .export import figure_bytes,LOCK

DEFAULT_CAPTIONS={
 'production':{'section':'1','start':1,'template':'Рисунок {раздел}.{номер} - Динамика по скважине {скважина}'},
 'gdi':{'section':'2','start':1,'template':'Рисунок {раздел}.{номер} - ГДИ по скважине {скважина}'},
 'response':{'section':'3','start':1,'template':'Рисунок {раздел}.{номер} - Реагирование по скважине {скважина}'},
 'object_pressure':{'section':'4','start':1,'template':'Рисунок {раздел}.{номер} - Пластовое давление объекта'},
 'well_dashboard':{'section':'5','start':1,'template':'Рисунок {раздел}.{номер} - Анализ скважины {скважина}'},
 'operations':{'section':'6','start':1,'template':'Рисунок {раздел}.{номер} - Эксплуатация скважины {скважина}'},
 'water':{'section':'7','start':1,'template':'Рисунок {раздел}.{номер} - Контроль воды скважины {скважина}'},
 'bottom':{'section':'8','start':1,'template':'Рисунок {раздел}.{номер} - Забой скважины {скважина}'},
 'construction':{'section':'9','start':1,'template':'Рисунок {раздел}.{номер} - Конструкция скважины {скважина}'}}


DEFAULT_CAPTIONS['pressure_match']={'section':'10','start':1,'template':'Рисунок {раздел}.{номер} - Кроссплот давлений: {скважина}'}

DEFAULT_CAPTIONS['histograms']={**DEFAULT_CAPTIONS['production'],'section':'2.2'}

def caption_for(figure,name,config,counters):
    meta=figure.layout.meta or {};module=meta.get('module','gdi')
    cfg={**DEFAULT_CAPTIONS.get(module,DEFAULT_CAPTIONS['gdi']),**config.get(module,{})}
    number=counters.setdefault(module,int(cfg.get('start',1)));counters[module]=number+1
    values={'раздел':str(cfg['section']),'номер':number,'скважина':', '.join(map(str,meta.get('wells',[]))),
        'горизонт':', '.join(map(str,meta.get('horizons',[]))),'период':', '.join(map(str,meta.get('periods',[]))),
        'модуль':{'production':'Динамика','gdi':'ГДИ','response':'Реагирование','object_pressure':'Давление объекта'}.get(module,module)}
    template=cfg['template']
    for _,field,spec,conversion in string.Formatter().parse(template):
        if field is not None and (field not in values or spec or conversion):
            raise ValueError('Неизвестное поле подписи: '+str(field)+'. Допустимы: '+', '.join('{'+v+'}' for v in values))
    return template.format_map(values)


def report_docx(figures,project,caption_config=None,progress=None,errors=None,counters=None,target=None):
    """A real two-column Word table, with editable captions below each image."""
    if not figures:raise ValueError('Для отчета Word выберите хотя бы один график.')
    def paragraph(text,bold=False,style=''):
        props='<w:pPr><w:spacing w:after="100" w:line="240" w:lineRule="auto"/>'+('<w:pStyle w:val="'+style+'"/>' if style else '')+'</w:pPr>'
        return '<w:p>'+props+'<w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="'+('32' if style=='Title' else '20')+'"/>'+('<w:b/>' if bold else '')+'</w:rPr><w:t xml:space="preserve">'+escape(str(text))+'</w:t></w:r></w:p>'
    namespaces='xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
    rows=[];cells=[];rels=[];counters={} if counters is None else counters
    buf=io.BytesIO() if target is None else None
    z=zipfile.ZipFile(buf if target is None else target,'w',zipfile.ZIP_DEFLATED)
    try:
        for i,(name,fig) in enumerate(figures.items(),1):
            try:
                content=figure_bytes(fig,'png',300,90)
                with Image.open(io.BytesIO(content)) as image:w,h=image.size
                label=caption_for(fig,name,caption_config or {},counters)
            except Exception as error:
                if errors is None:raise
                errors.append({'График':name,'Формат':'docx','Ошибка':str(error)});continue
            z.writestr('word/media/chart'+str(i)+'.png',content)
            cx=int(84*36000);cy=int(cx*h/w)
            if cy>180*36000:cx=int(cx*(180*36000)/cy);cy=180*36000
            drawing=f'''<w:p><w:pPr><w:jc w:val="center"/><w:keepNext/></w:pPr><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{i}" name="Chart {i}" descr="{escape(label, {'&quot;':'&quot;', chr(34):'&quot;'})}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="chart{i}.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rId{i}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'''
            cells.append('<w:tc><w:tcPr><w:tcW w:w="5100" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>'+drawing+paragraph(label)+'</w:tc>')
            rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/chart{i}.png"/>')
            if len(cells)==2:rows.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>'+''.join(cells)+'</w:tr>');cells=[]
            if progress:progress(i/len(figures))
        if cells:rows.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>'+cells[0]+'<w:tc><w:tcPr><w:tcW w:w="5100" w:type="dxa"/></w:tcPr><w:p/></w:tc></w:tr>')
        borders=''.join('<w:'+side+' w:val="single" w:sz="4" w:color="D9D9D9"/>' for side in ('top','left','bottom','right','insideH','insideV'))
        table='<w:tbl><w:tblPr><w:tblW w:w="10200" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblBorders>'+borders+'</w:tblBorders><w:tblCellMar><w:top w:w="120" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid><w:gridCol w:w="5100"/><w:gridCol w:w="5100"/></w:tblGrid>'+''.join(rows)+'</w:tbl>'
        document='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document '+namespaces+'><w:body>'+paragraph('Газовый атлас',True,'Title')+paragraph(project)+table+'<w:p/><w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="850" w:right="850" w:bottom="850" w:left="850" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr></w:body></w:document>'
        if errors:
            document=document.replace('<w:p/><w:sectPr>',paragraph('Ошибки формирования: '+str(len(errors)))+''.join(paragraph(str(e)) for e in errors)+'<w:p/><w:sectPr>')
        try:
            z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
            z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
            z.writestr('word/document.xml',document)
            z.writestr('word/styles.xml','<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:color w:val="000000"/><w:sz w:val="32"/></w:rPr></w:style></w:styles>')
            z.writestr('word/_rels/document.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(rels)+'<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        finally:z.close()
    finally:z.close()
    return buf.getvalue() if buf is not None else target


def passport_pdf(project,well,figures,tables,settings,comment='',progress=None):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.image import imread
    lines=[project,'Скважина №'+str(well),'Паспорт скважины','',
       'Сезон отбора: месяцы {}-{}'.format(settings.get('season_start',11),settings.get('season_end',4)),
       'Порог качества ГДИ R²: '+str(settings.get('r2_threshold',.95)),
       'Давление: кгс/см²; расход: тыс. м³/сут; уровень: м.',
       'Исключенных показателей в проекте: '+str(len(settings.get('excluded_points',{}))),'']
    for name,table in tables.items():
        if name=='Исключенные_точки' or table.empty:continue
        cols=[c for c in ('date','period','a_calc','b_calc','r2_calc','q_observed','q_free','value','active','volume','Горизонт','Скважин','Замеров','Начало','Окончание','Минимум_м','Максимум_м') if c in table]
        if not cols:continue
        heading=name.replace('withdrawal','Отбор').replace('injection','Закачка').replace('_',' ')
        lines.append(heading+' (последние записи, до 12 строк)')
        for _,row in table.tail(12).iterrows():
            values=[]
            for col in cols:
                value=row[col]
                if isinstance(value,datetime.date):value=value.strftime('%d.%m.%Y')
                elif isinstance(value,float):value=f'{value:.5g}'
                label={'date':'Дата','period':'Период','a_calc':'a','b_calc':'b','r2_calc':'R²','q_observed':'Qmax','q_free':'Qсв','value':'Средний расход','active':'Активных дней','volume':'Объем, млн м³'}.get(col,col)
                values.append(label+' = '+str(value))
            if values:lines.extend(textwrap.wrap('; '.join(values),90))
        lines.append('')
    lines+=['Комментарий инженера']
    for part in (comment or 'Комментарий не задан.').splitlines():lines.extend(textwrap.wrap(part,90) or [''])
    buf=io.BytesIO()
    with LOCK,plt.rc_context({'font.family':'DejaVu Sans','pdf.fonttype':42}):
        with PdfPages(buf,metadata={'Title':'Паспорт скважины №'+str(well),'Author':'Газовый атлас'}) as pdf:
            for offset in range(0,len(lines),46):
                fig=plt.figure(figsize=(8.27,11.69))
                try:
                    fig.text(.075,.955,'Паспорт скважины №'+str(well),fontsize=18,weight='bold',va='top')
                    fig.text(.075,.91,'\n'.join(lines[offset:offset+46]),fontsize=10,va='top',linespacing=1.55)
                    pdf.savefig(fig)
                finally:plt.close(fig)
            for i,(name,chart) in enumerate(figures.items(),1):
                png=figure_bytes(chart,'png',150,190);fig=plt.figure(figsize=(8.27,11.69))
                try:
                    fig.text(.075,.955,name,fontsize=12,va='top')
                    ax=fig.add_axes([.04,.06,.92,.82]);ax.imshow(imread(io.BytesIO(png),format='png'));ax.axis('off')
                    pdf.savefig(fig)
                finally:plt.close(fig)
                if progress:progress(i/max(1,len(figures)))
    return buf.getvalue()

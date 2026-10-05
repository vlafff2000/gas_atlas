"""Content-aware, dependency-free ODS and text readers; XLSX remains streamed."""
import csv
import io
import re
import shlex
import zipfile
from pathlib import Path
from itertools import islice
from xml.etree import ElementTree as ET
import openpyxl
import pandas as pd

T='{urn:oasis:names:tc:opendocument:xmlns:table:1.0}'
O='{urn:oasis:names:tc:opendocument:xmlns:office:1.0}'
X='{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'

def format_of(path):
    with open(path,'rb') as f:magic=f.read(8)
    if magic.startswith(b'PK'):
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist())>3*1024**3:raise ValueError('Распакованная книга превышает 3 ГБ.')
            if 'content.xml' in z.namelist() and 'mimetype' in z.namelist() and b'opendocument.spreadsheet' in z.read('mimetype'):return 'ods'
            if 'xl/workbook.xml' in z.namelist():return 'xlsx'
        raise ValueError('ZIP не является таблицей XLSX или ODS.')
    if magic.startswith(b'\xd0\xcf\x11\xe0'):return 'xls'
    return 'text'

def decode_text(content,encoding='auto'):
    if encoding!='auto':return content.decode(encoding)
    candidates=['utf-16'] if content.startswith((b'\xff\xfe',b'\xfe\xff')) else ['utf-8-sig','cp1251']
    for enc in candidates:
        try:return content.decode(enc)
        except UnicodeError:pass
    raise ValueError('Не удалось прочитать текст. Выберите кодировку вручную.')

_SPACED_DATE=re.compile(r'\b(\d{1,2}) ([A-Za-z]{3,9})\.? (\d{2,4})\b')

def _whitespace_cells(line):
    # дата «01 Jan 2020» сама содержит пробелы: склеиваем её в одну ячейку, остальное делим как раньше
    found=[]
    def keep(m):
        found.append(m.group(0));return '\x00%d\x00'%(len(found)-1)
    cells=shlex.split(_SPACED_DATE.sub(keep,line),comments=False)
    return [re.sub('\x00(\\d+)\x00',lambda m:found[int(m.group(1))],c) for c in cells]

def resolve_delimiter(text,delimiter='auto'):
    if delimiter!='auto':return delimiter
    sample='\n'.join(text.splitlines()[:40])
    if '\t' in sample:return '\t'
    if ';' in sample:return ';'
    first=next((line for line in text.splitlines() if line.strip()),'')
    if '|' in first:return '|'
    if ',' not in first:return 'whitespace'
    try:return csv.Sniffer().sniff(sample,delimiters=',|').delimiter
    except csv.Error:return ','

def text_rows(text,delimiter='auto'):
    delimiter=resolve_delimiter(text,delimiter)
    if delimiter=='whitespace':
        for line in text.splitlines():
            yield _whitespace_cells(line) if line.strip() else []
    else:yield from csv.reader(io.StringIO(text),delimiter=delimiter)

def _cell(cell):
    kind=cell.get(O+'value-type')
    if kind=='date':return cell.get(O+'date-value')
    if kind in ('float','currency','percentage'):
        try:return float(cell.get(O+'value'))
        except (ValueError,TypeError):pass
    if kind=='boolean':return cell.get(O+'boolean-value')=='true'
    paragraphs=[''.join(p.itertext()) for p in cell.iter(X+'p')]
    return '\n'.join(paragraphs) if paragraphs else cell.get(O+'string-value')

def ods_rows(path,target):
    """Keep interior repeats, never expand LibreOffice's trailing blank grid."""
    with zipfile.ZipFile(path) as z, z.open('content.xml') as stream:
        active=False;logical_rows=0;pending_rows=0
        for event,elem in ET.iterparse(stream,events=('start','end')):
            if event=='start' and elem.tag==T+'table':active=elem.get(T+'name')==target
            if event!='end':continue
            if elem.tag==T+'table-row':
                if active:
                    cells=[];pending=0
                    for cell in elem:
                        if cell.tag not in (T+'table-cell',T+'covered-table-cell'):continue
                        count=int(cell.get(T+'number-columns-repeated','1'));value=_cell(cell)
                        if value is None or value=='':pending+=count;continue
                        if len(cells)+pending+count>16384:raise ValueError('В ODS более 16384 заполненных колонок.')
                        cells.extend([None]*pending);pending=0;cells.extend([value]*count)
                    repeat=int(elem.get(T+'number-rows-repeated','1'))
                    if logical_rows+repeat>2000000:raise ValueError('В ODS более 2 млн строк; разделите книгу.')
                    logical_rows+=repeat
                    if not cells:
                        pending_rows+=repeat
                    else:
                        for _ in range(pending_rows):yield []
                        pending_rows=0
                        for _ in range(repeat):yield list(cells)
                elem.clear()
            elif elem.tag==T+'table':
                if active:return
                elem.clear()

def trim_rows(rows):
    for row in rows:
        row=list(row)
        while row and (row[-1] is None or row[-1]==''):row.pop()
        yield row

def _calamine_book(path):
    try:
        from python_calamine import CalamineWorkbook
        return CalamineWorkbook.from_path(str(path))
    except Exception:return None

def iter_tables(path,encoding='auto',delimiter='auto'):
    if Path(path).stat().st_size>512*1024**2:raise ValueError('Размер файла превышает 512 МБ.')
    fmt=format_of(path)
    if fmt=='ods':
        # Discover names without retaining the XML tree.
        names=[]
        with zipfile.ZipFile(path) as z, z.open('content.xml') as stream:
            for event,elem in ET.iterparse(stream,events=('start','end')):
                if event=='start' and elem.tag==T+'table':names.append(elem.get(T+'name','Лист'))
                if event=='end' and elem.tag==T+'table-row':elem.clear()
        for name in names:yield name,ods_rows(path,name)
    elif fmt=='xlsx':
        fast=_calamine_book(path)
        if fast is not None:
            # Rust reader: about 10x faster than openpyxl on large workbooks.
            for name in fast.sheet_names:yield name,trim_rows(fast.get_sheet_by_name(name).to_python(skip_empty_area=False))
            return
        book=openpyxl.load_workbook(path,read_only=True,data_only=True)
        try:
            for sheet in book:yield sheet.title,trim_rows(sheet.iter_rows(values_only=True))
        finally:book.close()
    elif fmt=='xls':
        import xlrd
        book=xlrd.open_workbook(path,on_demand=True)
        try:
            for sheet in book.sheets():
                def rows(ws=sheet):
                    for i in range(ws.nrows):yield [xlrd.xldate_as_datetime(c.value,book.datemode) if c.ctype==xlrd.XL_CELL_DATE else c.value for c in ws.row(i)]
                yield sheet.name,rows()
        finally:book.release_resources()
    else:yield Path(path).stem,text_rows(decode_text(Path(path).read_bytes(),encoding),delimiter)

def read_content(content,name,limit=None,encoding='auto',delimiter='auto'):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/Path(name).name;path.write_bytes(content);fmt=format_of(path);tables={}
        for sheet,rows in iter_tables(path,encoding,delimiter):
            values=list(islice(rows,limit)) if limit else list(rows)
            # Pad only to the actual used width, preserve raw duplicate headings.
            width=max((len(r) for r in values),default=0)
            if width>16384:raise ValueError('Слишком много колонок.')
            tables[sheet]=pd.DataFrame([list(r)+[None]*(width-len(r)) for r in values])
        return fmt,tables

def headed(raw,header=0,names=None):
    if header>=len(raw):raise ValueError('Строка заголовков за пределами файла.')
    labels=list(raw.iloc[header]) if header>=0 else list(range(raw.shape[1]))
    if names:labels=[names.get(str(i),v) for i,v in enumerate(labels)]
    data=raw.iloc[header+1:].copy();data.columns=labels;return data.reset_index(drop=True)

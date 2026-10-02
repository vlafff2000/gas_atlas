"""Remembered column layouts. A sheet whose header row matches a saved one gets the same mapping automatically."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from app.core import config

def _file():
    return Path(config.STORAGE)/'import_profiles.json'

def load():
    try:return json.loads(_file().read_text('utf-8'))
    except (OSError,ValueError):return {}

def _store(data):
    path=_file();path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=str(path.parent),suffix='.tmp')
    with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=1)
    os.replace(tmp,str(path))

def signatures(raw,limit=31):
    """(row index, signature) of every row of the preview that looks like a header (two or more non-empty cells)."""
    for i in range(min(limit,len(raw))):
        labels=[str(v).strip() for v in raw.iloc[i] if v is not None and str(v).strip() and str(v)!='nan']
        if len(labels)>=2:yield i,hashlib.sha256(('|'.join(labels)+'#'+str(raw.shape[1])).encode('utf-8')).hexdigest()[:20]

def find(raw,kind):
    saved=load()
    for i,signature in signatures(raw):
        item=saved.get(kind+':'+signature)
        if item and item['spec'].get('header')==i:return dict(item['spec'])
    return None

def save(raw,spec,kind):
    """Remember the layout under the signature of the chosen header row."""
    header=spec.get('header',-1)
    for i,signature in signatures(raw):
        if i==header:
            data=load();data[kind+':'+signature]={'spec':json.loads(json.dumps(spec,default=str))};_store(data);return True
    return False

def forget(raw,spec,kind):
    data=load();changed=False
    for i,signature in signatures(raw):
        if i==spec.get('header',-1) and data.pop(kind+':'+signature,None) is not None:changed=True
    if changed:_store(data)

def count():
    return len(load())

def clear():
    _store({})

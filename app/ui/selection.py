from app.core.config import ordered


def choose_group_wells(state,group_key,well_key,wells,mapping):
    groups=state.get(group_key,[])
    state[well_key]=ordered(w for w in wells if mapping.get(w,{}).get('group','Без группы') in groups)


def histogram_size(value,count):
    if value=='Все':return max(1,count)
    if value=='Авто':return 10
    return max(1,int(value))


def parse_wells(text):
    import re
    return ordered(w.lstrip('№#') for w in re.split(r'[,;\s]+',text.strip()) if w.lstrip('№#'))


def checklist(label,options,default=None,key=None,format_func=str,on_change=None,args=()):
    """Local batched checklist: no server round trip per checkbox or drag."""
    import streamlit as st
    import streamlit.components.v1 as components
    from pathlib import Path
    from app.core.performance import signature
    options=list(dict.fromkeys(str(v) for v in options))
    selected=[v for v in st.session_state.get(key,default or []) if v in options]
    st.session_state[key]=selected
    component=components.declare_component('atlas_checklist',path=str(Path(__file__).parent/'checklist'))
    token=signature([options,selected])
    result=component(label=label,options=options,selected=selected,labels={v:str(format_func(v)) for v in options},token=token,key=key+'__checklist',default=None)
    if isinstance(result,dict) and result.get('token')==token:
        values=[v for v in options if v in result.get('values',[])]
        if values!=selected:
            st.session_state[key]=values;selected=values
            if on_change:on_change(*args)
            st.rerun()
    return selected


def paginate(items,label,key,size=6,format_func=str):
    """Bound chart count with previous/next, direct jump and user-selected page size."""
    import streamlit as st
    items=list(items)
    if not items:return []
    sizes=[1,2,4,6,10,20]
    if size not in sizes:sizes.append(size);sizes.sort()
    cols=st.columns([1,1,3,1,1])
    page_size=cols[0].selectbox('Графиков на странице',sizes,index=sizes.index(size),key=key+'_size')
    total=max(1,(len(items)+page_size-1)//page_size)
    old=st.session_state.get(key,1);page=min(max(1,old),total);st.session_state[key]=page
    def change(delta):
        st.session_state[key]=min(total,max(1,st.session_state.get(key,1)+delta))
        st.session_state[key+'_jump']=st.session_state[key]
    cols[1].button('← Назад',key=key+'_prev',disabled=page==1,on_click=change,args=(-1,))
    jump=key+'_jump'
    if st.session_state.get(jump) not in range(1,total+1) or st.session_state.get(key+'_count')!=(len(items),page_size):st.session_state[jump]=page
    st.session_state[key+'_count']=(len(items),page_size)
    def jump_to():st.session_state[key]=st.session_state[jump]
    def name(p):
        first=format_func(items[(p-1)*page_size]);last=format_func(items[min(p*page_size,len(items))-1])
        def short(v):return str(v)[:48]
        return str(p)+' / '+str(total)+' · '+short(first)+((' … '+short(last)) if page_size>1 else '')
    cols[2].selectbox(label,list(range(1,total+1)),format_func=name,key=jump,on_change=jump_to)
    page=st.session_state[key]
    cols[3].button('Вперед →',key=key+'_next',disabled=page==total,on_click=change,args=(1,))
    cols[4].button('В начало',key=key+'_first',disabled=page==1,on_click=change,args=(1-page,))
    st.caption('Показаны '+str((page-1)*page_size+1)+'–'+str(min(page*page_size,len(items)))+' из '+str(len(items))+'. Экспорт включает весь выбранный список.')
    return items[(page-1)*page_size:page*page_size]

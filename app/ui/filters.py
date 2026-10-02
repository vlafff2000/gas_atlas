"""Shared filter bar: a bordered block above the charts that can be pinned while scrolling."""
from contextlib import contextmanager
import streamlit as st

PIN_CSS='''<style>
[data-testid="stVerticalBlockBorderWrapper"]:has(.atlas-pin-marker):not(:has([data-testid="stVerticalBlockBorderWrapper"] .atlas-pin-marker)) {
    position:sticky;top:2.8rem;z-index:50;background-color:#f3f6f7;box-shadow:0 6px 14px rgba(0,0,0,.12)}
@media (prefers-color-scheme: dark){[data-testid="stVerticalBlockBorderWrapper"]:has(.atlas-pin-marker):not(:has([data-testid="stVerticalBlockBorderWrapper"] .atlas-pin-marker)){background-color:#0e1117}}
</style>'''

def pin_toggle():
    """Sidebar switch shared by every page that uses filter_bar."""
    return st.toggle('Закреплять панель фильтров',value=False,key='pin_filters',
        help='Панель фильтров остается вверху экрана при прокрутке графиков. Занимает место на небольших экранах.')

@contextmanager
def filter_bar(pin=True):
    """pin=False for bars that contain tall lists (they would cover the charts when pinned)."""
    with st.container(border=True):
        if pin and st.session_state.get('pin_filters'):
            st.markdown('<span class="atlas-pin-marker"></span>'+PIN_CSS,unsafe_allow_html=True)
        yield

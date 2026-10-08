"""Кэш результатов в памяти процесса: замена ``st.cache_resource`` из 5.8 (Streamlit больше не нужен).

Как и в Streamlit, ключ строится по аргументам, кроме тех, чьё имя начинается с «_» (большие таблицы
в ключ не входят — вместо них передаётся токен). Самые старые записи вытесняются по ``max_entries``.
"""
from __future__ import annotations

import inspect
import threading
from collections import OrderedDict
from functools import wraps


def cache_resource(max_entries=None):
    def decorate(function):
        signature = inspect.signature(function)
        names = [n for n in signature.parameters if not n.startswith('_')]
        entries = OrderedDict()
        lock = threading.RLock()

        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            key = repr(tuple((n, bound.arguments[n]) for n in names if n in bound.arguments))
            with lock:
                if key in entries:
                    entries.move_to_end(key)
                    return entries[key]
            value = function(*args, **kwargs)
            with lock:
                entries[key] = value
                while max_entries and len(entries) > max_entries:
                    entries.popitem(last=False)
            return value

        wrapped.clear = entries.clear
        return wrapped
    return decorate

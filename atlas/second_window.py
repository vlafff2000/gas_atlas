"""Второе окно программы (для второго монитора): окно открывает тот, кто запустил сервер (pywebview или браузер)."""
from __future__ import annotations

from typing import Callable, Optional

from starlette.responses import JSONResponse
from starlette.routing import Route

_opener: dict[str, Optional[Callable[[str], None]]] = {'open': None}


def set_opener(fn: Optional[Callable[[str], None]]) -> None:
    _opener['open'] = fn


def open_second(hash_part: str = '') -> bool:
    """False, если открыть окно нечем (сервер без окна): тогда интерфейс открывает окно браузера сам."""
    fn = _opener['open']
    if fn is None:
        return False
    try:
        fn('#' + hash_part.lstrip('#') if hash_part else '')
    except Exception:
        return False
    return True


async def _handler(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    part = str(body.get('hash', ''))[:100] if isinstance(body, dict) else ''
    return JSONResponse({'opened': open_second(part)})


def route() -> Route:
    return Route('/api/second-window', _handler, methods=['POST'])

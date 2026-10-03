"""Обнаружение модулей: любой файл в ``atlas/modules/`` с подклассом ``Module``.

Новый скрипт подключается файлом в ``atlas/modules/`` — без правок интерфейса и API.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from functools import lru_cache

from .contract import Module

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def modules() -> dict[str, Module]:
    from . import modules as package
    found: dict[str, Module] = {}
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith('_'):
            continue
        try:
            mod = importlib.import_module(f'{package.__name__}.{info.name}')
        except Exception:  # один сломанный модуль не должен ронять приложение
            log.exception('Модуль %s не загружен', info.name)
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if issubclass(cls, Module) and cls is not Module and cls.__module__ == mod.__name__ and hasattr(cls, 'spec'):
                spec = cls.spec
                if spec.id in found:
                    raise RuntimeError(f'Повтор идентификатора модуля: {spec.id}')
                found[spec.id] = cls()
    return dict(sorted(found.items(), key=lambda kv: (kv[1].spec.order, kv[1].spec.title)))


def get(module_id: str) -> Module:
    try:
        return modules()[module_id]
    except KeyError:
        raise KeyError(f'Нет модуля {module_id!r}') from None

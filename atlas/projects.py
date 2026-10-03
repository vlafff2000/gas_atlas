"""Доступ к проектам. Пока — адаптер к хранилищу 5.8 (``app/core/storage.py``):
те же папки, тот же формат, обе версии видят одни проекты, настройки и исключения.

Таблицы снимка читает и индексирует ``app.core.performance.Project`` из 5.8 (тот же код, те же кэши):
диск читается один раз на снимок; вид с исключёнными точками и сезонами пересобирается при новой ревизии.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import threading
import uuid
from collections import OrderedDict
from typing import Any, Iterable, Mapping

import pandas as pd

from app.core import exclusions
from app.core.config import DEFAULT_SETTINGS, STORAGE, natural_key, ordered
from app.core.history import filter_details
from app.core.performance import Project as FrameCache
from app.core.storage import Store

from .contract import Data, MissingData, ParamError
from .domain import DatasetKind

_CACHE_PROJECTS = 3
KNOWN = {k.value: k for k in DatasetKind}

# Настройки, которые интерфейс 6 может менять напрямую, с проверкой значения.
EDITABLE_SETTINGS = {
    'r2_threshold': lambda v: 0 <= float(v) <= 1,
    'working_horizons': lambda v: isinstance(v, list) and all(isinstance(h, str) for h in v),
}


class Conflict(RuntimeError):
    """Проект изменён параллельно (например, в 5.8). Текст — для пользователя."""


class Projects:
    def __init__(self, root=STORAGE):
        self.store = Store(root)
        self._lock = threading.RLock()
        self._frames: OrderedDict[tuple, FrameCache] = OrderedDict()
        self._views: OrderedDict[tuple, Data] = OrderedDict()

    # --- список и создание ---
    def list(self) -> list[dict[str, Any]]:
        return [self.summary(m) for m in self.store.list()]

    @staticmethod
    def summary(m: Mapping[str, Any]) -> dict[str, Any]:
        settings = m.get('settings', {})
        return {'id': m['id'], 'name': m['name'], 'demo': bool(m.get('demo')), 'updated': m['updated'],
                'revision': m.get('revision', 0), 'tables': dict(m.get('tables', {})),
                'settings': {k: settings.get(k) for k in EDITABLE_SETTINGS},
                'excluded': len(settings.get('excluded_points', {}))}

    def create_demo(self) -> str:
        from app.core.demo import demo_frames
        pid = self.store.create('Демонстрационный объект', demo=True)
        self.store.commit(pid, frames=demo_frames(), action='Демонстрационные данные')
        return pid

    def manifest(self, pid: str) -> dict[str, Any]:
        try:
            return self.store.manifest(pid)
        except (ValueError, FileNotFoundError):
            raise KeyError(f'Нет проекта {pid}') from None

    # --- данные ---
    def _cache(self, pid: str, m: Mapping[str, Any]) -> FrameCache:
        key = (pid, m.get('snapshot'))
        with self._lock:
            if key not in self._frames:
                for stale in [k for k in self._frames if k[0] == pid]:
                    self._frames.pop(stale).release()
                self._frames[key] = FrameCache(self.store.root, pid, m.get('snapshot'), tuple(m.get('tables', {})))
                while len(self._frames) > _CACHE_PROJECTS:
                    self._frames.popitem(last=False)[1].release()
            self._frames.move_to_end(key)
            return self._frames[key]

    def _raw_frames(self, pid: str, m: Mapping[str, Any]) -> dict[str, pd.DataFrame]:
        """Исходные таблицы с идентификаторами точек (``_point_id``)."""
        cache = self._cache(pid, m)
        return {n: cache.raw(n) for n in m.get('tables', {}) if n in KNOWN and m['tables'][n]}

    def data(self, pid: str) -> Data:
        m = self.manifest(pid)
        key = (pid, m.get('snapshot'), m.get('revision'))
        with self._lock:
            if key in self._views:
                self._views.move_to_end(key)
                return self._views[key]
        cache = self._cache(pid, m)
        settings = {**DEFAULT_SETTINGS, **m.get('settings', {})}
        raw = self._raw_frames(pid, m)
        # Эксплуатация готовится как в 5.8: сезоны и индексы; остальное — только исключения.
        prepared = exclusions.apply({n: d for n, d in raw.items() if n != 'production'}, settings)
        shown, original = dict(prepared), {n: d for n, d in raw.items() if n != 'production'}
        if 'production' in raw:
            shown['production'] = cache.prepared('production', settings)
            original['production'] = cache.prepared('production', {**settings, 'excluded_points': {}})
        data = Data({KNOWN[n]: d for n, d in shown.items()}, {KNOWN[n]: d for n, d in original.items()},
                    settings.get('excluded_points', {}))
        data.settings, data.revision = settings, m.get('revision')
        mapping = {w: dict(v) for w, v in cache.catalog()['mapping'].items()}
        for well, value in m.get('groups', {}).items():
            mapping.setdefault(well, {}).update(value)
        data.mapping = mapping
        data.wells = ordered(cache.catalog()['wells'])
        with self._lock:
            for stale in [k for k in self._views if k[0] == pid]:
                self._views.pop(stale)
            self._views[key] = data
            while len(self._views) > _CACHE_PROJECTS:
                self._views.popitem(last=False)
        return data

    def select(self, pid: str, needs, optional=()) -> Data:
        data = self.data(pid)
        missing = [k for k in needs if k not in data or data[k].empty]
        if missing:
            raise MissingData(missing)
        keep = (*needs, *optional)
        out = Data({k: data[k] for k in keep if k in data}, {k: data.raw[k] for k in keep if k in data.raw}, data.excluded)
        out.settings, out.revision, out.mapping, out.wells = data.settings, data.revision, data.mapping, data.wells
        return out

    def options(self, pid: str, dataset: DatasetKind, column: str) -> list[str]:
        frame = self.data(pid).raw.get(dataset)
        if frame is None or column not in frame:
            return []
        values = frame[column].dropna().astype(str)
        return sorted((v for v in values.unique() if v != ''), key=natural_key)

    # --- изменения ---
    def _commit(self, pid: str, settings: dict, expected: int | None, action: str, details=None):
        try:
            return self.store.commit(pid, settings=settings, expected=expected, action=action, details=details)
        except ValueError as e:
            if 'изменен' in str(e):
                raise Conflict('Проект изменён в другом окне (например, в версии 5.8). Обновите данные и повторите.') from None
            raise

    def update_settings(self, pid: str, values: Mapping[str, Any], expected: int | None = None) -> dict[str, Any]:
        m = self.manifest(pid)
        cfg = copy.deepcopy(m.get('settings', {}))
        for name, value in values.items():
            check = EDITABLE_SETTINGS.get(name)
            try:
                ok = check is not None and check(value)
            except (TypeError, ValueError):
                ok = False
            if not ok:
                raise ParamError(f'Недопустимое значение настройки {name}')
            cfg[name] = float(value) if name == 'r2_threshold' else value
        action = 'Выбор рабочих горизонтов' if set(values) == {'working_horizons'} else 'Изменение правил'   # как в 5.8
        return self.summary(self._commit(pid, cfg, expected, action, {'changed': dict(values)}))

    def change_exclusions(self, pid: str, dataset: DatasetKind, add: Iterable[str] = (), remove: Iterable[str] = (),
                          reason: str = 'Исключено вручную', metric: str | None = None,
                          expected: int | None = None) -> dict[str, Any]:
        """Как ``PointControls.change`` в 5.8: одна операция — одна запись журнала с состоянием до и после."""
        m = self.manifest(pid)
        raw = self._raw_frames(pid, m)
        before = m.get('settings', {})
        cfg = copy.deepcopy(before)
        items = cfg.setdefault('excluded_points', {})
        reason = (reason or '').strip()[:300] or 'Исключено вручную'
        added = []
        for identifier in dict.fromkeys(str(i) for i in add):
            if identifier in items:
                continue
            # Реагирование: показатель (уровень / давление) — в самом идентификаторе точки, как в 5.8.
            field = metric or (identifier.rsplit(':', 1)[-1] if dataset is DatasetKind.RESPONSE else None)
            entry = exclusions.entry(raw, dataset.value, identifier, field, reason)
            if entry is None:
                raise ParamError('Точка не найдена в данных проекта. Обновите страницу.')
            added.append(entry)
        removed = [str(i) for i in dict.fromkeys(remove) if str(i) in items]
        if not added and not removed:
            return {'added': 0, 'removed': 0, 'excluded': len(items), 'revision': m.get('revision')}
        operation, stamp = uuid.uuid4().hex, dt.datetime.now(dt.timezone.utc).isoformat()
        for entry in added:
            items[entry['id']] = {**entry, 'batch': operation, 'excluded_utc': stamp}
        for identifier in removed:
            items.pop(identifier, None)
        details = filter_details(raw, before, cfg, added, removed)
        saved = self._commit(pid, cfg, expected, 'Ручной фильтр точек', details)
        return {'added': len(added), 'removed': len(removed), 'excluded': len(items), 'revision': saved['revision']}

    def undo_exclusion(self, pid: str) -> dict[str, Any]:
        """«Отменить последнее исключение»: снимает всю последнюю операцию (пакет)."""
        items = self.manifest(pid).get('settings', {}).get('excluded_points', {})
        if not items:
            return {'added': 0, 'removed': 0, 'excluded': 0}
        latest = max(items.values(), key=lambda e: e.get('excluded_utc', ''))
        batch = latest.get('batch')
        ids = [k for k, v in items.items() if batch and v.get('batch') == batch] or [latest['id']]
        dataset = KNOWN[latest.get('module', 'gdi')]
        return self.change_exclusions(pid, dataset, remove=ids)

    def assign_groups(self, pid: str, changes: Mapping[str, Mapping[str, Any]], action: str = 'Назначение групп',
                      expected: int | None = None) -> dict[str, Any]:
        """Группы и подгруппы скважин (``manifest.groups``), как страница «Группы» 5.8.

        ``changes``: скважина -> {'group'?, 'subgroup'?}. Пустая группа — «Без группы», как в 5.8.
        Остальные назначения проекта не меняются."""
        if action not in ('Назначение групп', 'Автоматические подгруппы'):
            raise ParamError('Неизвестное действие с группами')
        if not isinstance(changes, Mapping) or not changes:
            raise ParamError('Нет изменений для сохранения')
        data = self.data(pid)
        known = set(data.wells)
        unknown = [str(w) for w in changes if str(w) not in known]
        if unknown:
            raise ParamError('Нет таких скважин в проекте: ' + ', '.join(unknown[:5]) + '. Обновите страницу.')
        groups = copy.deepcopy(self.manifest(pid).get('groups', {}))
        for well, value in changes.items():
            if not isinstance(value, Mapping) or not set(value) <= {'group', 'subgroup'}:
                raise ParamError('Назначение скважины: ожидаются поля group и subgroup')
            well = str(well)
            current = {'group': data.mapping.get(well, {}).get('group', 'Без группы'),
                       'subgroup': data.mapping.get(well, {}).get('subgroup', ''), **groups.get(well, {})}
            if 'group' in value:
                current['group'] = str(value['group'] or '').strip()[:200] or 'Без группы'
            if 'subgroup' in value:
                current['subgroup'] = str(value['subgroup'] or '').strip()[:200]
            groups[well] = current
        try:
            m = self.store.commit(pid, groups=groups, expected=expected, action=action,
                                  details={'wells': len(changes)})
        except ValueError as e:
            if 'изменен' in str(e):
                raise Conflict('Проект изменён в другом окне (например, в версии 5.8). Обновите данные и повторите.') from None
            raise
        return self.summary(m)

    # --- сохранённые параметры и расчёты ---
    def saved_state(self, pid: str, module, panel_index: int = 0) -> dict[str, Any]:
        m = self.manifest(pid)
        panels = m.get('settings', {}).get('panels', {})
        panel = panels.get(module.panel_key(panel_index))
        for old in module.panel_fallbacks(panel_index):
            if panel is None:
                panel = panels.get(old)
        history = []
        if module.history_action:
            rows = self.store.history(pid)
            for _, row in rows[rows['Действие'].eq(module.history_action)].iterrows():
                try:
                    details = json.loads(row['Подробности'])
                except ValueError:
                    continue
                history.append({'date': row['Дата'], 'params': module.load_state(details)})
        return {'panel': module.load_state(panel) if panel else None, 'history': history}

    def save_state(self, pid: str, module, params: dict[str, Any], data: Data, panel_index: int = 0) -> dict[str, Any]:
        m = self.manifest(pid)
        state = module.save_state(params, data)
        cfg = copy.deepcopy(m.get('settings', {}))
        cfg.setdefault('panels', {})[module.panel_key(panel_index)] = state
        if module.history_action:
            self.store.event(pid, module.history_action, state)
        return self.summary(self._commit(pid, cfg, None, 'Сохранение фильтров', {'module': module.spec.id}))

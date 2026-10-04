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
from app.ui import navigation
from app.modules import seasons
from app.ui.selection import parse_wells

from .contract import Data, MissingData, ParamError
from .domain import DatasetKind

_CACHE_PROJECTS = 3
WARM_ROWS = 100_000     # меньшие проекты и так открываются мгновенно
KNOWN = {k.value: k for k in DatasetKind}

# Настройки, которые интерфейс 6 может менять напрямую, с проверкой значения (как поля «Настроек» 5.8).
_month = lambda v: not isinstance(v, bool) and float(v) == int(v) and 1 <= int(v) <= 12   # noqa: E731
_names = lambda v: isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, (str, int)) for x in v))  # noqa: E731
EDITABLE_SETTINGS = {
    'r2_threshold': lambda v: 0 <= float(v) <= 1,
    'season_start': _month,
    'season_end': _month,
    'auto_seasons': lambda v: isinstance(v, bool),
    'season_gap_days': lambda v: not isinstance(v, bool) and float(v) == int(v) and 1 <= int(v) <= 365,
    'season_rate_share': lambda v: not isinstance(v, bool) and 0 < float(v) <= 50,
    'season_schedule': lambda v: v in (None, '') or (isinstance(v, str) and bool(sum(seasons.parse_schedule(v), []))),
    'peak_windows': lambda v: v is None or (isinstance(v, list) and all(isinstance(x, list) and len(x) == 2 for x in v)),
    'auto_peaks': lambda v: isinstance(v, bool),
    'peak_factor': lambda v: not isinstance(v, bool) and 1 < float(v) <= 20,
    'manometer_wells': _names,
    # Состав меню: имена страниц 5.8 (``app/ui/navigation.PAGES``); None — меню по умолчанию.
    'visible_pages': lambda v: v is None or (isinstance(v, list) and all(navigation.ALIASES.get(x, x) in navigation.PAGES for x in v)),
    'working_horizons': lambda v: isinstance(v, list) and all(isinstance(h, str) for h in v),
    'chart_style': lambda v: isinstance(v, dict) and all(k in ('points', 'legend', 'grid', 'autoscale') and isinstance(x, bool)
                                                         for k, x in v.items()),
}
SETTING_LABELS = {'r2_threshold': 'Порог R²', 'season_start': 'Первый месяц сезона отбора (1–12)',
                  'season_end': 'Последний месяц сезона отбора (1–12)', 'manometer_wells': 'Скважины с глубинными манометрами',
                  'auto_seasons': 'Определять сезоны по накопленному расходу', 'season_gap_days': 'Минимальная пауза (нейтральный период), сут',
                  'season_rate_share': 'Порог расхода, % от типичного', 'season_schedule': 'Расписание периодов', 'peak_windows': 'Пиковые окна',
                  'auto_peaks': 'Искать пиковые режимы по расходу', 'peak_factor': 'Пик: во сколько раз выше медианы сезона',
                  'visible_pages': 'Разделы меню', 'working_horizons': 'Рабочие горизонты', 'chart_style': 'Оформление графиков'}


def _setting_value(name: str, value: Any) -> Any:
    """Значение в том виде, в каком его пишет 5.8."""
    if name == 'r2_threshold':
        return float(value)
    if name in ('season_start', 'season_end', 'season_gap_days'):
        return int(value)
    if name == 'season_schedule':      # список [дата, вид]; пустой текст снимает расписание
        return [list(x) for x in seasons.parse_schedule(value)[0]] or None if value else None
    if name == 'peak_factor':
        return float(value)
    if name == 'season_rate_share':
        return float(value)
    if name == 'manometer_wells':      # как ``parse_wells`` 5.8: «№», запятые, пробелы, естественный порядок
        return parse_wells(value if isinstance(value, str) else ', '.join(str(x) for x in value))
    if name == 'visible_pages':
        return list(navigation.DEFAULT) if value is None else [navigation.ALIASES.get(x, x) for x in value]
    return value


class Conflict(RuntimeError):
    """Проект изменён параллельно (например, в 5.8). Текст — для пользователя."""


class ProjectInfo:
    """Сведения о проекте для модулей «Обзор», «Исключенные точки», «История фильтра».
    Журнал и каталог читаются по запросу: другим модулям они не нужны."""

    def __init__(self, pid: str, manifest: Mapping[str, Any], store: Store, cache: FrameCache):
        self.id, self.name, self.demo = pid, manifest.get('name', ''), bool(manifest.get('demo'))
        self.tables = dict(manifest.get('tables', {}))
        self._store, self._cache = store, cache

    def history(self) -> pd.DataFrame:
        """Журнал действий 5.8: «Дата», «Действие», «Подробности» (JSON), новые сверху, до 500 записей."""
        return self._store.history(self.id)

    def catalog(self) -> dict[str, Any]:
        """Состав проекта как в 5.8 (``Project.catalog``): строки, скважины, даты по наборам."""
        return self._cache.catalog()


class Projects:
    def __init__(self, root=STORAGE, warm: bool = False):
        self.store = Store(root)
        self.warm = warm        # после открытия большого проекта готовить суточный набор «Поскважинного анализа» в фоне
        self._lock = threading.RLock()
        self._frames: OrderedDict[tuple, FrameCache] = OrderedDict()
        self._views: OrderedDict[tuple, Data] = OrderedDict()

    # --- список и создание ---
    def list(self) -> list[dict[str, Any]]:
        return [self.summary(m) for m in self.store.list()]

    @staticmethod
    def summary(m: Mapping[str, Any]) -> dict[str, Any]:
        settings = m.get('settings', {})
        return {'id': m['id'], 'name': m['name'], 'demo': bool(m.get('demo')), 'updated': m['updated'], 'version': m.get('version'),
                'revision': m.get('revision', 0), 'tables': dict(m.get('tables', {})),
                'settings': {k: settings.get(k) for k in EDITABLE_SETTINGS},
                'menu': navigation.visible(settings),     # разделы 5.8, показанные в меню (как в боковой панели 5.8)
                'excluded': len(settings.get('excluded_points', {}))}

    def create_demo(self, large: bool = False, rows: Mapping[str, Any] | None = None) -> str:
        """Демо-объект; ``large`` — большой объём для проверки скорости (``app.core.demo_large``)."""
        if large:
            from app.core.demo_large import DEFAULTS, create_large_demo
            sizes = {k: int(v) for k, v in (rows or {}).items() if k in DEFAULTS and v is not None}
            return create_large_demo(self.store, **sizes)
        from app.core import pressure_demo
        from app.core.demo import demo_frames
        pid = self.store.create('Демонстрационный объект', demo=True)
        frames = demo_frames()
        frames['pressure_match'] = pressure_demo.frame()
        self.store.commit(pid, frames=frames, action='Демонстрационные данные')
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
        data.project = ProjectInfo(pid, m, self.store, cache)
        data.wells = ordered(cache.catalog()['wells'])
        if self.warm and len(shown.get('production', ())) >= WARM_ROWS:
            self._warm_wells(data)
        with self._lock:
            for stale in [k for k in self._views if k[0] == pid]:
                self._views.pop(stale)
            self._views[key] = data
            while len(self._views) > _CACHE_PROJECTS:
                self._views.popitem(last=False)
        return data

    @staticmethod
    def _warm_wells(data: Data) -> None:
        """Суточный набор объекта (14–16 с на 2 млн строк) строится один раз; запрос пользователя ждёт тот же кэш, а не считает заново."""
        def build():
            try:
                from app.modules import well_analysis
                well_analysis.dataset({k.value: data[k] for k in data}, data.settings, data.mapping)
            except Exception:       # прогрев необязателен: ошибку покажет сам раздел
                pass
        threading.Thread(target=build, name='warm-wells', daemon=True).start()

    def select(self, pid: str, needs, optional=()) -> Data:
        data = self.data(pid)
        missing = [k for k in needs if k not in data or data[k].empty]
        if missing:
            raise MissingData(missing)
        keep = (*needs, *optional)
        out = Data({k: data[k] for k in keep if k in data}, {k: data.raw[k] for k in keep if k in data.raw}, data.excluded)
        out.settings, out.revision, out.mapping, out.wells = data.settings, data.revision, data.mapping, data.wells
        out.project = data.project
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
            except (TypeError, ValueError) as e:
                ok = False
                if name == 'season_schedule' and isinstance(e, ValueError) and e.args:
                    raise ParamError(f'Расписание периодов: {e.args[0]}') from None
            if not ok:
                raise ParamError(f'Недопустимое значение настройки «{SETTING_LABELS.get(name, name)}»')
            cfg[name] = _setting_value(name, value)
            if name == 'season_schedule':      # пиковые окна пишутся из того же файла расписания
                cfg['peak_windows'] = [list(x) for x in seasons.parse_schedule(value)[1]] or None if value else None
        # Действия журнала как в 5.8: «Состав меню» (с отметкой о показанном «Кроссплоте»; сброс — без неё),
        # «Оформление графиков», иначе «Изменение правил».
        action = 'Изменение правил'
        if set(values) == {'visible_pages'}:
            action = 'Состав меню'
            if values['visible_pages'] is not None:
                cfg['pressure_module_menu_seen'] = True
        elif set(values) == {'working_horizons'}:
            action = 'Выбор рабочих горизонтов'
        elif set(values) == {'chart_style'}:
            action = 'Оформление графиков'
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

    def assign_object_categories(self, pid: str, changes: Mapping[str, Any],
                                 expected: int | None = None) -> dict[str, Any]:
        """Категории объектов кроссплота давлений — в сохранённом виде 5.8, где их вводит раздел «Категории»."""
        from .modules.pressure import CATEGORIES_JOURNAL, with_categories
        raw = self.data(pid).raw.get(DatasetKind.PRESSURE_MATCH)
        objects = [str(o) for o in raw.object.unique()] if raw is not None and not raw.empty else []
        settings = with_categories(self.manifest(pid).get('settings', {}), objects, changes)
        return self.summary(self._commit(pid, settings, expected, CATEGORIES_JOURNAL,
                                         {'object_groups': settings['panels']['pressure_match']['object_groups']}))

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

"""Удаление наборов данных проекта целиком (например, всех данных ГИС перед загрузкой обновлённой БД).

Ничего не стирается без явного подтверждения: сначала показывается, что именно будет удалено (строк по наборам),
затем, после подтверждения, в экспорты проекта сохраняется резервная копия, и только потом создаётся новая ревизия данных
без выбранных наборов. Прежние данные остаются в копиях проекта: «Вернуть эти данные» (``Store.rollback``) возвращает их."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .import_checklist import ITEMS

# Составные наборы: один пункт «ГИС целиком» вместо шести таблиц.
BUNDLES: dict[str, tuple[str, list[str]]] = {
    'gis': ('ГИС целиком (пачки, интервалы, замеры, термобарика, заполнение ствола, пометки)',
            ['gis_packs', 'gis_intervals', 'gis_observations', 'gis_thermobaric', 'gis_filling', 'gis_annotations']),
}
LABELS = {i['key']: i['label'] for i in ITEMS}


def expand(keys: Iterable[str]) -> list[str]:
    out: list[str] = []
    for k in keys:
        for t in (BUNDLES[k][1] if k in BUNDLES else [k]):
            if t not in out:
                out.append(t)
    return out


def available(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Наборы, которые можно удалить: только те, где в проекте есть строки."""
    tables = manifest.get('tables', {})
    out = []
    for key, (label, members) in BUNDLES.items():
        rows = sum(int(tables.get(t, 0) or 0) for t in members)
        if rows:
            out.append({'key': key, 'label': label, 'rows': rows, 'tables': [t for t in members if tables.get(t)]})
    for key, label in LABELS.items():
        if key != 'groups' and tables.get(key):
            out.append({'key': key, 'label': label, 'rows': int(tables[key]), 'tables': [key]})
    return out


def plan(manifest: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    tables = manifest.get('tables', {})
    wanted = expand(keys)
    unknown = [k for k in wanted if k not in LABELS or k == 'groups']
    if unknown:
        raise ValueError('Неизвестный набор данных: ' + ', '.join(unknown))
    items = [{'key': t, 'label': LABELS[t], 'rows': int(tables[t])} for t in wanted if tables.get(t)]
    if not items:
        raise ValueError('В проекте нет данных, выбранных для удаления.')
    return {'items': items, 'total': sum(i['rows'] for i in items), 'keep': [t for t in tables if t not in wanted]}


def delete(projects, pid: str, keys: Iterable[str], expected: int | None = None) -> dict[str, Any]:
    """Удалить наборы: резервная копия → новая ревизия без них. Возвращает проект и ``undo`` (копия данных до удаления)."""
    store = projects.store
    manifest = projects.manifest(pid)
    found = plan(manifest, keys)
    if expected is not None and manifest['revision'] != expected:
        raise ValueError('Проект изменен в другой вкладке. Обновите страницу и повторите действие.')
    backup = store.save_export(pid, f"{manifest['name']} — резерв до удаления данных.gasatlas.zip", store.backup(pid, originals=False),
                               {'kind': 'backup', 'reason': 'удаление наборов данных'})
    _, frames = store.load(pid)
    removed = {i['key'] for i in found['items']}
    saved = store.commit(pid, {n: f for n, f in frames.items() if n not in removed}, expected=manifest['revision'],
                         action='Удаление наборов данных',
                         details={'deleted': {i['key']: i['rows'] for i in found['items']}, 'backup': backup.name})
    versions = store.versions(pid)
    undo = next((v['before'] for v in versions if v['current']), None)
    return {'project': projects.summary(saved), 'deleted': found['items'], 'total': found['total'], 'backup': backup.name, 'undo': undo}

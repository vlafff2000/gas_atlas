"""Слепок Атласа: модули, виды данных и отмеченные пункты паритета не пропадают молча.

Если модуль, вид данных или пункт паритета убран намеренно — впишите его в REMOVED_ON_PURPOSE с причиной
и обновите снимок. Иначе тест падает: это и есть проверка «ничего не потеряно» (CLAUDE.md, аудит объединения, раздел 2).
"""
from pathlib import Path

from atlas import registry
from atlas.domain import DatasetKind

ROOT = Path(__file__).resolve().parents[2]

# Модули Атласа (registry.modules()). Удалённые намеренно — в REMOVED_ON_PURPOSE.
MODULES = [
    'an_report', 'an_revision', 'an_wf_table', 'builder', 'exclusions', 'filter_history', 'fund', 'gdi', 'gdi_trend', 'ggh',
    'elpro_compare', 'gas_accounting', 'seasonal', 'seasonal_groups', 'injection-decline', 'groups', 'histograms', 'overview', 'plan_fact', 'pressure', 'production', 'quality', 'response',
    'water', 'wells', 'gis',
]
REMOVED_ON_PURPOSE: dict[str, str] = {}   # id модуля -> причина; пусто, ничего не удалено

# Виды данных, которые принимает проект (DatasetKind).
DATASET_KINDS = [
    'production', 'gdi', 'response', 'object_pressure', 'operations', 'water', 'water_factor',
    'bottom', 'construction', 'pressure_match', 'plan', 'ggh', 'elpro', 'annulus',
    'gas_db', 'model', 'model_object', 'model_cells',
    'well_geo', 'gis_packs', 'gis_observations', 'gis_intervals',
]

# Сколько пунктов со статусом ✅ стоит в каждом чек-листе паритета (docs/parity/*.md).
# Число может расти, но не падать: пункт, снятый с ✅, должен быть осознанным.
PARITY_DONE = {
    'exclusions.md': 12, 'export.md': 23, 'filter_history.md': 7, 'gdi.md': 31, 'groups.md': 20,
    'import.md': 41, 'overview.md': 8, 'passport.md': 11, 'pressure.md': 44, 'production.md': 32,
    'projects.md': 8, 'response.md': 21, 'settings.md': 12, 'water.md': 3, 'wells.md': 32,
}


def test_modules_are_all_present():
    loaded = set(registry.modules())
    expected = set(MODULES)
    missing = expected - loaded - set(REMOVED_ON_PURPOSE)
    assert not missing, f'Пропали модули без записи в REMOVED_ON_PURPOSE: {sorted(missing)}'
    added = loaded - expected
    assert not added, f'Новые модули — добавьте в слепок MODULES: {sorted(added)}'


def test_dataset_kinds_are_all_present():
    kinds = {k.value for k in DatasetKind}
    assert set(DATASET_KINDS) == kinds, f'Виды данных изменились: +{sorted(kinds - set(DATASET_KINDS))} -{sorted(set(DATASET_KINDS) - kinds)}'


def test_parity_checklists_keep_done_items():
    for name, done in PARITY_DONE.items():
        text = (ROOT / 'docs' / 'parity' / name).read_text(encoding='utf-8')
        count = sum(1 for line in text.splitlines() if line.startswith('- ✅'))
        assert count >= done, f'docs/parity/{name}: было ✅ {done}, стало {count}'

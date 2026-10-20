"""Суточный график ЭЛПРО: день без записи и ноль — на оси X, исключённая точка — разрыв, КРУ 0–100, порог и температура."""
import numpy as np
import pandas as pd

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules import elpro_daily as ed

PROD, ELPRO = DatasetKind.PRODUCTION, DatasetKind.ELPRO


def frames():
    days = pd.to_datetime(['2025-06-01', '2025-06-02', '2025-06-03', '2025-06-04'])
    # 101: 01.06 работа; 02.06 — нулевой расход; 03.06 — записи нет; 04.06 — исключённая точка (строка есть, q пуст)
    prod = pd.DataFrame({'well': ['101', '101', '101', '102', '102', '102', '102', '103', '103'],
                         'date': [days[0], days[1], days[3], days[0], days[1], days[2], days[3], days[0], days[2]],
                         'q': [1000.0, 0.0, np.nan, 2000.0, 1000.0, 1000.0, 1000.0, 2000.0, 2000.0],
                         'kind': 'withdrawal', 'hours': [24.0, 0.0, np.nan, 24.0, 24.0, 24.0, 24.0, 24.0, 24.0]})
    elpro = pd.DataFrame({
        'well': ['101', '101', '102', '102', '102', '102', '103', '103', '103'],
        'date': [days[0], days[1], days[0], days[1], days[2], days[3], days[0], days[1], days[2]],
        'group': 'ГСП 4', 'kind': 'withdrawal',
        # 101 01.06: ЭЛПРО видит 0.8 (ниже порога), T как у соседа; 102 01.06: видит 1.8 (норма), КРУ 40;
        # 102 02.06: 1.0 (ниже порога), T 15.2 ≈ медиана; 102 03.06: T 25 — единственная скважина в сутках, сравнения нет
        # 103: 01.06 и 02.06 видит 2.0 при T 15 (две «других» скважины для медианы); 03.06 — пропуск расхода «-» (NaN)
        'q': [0.8, 0.0, 1.8, 1.0, 1.0, 1.0, 2.0, 2.0, np.nan], 'np': '1',
        't': [15.0, 15.0, 15.0, 15.2, 25.0, 15.1, 15.0, 15.0, 15.0],
        'p': 50.0, 'y': [150.0, -5.0, 40.0, 30.0, 20.0, 30.0, 40.0, 40.0, 40.0], 'hours': 24.0, 'file': 'x'})
    return prod, elpro, days


def data_of(prod, elpro):
    data = Data({PROD: prod, ELPRO: elpro})
    data.mapping = {'101': {'group': 'ГСП 4'}, '102': {'group': 'ГСП 4'}}
    data.settings = {}
    return data


def test_daily_rules_zero_gap_and_clipping():
    prod, elpro, days = frames()
    f = ed.daily(prod, elpro, 'withdrawal', '101', days[0], days[3])
    assert f.q.iloc[0] == 1.0                                # запись есть
    assert f.q.iloc[1] == 0.0                                # ноль — на оси X
    assert f.q.iloc[2] == 0.0                                # нет записи — на оси X, не разрыв
    assert np.isnan(f.q.iloc[3])                             # исключённая точка — разрыв
    assert f.cru.iloc[0] == 100.0                            # 150 → 100
    assert f.hours.iloc[2] == 0.0                            # часы: день без записи — ноль, как расход
    assert np.isnan(f.hours.iloc[3])                         # часы у исключённой точки — разрыв
    assert f.cru.iloc[1] == 0.0                              # −5 → 0
    assert np.isnan(f.t.iloc[2])                             # в ЭЛПРО записи нет — разрыв, не ноль


def test_sensitivity_counts_hidden_low_flow_days():
    prod, elpro, _ = frames()
    s = ed.sensitivity(prod, elpro, 'withdrawal', threshold=1.5, tol=1.0, start=None, end=None).set_index('well')
    # 101: сутки работы по БД — 01.06 (1.0 тыс.); ЭЛПРО видит 0.8 < 1.5 и T = 15 ≈ медиана → скрыт
    assert s.loc['101', 'days_work'] == 1
    assert s.loc['101', 'days_low'] == 1
    assert s.loc['101', 'days_hidden'] == 1                  # 01.06: T 15 при медиане остальных (15) ≈ T
    assert s.loc['101', 'volume_hidden'] == 1.0
    # 103 на 03.06: расход в ЭЛПРО — пропуск (NaN): не ноль, не «ниже порога»
    assert s.loc['103', 'days_work'] == 2                    # 01.06 и 03.06 — расход по БД расходов > 0
    assert s.loc['103', 'days_low'] == 0
    # 102: работает 4 суток; 02.06 ниже порога и T ≈ медиана → скрыт; 03.06 одна скважина в сутки → сравнения нет
    assert s.loc['102', 'days_work'] == 4
    assert s.loc['102', 'days_low'] == 3                     # 02.06, 03.06, 04.06 — ниже порога
    assert s.loc['102', 'days_hidden'] == 1
    assert s.loc['102', 'cru_normal'] == 40.0                # 01.06 — ЭЛПРО видит 1.8, КРУ 40


def test_module_runs_and_builds_charts():
    prod, elpro, days = frames()
    module = ed.ElproDailyModule()
    data = data_of(prod, elpro)
    assert module.options('well', data, {'kind': 'withdrawal'}) == ['101', '102', '103']
    result = module.run(data, module.spec.coerce({'kind': 'withdrawal', 'well': '101'}))
    assert {t.id for t in result.tables} == {'elpro-sensitivity'}
    assert [c.id for c in result.charts] == ['elpro-flow-101', 'elpro-cru-101', 'elpro-temp-101']
    flow = result.charts[0]
    assert any(s.axis == 'y2' for s in flow.series)
    assert flow.y2 is not None


def test_flow_chart_extras_each_on_own_axis():
    prod, elpro, days = frames()
    module = ed.ElproDailyModule()
    data = data_of(prod, elpro)
    result = module.run(data, module.spec.coerce({'kind': 'withdrawal', 'well': '101', 'extras': ['cru', 'p', 't', 'hours']}))
    flow = result.charts[0]
    # каждый выбранный ряд — на своей правой шкале, по порядку от графика наружу
    assert [a.label for _, a in flow.right_axes()] == ['Степень открытия КРУ, %', 'Давление газа', 'Температура газа, °C', 'Часы работы']
    axes = {s.name: s.axis for s in flow.series}
    assert axes['КРУ'] == 'y2' and axes['Давление ЭЛПРО'] == 'y3' and axes['Температура газа'] == 'y4' and axes['Часы работы'] == 'y5'
    # пусто — график расхода без правых осей
    plain = module.run(data, module.spec.coerce({'kind': 'withdrawal', 'well': '101', 'extras': []})).charts[0]
    assert plain.right_axes() == []


def test_export_builds_flow_chart_per_well_with_chosen_rows():
    from atlas.api_export import options_from, with_elpro

    class Plan:                                  # план экспорта: только список заданий
        jobs = []

    prod, elpro, _ = frames()
    data = data_of(prod, elpro)
    form = {'modules': ['elpro_daily'], 'elpro_daily_wells': ['101', '102'], 'elpro_daily_hours': False,
            'elpro_daily_cru': True, 'elpro_daily_p': True}
    options, _, _ = options_from(form, data)
    assert options['elpro_daily']['extras'] == ['cru', 'p']
    plan = with_elpro(Plan(), data, options)
    assert len(plan.jobs) == 2                           # по графику на скважину, таблицы в выгрузку не идут
    assert all(job.module == 'elpro_daily' for job in plan.jobs)


def test_dynamic_params_match_frontend_shape():
    """Интерфейс: зависимый список с kind=multi — массив, с kind=choice — одна строка. Иначе вкладка падает целиком."""
    from atlas import registry
    for module in registry.modules().values():
        for p in module.spec.params:
            if not p.dynamic:
                continue
            if p.kind == 'multi':
                assert isinstance(p.default, list), (module.spec.id, p.name)
            if p.kind == 'choice':
                assert isinstance(p.default, str), (module.spec.id, p.name)
    well = next(p for p in ed.ElproDailyModule.spec.params if p.name == 'well')
    assert well.kind == 'choice' and well.dynamic and well.default == ''

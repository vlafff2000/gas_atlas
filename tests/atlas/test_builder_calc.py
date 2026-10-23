"""Конструктор графиков, этап 4: преобразования ряда и формулы (безопасный разбор, пропуски, циклы)."""
import numpy as np
import pandas as pd
import pytest

from atlas.contract import Data, ParamError
from atlas.modules import builder, builder_calc as calc
from tests.atlas.test_builder import frames

N = np.nan
Q = {'dataset': 'production', 'y': 'q', 'wells': ['1', '2']}         # тыс. м³/сут: скв. 1 — 100, 0, нет, 200; скв. 2 — 50…80


@pytest.fixture()
def data():
    return Data(frames())


def run(data, *rows, **labels):
    return builder.build(data, {'series': list(rows), **labels})


def curves(result):
    return {s.name: list(np.round(s.y.astype(float), 6)) for s in result.charts[0].series}


def same(a, b):
    return len(a) == len(b) and all((np.isnan(x) and np.isnan(y)) or x == pytest.approx(y) for x, y in zip(a, b))


def text(result):
    return ' '.join(n.text for n in result.notes)


def one(data, transform, row=Q, **more):
    r = run(data, {**row, 'transform': transform, **more})
    return r, curves(r)


# ---------- преобразования ----------

def test_cumulative_from_period_start_rate_to_volume(data):
    r, c = one(data, {'op': 'cumsum'})
    assert same(c['Суточный расход газа, накопленное · скв. 1'], [0.1, 0.1, N, 0.3])       # ноль простоя — точка, «нет данных» — разрыв
    assert same(c['Суточный расход газа, накопленное · скв. 2'], [0.05, 0.11, 0.18, 0.26])
    assert r.charts[0].y.unit == 'млн м³' and 'накопленное' in r.charts[0].y.label
    r, c = one(data, {'op': 'cumsum'}, date_from='2025-01-02')
    assert same(c['Суточный расход газа, накопленное · скв. 2'], [0.06, 0.13, 0.21])       # с нуля от начала периода


def test_rolling_by_points_and_days(data):
    _, c = one(data, {'op': 'rolling', 'n': 2})
    assert same(c['Суточный расход газа, скользящее среднее (2 точек) · скв. 2'], [50, 55, 65, 75])
    assert same(c['Суточный расход газа, скользящее среднее (2 точек) · скв. 1'], [100, 50, N, 200])
    _, c = one(data, {'op': 'rolling', 'n': 2, 'by': 'days'})
    assert same(next(v for k, v in c.items() if k.endswith('скв. 2')), [50, 55, 65, 75])


def test_by_day_and_month(data):
    p = {'dataset': 'operations', 'y': 'p_wellhead', 'wells': ['1']}           # 2025-01-02 — два замера: 41 и 43
    for agg, value in (('mean', 42), ('max', 43), ('min', 41), ('sum', 84)):
        r, c = one(data, {'op': 'day', 'agg': agg}, row=p)
        assert same(list(c.values())[0], [40, value])
        assert r.charts[0].y.unit == 'кгс/см²'
    r, c = one(data, {'op': 'month', 'agg': 'sum'})
    assert same(c['Суточный расход газа, сумма за месяц · скв. 2'], [0.26]) and r.charts[0].y.unit == 'млн м³'
    assert same(c['Суточный расход газа, сумма за месяц · скв. 1'], [0.3])       # пропуск не ноль, не сумма
    r, c = one(data, {'op': 'month', 'agg': 'mean'})
    assert same(c['Суточный расход газа, среднее за месяц · скв. 2'], [65]) and r.charts[0].y.unit == 'тыс. м³/сут'
    assert str(r.charts[0].series[0].x[0])[:10] == '2025-01-01'


def test_by_wells_of_group(data):
    r, c = one(data, {'op': 'group', 'agg': 'mean'})
    assert list(c) == ['Суточный расход газа, среднее по скважинам']                 # одна кривая
    assert same(c['Суточный расход газа, среднее по скважинам'], [75, 30, 70, 140])  # «нет данных» не учитывается, ноль — учитывается
    _, c = one(data, {'op': 'group', 'agg': 'sum'})
    assert same(list(c.values())[0], [150, 60, 70, 280])
    assert 'по 2 кривым' in text(r)


def test_cumulative_of_sum_over_wells(data):
    r, c = one(data, {'op': 'group', 'agg': 'sum', 'cum': True})
    assert same(list(c.values())[0], [0.15, 0.21, 0.28, 0.56]) and r.charts[0].y.unit == 'млн м³'
    assert 'накопленное' in r.charts[0].y.label
    r, c = one(data, {'op': 'month', 'agg': 'sum', 'cum': True})
    assert same(c['Суточный расход газа, сумма за месяц, накопленное · скв. 2'], [0.26]) and r.charts[0].y.unit == 'млн м³'
    with pytest.raises(ParamError, match='только вместе'):
        one(data, {'op': 'group', 'agg': 'mean', 'cum': True})


def test_normalize(data):
    w2 = {**Q, 'wells': ['2']}
    r, c = one(data, {'op': 'norm', 'norm': 'first'}, row=w2)
    assert same(list(c.values())[0], [1, 1.2, 1.4, 1.6]) and r.charts[0].y.unit == 'д. ед.'
    _, c = one(data, {'op': 'norm', 'norm': 'max'}, row=w2)
    assert same(list(c.values())[0], [0.625, 0.75, 0.875, 1])
    _, c = one(data, {'op': 'norm', 'norm': 'value', 'value': '25'}, row=w2)
    assert same(list(c.values())[0], [2, 2.4, 2.8, 3.2])
    frame = pd.DataFrame({'entity': '1', 'x': [1.0, 2.0], 'y': [0.0, 5.0], 'id': None})
    out, notes = calc.apply(frame, calc.Transform('norm', norm='first'), '', 'Ряд 1', False)
    assert out['y'].isna().all() and 'равно нулю' in notes[0].text                    # делить на ноль — пропуск с заметкой


def test_scale_and_units(data):
    w2 = {**Q, 'wells': ['2']}
    r, c = one(data, {'op': 'mul', 'value': 1000}, row=w2)
    assert same(list(c.values())[0], [50_000, 60_000, 70_000, 80_000]) and r.charts[0].y.unit == 'м³/сут'
    r, _ = one(data, {'op': 'div', 'value': '1000'}, row=w2)
    assert r.charts[0].y.unit == 'млн м³/сут'
    r, c = one(data, {'op': 'mul', 'value': 2}, row=w2)
    assert r.charts[0].y.unit == '' and '× 2' in r.charts[0].y.label                   # единица неизвестна — инженер задаёт её вручную
    r, _ = one(data, {'op': 'mul', 'value': 2}, row=w2, unit='тыс. м³')
    assert r.charts[0].y.unit == 'тыс. м³'
    r, _ = one(data, {'op': 'mul', 'value': 0.0980665}, row={'dataset': 'operations', 'y': 'p_wellhead'})
    assert r.charts[0].y.unit == 'МПа'
    _, c = one(data, {'op': 'add', 'value': -50}, row=w2)
    assert same(list(c.values())[0], [0, 10, 20, 30])


def test_diff_skips_gaps(data):
    _, c = one(data, {'op': 'diff'})
    assert same(c['Δ Суточный расход газа · скв. 1'], [N, -100, N, 200])              # разность с предыдущим имеющимся значением
    assert same(c['Δ Суточный расход газа · скв. 2'], [N, 10, 10, 10])


def test_no_transform_and_old_layouts(data):
    base = curves(run(data, Q))
    for t in (None, '', {}, 'none', {'op': 'none'}):
        assert all(same(curves(run(data, {**Q, 'transform': t}))[k], v) for k, v in base.items())
    assert all(same(curves(run(data, {**Q, 'source': 'field'}))[k], v) for k, v in base.items())


@pytest.mark.parametrize('transform, error', [
    ({'op': 'magic'}, 'преобразование'), ({'op': 'div', 'value': 0}, 'на ноль'), ({'op': 'mul'}, 'введите число'),
    ({'op': 'mul', 'value': 'abc'}, 'число'), ({'op': 'rolling', 'n': 0}, 'окно'), ({'op': 'day', 'agg': 'median'}, 'сводка'),
    (['cumsum'], 'объект'),
])
def test_bad_transform_is_russian_error(data, transform, error):
    with pytest.raises(ParamError, match='Ряд 1') as e:
        run(data, {**Q, 'transform': transform})
    assert error in str(e.value)


def test_time_transform_on_number_x_is_note(data):
    r = run(data, {'dataset': 'gdi', 'y': 'p_res', 'x': 'q', 'transform': {'op': 'month'}})
    assert r.charts and 'только когда X — дата' in text(r)


# ---------- формулы ----------

def F(formula, **more):
    return {'source': 'formula', 'formula': formula, **more}


def test_formula_ratio_on_second_axis_with_hidden_input(data):
    r = run(data, Q, {**Q, 'hidden': True, 'transform': {'op': 'mul', 'value': 2}}, F('A/B', axis='y2'))
    chart = r.charts[0]
    assert [s.axis for s in chart.series] == ['y', 'y', 'y2', 'y2']                  # скрытый ряд B не показан
    c = curves(r)
    assert same(c['A/B · скв. 1'], [0.5, N, N, 0.5])          # 0/0 — пропуск, «нет данных» — пропуск
    assert same(c['A/B · скв. 2'], [0.5] * 4)
    assert 'деление на ноль: 1' in text(r) and chart.y2.label == 'A/B'


def test_formula_by_key_well_date_and_mean(data):
    r = run(data, Q, {'dataset': 'operations', 'y': 'p_wellhead'}, F('A/B'))
    c = curves(r)
    assert same(c['A/B · скв. 1'], [2.5, 0, N, N])            # 100/40; 0/среднее(41, 43); нет Q; нет P
    assert same(c['A/B · скв. 2'], [N, N, 1.4, N])            # 70/50
    assert 'взято среднее' in text(r)
    r = run(data, Q, {'dataset': 'gas_db', 'y': 'gas'}, F('A/B*1000'))
    assert 'только по дате' in text(r)                         # у объекта нет скважин
    assert same(curves(r)['A/B*1000 · скв. 2'], [50 / 1.0, 60 / 1.1, 70 / 1.2, 80 / 1.3])
    r = run(data, Q, {'dataset': 'construction', 'y': 'bottom_m'}, F('A/B', key='well'))
    assert same(curves(r)['A/B · скв. 2'], [50 / 1600, 60 / 1600, 70 / 1600, 80 / 1600])


def test_formula_log_and_sqrt_skip_points(data):
    r = run(data, Q, F('ln(A) + sqrt(A - 60)'))
    c = curves(r)
    assert same(c['ln(A) + sqrt(A - 60) · скв. 2'], [N, np.log(60), np.log(70) + np.sqrt(10), np.log(80) + np.sqrt(20)])
    t = text(r)
    assert 'логарифм от нуля или отрицательного: 1' in t and 'корень из отрицательного: 2' in t


def test_formula_cyrillic_letters_symbols_and_transform(data):
    r = run(data, Q, {**Q, 'hidden': True}, F('(А − В) × 2 ÷ 4 + А', transform={'op': 'cumsum'}, unit='тыс. м³', axis='y2'))
    c = curves(r)
    assert same(c['(А − В) × 2 ÷ 4 + А, накопленное · скв. 2'], [50, 110, 180, 260])
    assert r.charts[0].y2.unit == 'тыс. м³'


@pytest.mark.parametrize('formula, expected', [
    ('(A-B)/A*100', [50.0, 75.0]), ('-A^2', [-4.0, -16.0]), ('2^-1*A', [1.0, 2.0]), ('A^3^0', [2.0, 4.0]),
    ('max(A; B) + min(A, B)', [3.0, 5.0]), ('mean(A; C)', [2.0, 4.0]), ('abs(B - A) + pi*0 + e*0', [1.0, 3.0]),
    ('log10(A*50)', [2.0, np.log10(200)]), ('exp(0*A)', [1.0, 1.0]), ('A/0', [N, N]), ('1,5*A', [3.0, 6.0]),
    ('R1 + R2', [3.0, 5.0]), ('lg(A*5)', [1.0, np.log10(20)]),
])
def test_evaluate(formula, expected):
    f = calc.parse_formula(formula, 4, 3)
    env = {1: np.array([2.0, 4.0]), 2: np.array([1.0, 1.0]), 3: np.array([N, 4.0])}
    out, _ = calc.evaluate(f.tree, env, 2)
    assert same(list(out), expected)


@pytest.mark.parametrize('formula, error', [
    ('A +* B', 'ожидается'), ('A/(B', 'не хватает «)»'), ('2 3 + A', 'лишнее'), ('A @ B', 'недопустимый символ «@»'),
    ('__import__(A)', 'неизвестная функция'), ('__import__("os")', 'недопустимый символ'), ('A.__class__', 'недопустимый символ «.»'), ('exec(A)', 'неизвестная функция'),
    ('os', 'неизвестное имя'), ('a/b', 'неизвестное имя'), ('log(A)', 'ln и log10'), ('sqrt(A; B)', 'аргументов'),
    ('max(A)', 'аргументов'), ('2*3', 'нет ни одного ряда'), ('A/', 'обрывается'), ('A/D', 'ряда D'), ('R9', 'ряда R9'),
    ('(' * 70 + 'A' + ')' * 70, 'вложенность'), ('A' + '+A' * 300, 'не длиннее'), ('"A"', 'недопустимый символ'),
    ('lambda: A', 'недопустимый символ'), ('A[0]', 'недопустимый символ «[»'),
])
def test_bad_formula_is_russian_error(data, formula, error):
    with pytest.raises(ParamError) as e:
        run(data, Q, Q, F(formula))
    assert 'Ряд 3' in str(e.value) and error in str(e.value)


def test_cycles_and_self_reference(data):
    with pytest.raises(ParamError, match='циклическая') as e:
        run(data, F('B + 1'), F('A * 2'))
    assert 'ряд 1' in str(e.value) and 'ряд 2' in str(e.value)
    with pytest.raises(ParamError, match='Ряд 2: циклическая'):
        run(data, Q, F('A + B'))
    with pytest.raises(ParamError, match='циклическая'):
        run(data, Q, F('A + C', hidden=True), F('B'))


def test_formula_empty_and_empty_input_are_notes(data):
    r = run(data, Q, F(''))
    assert 'введите формулу' in text(r) and len(r.charts[0].series) == 2
    r = run(data, {**Q, 'date_from': '2030-01-01', 'hidden': True}, F('A*2'))
    assert not r.charts and 'пуст' in text(r)
    r = run(data, {'dataset': 'production', 'y': ''}, F('A*2'))
    assert not r.charts and 'пуст' in text(r)


def test_formula_chain(data):
    r = run(data, {**Q, 'wells': ['2'], 'hidden': True}, F('A*2', hidden=True), F('B - A'))
    assert same(list(curves(r).values())[0], [50, 60, 70, 80])


def test_formula_unicode_digits_rejected_like_client():
    """Цифры других письменностей (٣) в числе — ошибка разбора, как в web/src/builderFormula.ts (там только 0-9)."""
    with pytest.raises(ParamError):
        calc.parse_formula('٣*A', 2, 2)


def test_cumulative_per_season(data):
    prod = data[builder.K.PRODUCTION]
    by_day = {'2025-01-01': '2024-2025', '2025-01-02': '2024-2025', '2025-01-03': '2025-2026', '2025-01-04': 'Нейтральный период 1'}
    prod['period'] = prod['date'].dt.strftime('%Y-%m-%d').map(by_day)
    w2 = {**Q, 'wells': ['2']}
    r, c = one(data, {'op': 'cumsum', 'season': True}, row=w2)
    assert same(list(c.values())[0], [0.05, 0.11, 0.07, np.nan]) and 'за сезон' in r.charts[0].y.label       # сброс с 3 января, нейтральный день не показан
    assert 'вне сезонов' in text(r)
    _, c = one(data, {'op': 'group', 'agg': 'sum', 'cum': True, 'season': True})
    assert same(list(c.values())[0], [0.15, 0.21, 0.07, np.nan])
    del prod['period']
    r, _ = one(data, {'op': 'cumsum', 'season': True}, row=w2)
    assert 'без сброса' in text(r)

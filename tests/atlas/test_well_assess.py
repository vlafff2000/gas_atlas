"""Ядро оценки скважины: свежесть замера и правило «недоход до низа фильтра» (Egor, 2026-11-20)."""
from atlas import well_assess as wa


def season(period, volume, mean, peak, kind='withdrawal'):
    return {'kind': kind, 'period': period, 'volume': volume, 'mean_rate': mean, 'max_rate': peak}


def seasons(factor):
    return [season('2022-2023', 100, 50, 80), season('2023-2024', 100, 50, 80), season('2025-2026', 100 * factor, 50 * factor, 80 * factor),
            season('2026-2027', 100 * factor, 50 * factor, 80 * factor), season('2024', 5, 5, 5, 'injection')]


def ev(factor, **kw):
    args = dict(bottom_m=990.0, bottom_date='01.06.2025', filter_bottom_m=1000.0, last_kr_year=None, seasons=seasons(factor), gdi=[], source='gis_report', today='01.09.2026')
    args.update(kw)
    return wa.bottom_evidence(**args)


def test_freshness_zero_before_kr_or_too_old_and_decays():
    assert wa.freshness('01.06.2025', '01.06.2026') == __import__('math').exp(-365 / 365)
    assert wa.freshness('01.06.2025', '01.06.2026', last_kr_year=2026) == 0.0
    assert wa.freshness('01.06.2023', '01.06.2026') == 0.0 and wa.freshness(None, '01.06.2026') == 0.0


def test_no_gap_no_evidence():
    assert ev(1.0, bottom_m=999.5) is None and ev(1.0, bottom_m=None) is None


def test_complex_decline_means_real_overlap():
    e = ev(0.6)
    assert e.level == 'strong' and 'перекрытие фильтра' in e.reason and 'Промывка' in e.recommendation


def test_stable_work_with_gis_bottom_suggests_templating():
    e = ev(1.0)
    assert e.level == 'weak' and 'отбит из отчёта ГИС' in e.reason and 'шаблонирование' in e.recommendation.lower()
    assert 'неизвестен' in ev(1.0, source='unknown').reason and ev(1.0, source='other').recommendation.startswith('ГДИ')


def test_geo_service_template_means_real_overlap_even_when_work_is_stable():
    e = ev(1.0, source='geo_template')
    assert e.level == 'strong' and 'прибор не причина' in e.reason and 'Промывка' in e.recommendation


def test_old_measure_or_after_kr_is_not_used_and_gdi_worse_blocks_templating():
    assert ev(1.0, last_kr_year=2026).weight == 0.0 and 'КР' in ev(1.0, last_kr_year=2026).reason
    gdi = [{'date': '01.01.2025', 'reliable': True, 'a': 1.0, 'b': 0.1, 'q_max': 100}, {'date': '01.09.2025', 'reliable': True, 'a': 1.5, 'b': 0.2, 'q_max': 100}]
    assert wa.gdi_trend(gdi, wa._day('01.06.2025')) == 'worse'
    assert ev(1.0, gdi=gdi).level == 'unknown'
    assert ev(1.0, seasons=[season('2025-2026', 100, 50, 80)]).level == 'unknown'

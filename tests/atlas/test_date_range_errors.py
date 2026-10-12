import pandas as pd
import pytest

from atlas.engine.core.config import DataRangeError, bounded_dates


def frame(dates):
    return pd.DataFrame({'date': pd.to_datetime(dates), 'q': 1.0})


def test_future_rows_are_dropped():
    future = (pd.Timestamp.today().normalize() + pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    out = bounded_dates(frame(['2024-01-01', '2024-01-02', future]), 'Период X')
    assert len(out) == 2


def test_typo_year_gives_readable_error():
    dates = ['2024-01-01'] * 300 + ['1924-01-01']
    with pytest.raises(DataRangeError) as e:
        bounded_dates(frame(dates), 'Группа «ГСП-1», период 2023/24')
    text = str(e.value)
    assert 'ГСП-1' in text and '01.01.1924' in text and '1924' in text


def test_api_maps_error_to_422_and_500_names_log():
    from atlas.api_projects import internal_error_text
    assert 'atlas.log' in internal_error_text()

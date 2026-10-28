from atlas.engine.core.export import sort_legend


def test_years_ascending():
    h, l = sort_legend(['a', 'b', 'c'], ['2024', '2022', '2023'])
    assert l == ['2022', '2023', '2024'] and h == ['b', 'c', 'a']


def test_seasons_and_groups():
    assert sort_legend([1, 2, 3], ['2023/24', '2021/22', '2022/23'])[1] == ['2021/22', '2022/23', '2023/24']
    assert sort_legend([1, 2, 3], ['ГСП-10', 'ГСП-2', 'ГСП-1'])[1] == ['ГСП-1', 'ГСП-2', 'ГСП-10']


def test_other_labels_untouched():
    assert sort_legend([1, 2], ['Факт', 'Прогноз'])[1] == ['Факт', 'Прогноз']
    assert sort_legend([1, 2], ['Факт 2023', 'Модель 2022'])[1] == ['Факт 2023', 'Модель 2022']

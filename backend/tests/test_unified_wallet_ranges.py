"""统一余额区间分摊的纯函数测试，不连接业务数据库。"""
from types import SimpleNamespace

import pytest

from app.services.billing.wallet_ranges import cost, normalize, remove_exact, split, take


def test_cumulative_cost_exact_and_mixed_ranges():
    """优惠到账额度的逐段成本累计后必须等于真实实付。"""
    lot = SimpleNamespace(total_units=7, total_amount_fen=10, available_ranges=[[0, 7]])
    assert cost(lot, [[0, 7]]) == 10
    selected, rest = split([[0, 7]], 3)
    assert selected == [[0, 3]] and rest == [[3, 7]]
    assert cost(lot, selected) + cost(lot, rest) == 10


def test_take_writes_remaining_ranges_without_overlap():
    """多个来源区间 FIFO 消费后只剩未用区间。"""
    lot = SimpleNamespace(total_units=10, total_amount_fen=13, available_ranges=[[0, 2], [5, 10]])
    selected, amount = take(lot, 4)
    assert selected == [[0, 2], [5, 7]]
    assert lot.available_ranges == [[7, 10]]
    assert amount == cost(SimpleNamespace(total_units=10, total_amount_fen=13), selected)


def test_invalid_ranges_fail_closed():
    """越界、重叠或空段不能静默修账。"""
    with pytest.raises(ValueError):
        normalize(5, [[0, 6]])
    with pytest.raises(ValueError):
        normalize(5, [[0, 3], [2, 4]])


def test_remove_exact_rejects_duplicate_or_outside_ranges():
    """退款撤销重新消费偿还额度时必须精确匹配原区间。"""
    assert remove_exact([[0, 10]], [[2, 4]]) == [[0, 2], [4, 10]]
    with pytest.raises(ValueError):
        remove_exact([[0, 10]], [[8, 12]])

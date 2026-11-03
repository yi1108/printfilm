"""按来源币区间累计取整，退款返还原币及原成本，不重估用户付款。"""


def _ranges(lot, values):
    """验证半开区间有序、不重叠，避免成本尾差或重复返还。"""
    result = []
    for value in sorted(values):
        if (not isinstance(value, (list, tuple)) or len(value) != 2
                or any(type(number) is not int for number in value)
                or not 0 <= value[0] < value[1] <= lot.total_coins
                or result and value[0] < result[-1][1]):
            raise RuntimeError("观影币来源区间不一致，已回滚")
        if result and value[0] == result[-1][1]:
            result[-1][1] = value[1]
        else:
            result.append(list(value))
    return result


def _cost(lot, values):
    """每个区间用累计金额差，完整批次精确等于真实付款整数分。"""
    return sum(lot.total_amount_fen * end // lot.total_coins - lot.total_amount_fen * start // lot.total_coins
               for start, end in values)


def _available(lot):
    """区间、币余量和金额余量必须三者相符，不能静默修账。"""
    ranges = _ranges(lot, lot.available_ranges)
    if sum(end - start for start, end in ranges) != lot.remaining_coins or _cost(lot, ranges) != lot.remaining_amount_fen:
        raise RuntimeError("观影币批次金额不一致，已回滚")
    return ranges


def allocate_cost(lot, coins: int):
    """按来源币序号FIFO消费，记录精确区间供未来混合批次退款使用。"""
    available = _available(lot)
    if not 0 < coins <= lot.remaining_coins:
        raise RuntimeError("观影币批次余额不一致，已回滚")
    remaining, selected, retained = coins, [], []
    for start, end in available:
        take = min(remaining, end - start)
        if take:
            selected.append([start, start + take])
            remaining -= take
        if start + take < end:
            retained.append([start + take, end])
    cost = _cost(lot, selected)
    lot.available_ranges = retained
    lot.remaining_coins -= coins
    lot.remaining_amount_fen -= cost
    return selected, cost


def restore_cost(lot, allocation) -> None:
    """返还原消费区间，保留其累计尾差，禁止重叠重复返还。"""
    available = _available(lot)
    returned = _ranges(lot, allocation.cost_ranges)
    if sum(end - start for start, end in returned) != allocation.coins or _cost(lot, returned) != allocation.amount_fen:
        raise RuntimeError("观影币消费成本不一致，已回滚")
    lot.available_ranges = _ranges(lot, available + returned)
    lot.remaining_coins += allocation.coins
    lot.remaining_amount_fen += allocation.amount_fen

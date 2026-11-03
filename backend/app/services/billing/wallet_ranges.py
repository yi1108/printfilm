"""统一额度来源的区间运算；每段实付成本使用累计取整差。"""


def normalize(total, values):
    """合并相邻区间，拒绝越界及重叠造成的重复资金。"""
    result = []
    for value in sorted(values):
        if (not isinstance(value, (list, tuple)) or len(value) != 2
                or any(type(n) is not int for n in value)
                or not 0 <= value[0] < value[1] <= total
                or result and value[0] < result[-1][1]):
            raise ValueError("资金来源区间不一致，操作已回滚")
        if result and value[0] == result[-1][1]:
            result[-1][1] = value[1]
        else:
            result.append(list(value))
    return result


def units(values):
    """额度序号使用半开区间。"""
    return sum(end - start for start, end in values)


def cost(lot, values):
    """完整消费一批时，累计实付成本精确等于该批实际付款。"""
    return sum(lot.total_amount_fen * end // lot.total_units
               - lot.total_amount_fen * start // lot.total_units for start, end in values)


def split(values, amount):
    """从已有区间中按顺序切出指定额度，不改动输入。"""
    if not 0 <= amount <= units(values):
        raise ValueError("资金来源额度不足")
    selected, rest = [], []
    for start, end in values:
        count = min(amount, end - start)
        if count:
            selected.append([start, start + count])
            amount -= count
        if start + count < end:
            rest.append([start + count, end])
    return selected, rest


def take(lot, amount):
    """消费可用额度后写回新的列表，让 ORM 正确检测 JSON 变化。"""
    selected, rest = split(normalize(lot.total_units, lot.available_ranges), amount)
    lot.available_ranges = rest
    return selected, cost(lot, selected)


def put(lot, values):
    """无效来源只恢复到待撤销区间，绝不返回可用余额。"""
    field = "available_ranges" if lot.active else "void_ranges"
    setattr(lot, field, normalize(lot.total_units, getattr(lot, field) + values))


def remove_exact(values, target):
    """从可用区间移除已知偿还区间，拒绝部分重叠或重复扣除。"""
    available = normalize(max((max(end for _, end in values), max(end for _, end in target)), default=0), values)
    wanted = normalize(max((end for _, end in target), default=0), target)
    result = []
    for start, end in available:
        cursor = start
        for left, right in wanted:
            if right <= cursor or left >= end:
                continue
            if left > cursor:
                result.append([cursor, min(left, end)])
            if right > end:
                raise ValueError("偿还区间不在可用来源中，操作已回滚")
            cursor = max(cursor, right)
        if cursor < end:
            result.append([cursor, end])
    if units(available) - units(normalize(max((max(end for _, end in result), 0), default=0), result)) != units(wanted):
        raise ValueError("偿还区间已被重复返还，操作已回滚")
    return result

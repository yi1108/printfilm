"""Aspect ratios shared by writing context and the actual media request."""


def media_ratio(kind, value=None):
    ratio = str(value or '').strip()
    return ratio if ratio and ratio != 'auto' else '16:9' if kind == 'video' else '2:3'

"""分集生成：按 id 筛选分镜。"""

from types import SimpleNamespace

from app.services.drama.access import match_fragments_for_generate


def test_match_all_when_ids_omitted():
    # 未指定 id 时生成全部
    frags = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    assert match_fragments_for_generate(frags, None) == frags
    assert match_fragments_for_generate(frags, []) == frags


def test_match_subset_by_id():
    frags = [SimpleNamespace(id=10), SimpleNamespace(id=11), SimpleNamespace(id=12)]
    got = match_fragments_for_generate(frags, [12, 10])
    assert [f.id for f in got] == [10, 12]


def test_stale_ids_match_nothing():
    # 保存重建后旧 id 对不上
    frags = [SimpleNamespace(id=20), SimpleNamespace(id=21)]
    assert match_fragments_for_generate(frags, [1, 2]) == []

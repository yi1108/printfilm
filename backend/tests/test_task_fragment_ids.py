"""分镜 id 解析与作废原因文案。"""

from types import SimpleNamespace

from app.services.tasks.service import stale_pending_fragment_video_reason, task_fragment_ids


def test_task_fragment_ids_from_column_and_payload():
    task = SimpleNamespace(
        fragment_id=12,
        payload={"fragment_ids": [12, 15, "16", "x"]},
    )
    assert task_fragment_ids(task) == [12, 15, 16]


def test_task_fragment_ids_payload_only():
    task = SimpleNamespace(fragment_id=None, payload={"fragment_ids": [99]})
    assert task_fragment_ids(task) == [99]


def test_stale_reason_deleted_message():
    assert stale_pending_fragment_video_reason([]) == "分镜已变更，请重新生成"

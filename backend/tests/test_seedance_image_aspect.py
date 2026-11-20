"""Seedance 参考图宽高比钳制单测。"""

from pathlib import Path

from app.services.seedance_image_aspect import read_image_size, target_canvas_for_seedance_ar


def test_reads_style_board_with_jpeg_content_and_png_extension():
    board = Path(__file__).resolve().parents[1] / "static/drama/image-styles/wuxia-realistic-photo.png"
    assert read_image_size(board) == (2560, 1440)


def test_target_canvas_ok_16_9():
    assert target_canvas_for_seedance_ar(1672, 941) is None


def test_target_canvas_ok_square():
    assert target_canvas_for_seedance_ar(1024, 1024) is None


def test_target_canvas_pads_overwide_like_shot5():
    # 线上 #404 第 5 镜：1983×793 ≈ 2.5006，Seedance 报 2.50 拒绝
    canvas = target_canvas_for_seedance_ar(1983, 793)
    assert canvas is not None
    cw, ch = canvas
    assert cw >= 1983
    assert ch > 793
    assert 0.41 <= cw / ch <= 2.49


def test_target_canvas_pads_too_tall():
    canvas = target_canvas_for_seedance_ar(400, 1200)  # ar≈0.333
    assert canvas is not None
    cw, ch = canvas
    assert cw > 400
    assert ch >= 1200
    assert 0.41 <= cw / ch <= 2.49


def test_target_canvas_boundary_exactly_2_5_gets_padded():
    # 5:2 = 2.5 恰好踩上限，也钳到安全区
    canvas = target_canvas_for_seedance_ar(2500, 1000)
    assert canvas is not None
    cw, ch = canvas
    assert 0.41 <= cw / ch <= 2.49


def test_target_canvas_even_align_stays_safe():
    # 偶数字对齐不得把 AR 推回 2.50
    canvas = target_canvas_for_seedance_ar(249, 99)
    assert canvas is not None
    cw, ch = canvas
    assert cw % 2 == 0 and ch % 2 == 0
    assert 0.41 <= cw / ch <= 2.49

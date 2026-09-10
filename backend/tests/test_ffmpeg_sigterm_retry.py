"""FFmpeg SIGTERM 识别与成片自动重试相关。"""

from app.services.ffmpeg_compose import (
    FFMPEG_INTERRUPTED_MSG,
    FfmpegInterrupted,
    is_ffmpeg_interrupted_error,
)


def test_is_ffmpeg_interrupted_detects_signal_15_log():
    log = (
        "[libx264 @ 0x] kb/s:795.87\n"
        "[aac @ 0x] Qavg: 709.430\n"
        "Exiting normally, received signal 15.\n"
    )
    assert is_ffmpeg_interrupted_error(log)
    assert is_ffmpeg_interrupted_error(FfmpegInterrupted(FFMPEG_INTERRUPTED_MSG))
    assert not is_ffmpeg_interrupted_error("Conversion failed!")

"""Local shot detection and bounded frame/clip exports for Studio nodes."""
import json
import re
from pathlib import Path

from app.config import get_settings
from app.printfilm_studio.integration.media_edit import command


def shot_boundaries(samples, duration, detector='adaptive', threshold=.28, minimum=.6):
    """Reject flicker/short tails; adaptive scoring compares neighbouring frames."""
    cuts = [0.0]
    for index, (time, score) in enumerate(samples):
        if time - cuts[-1] < minimum or duration - time < minimum:
            continue
        neighbours = [value for _, value in samples[max(0, index - 8):index] + samples[index + 1:index + 9]]
        baseline = sum(neighbours) / len(neighbours) if neighbours else 0
        accepted = score >= threshold if detector == 'content' else score >= .08 and score >= max(.02, baseline) * threshold
        if accepted:
            cuts.append(round(time, 4))
    return cuts + [duration]


async def analyze_frames(source: Path, folder: Path, detector, threshold, minimum, frames, clips, audio, disconnected=None):
    settings = get_settings()
    probe = json.loads(await command([settings.ffprobe_path, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_format', '-show_streams', '-of', 'json', str(source)], disconnected))
    duration = float((probe.get('format') or {}).get('duration') or 0)
    streams = probe.get('streams', [])
    if not any(s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic') for s in streams):
        raise ValueError('逐帧拉片需要包含视频轨道的文件')
    if not 0 < duration <= 600:
        raise ValueError('请选择时长不超过 10 分钟的视频')
    has_audio = any(s.get('codec_type') == 'audio' for s in streams)
    # Decode all source frames, but score a small image. metadata goes to stdout.
    raw = await command([settings.ffmpeg_path, '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-i', str(source), '-threads', '2', '-an', '-vf', "scale=160:-2,select='gte(scene,0)',metadata=print:file=-", '-f', 'null', '-'], disconnected)
    samples = [(float(t), float(s)) for t, s in re.findall(rb'pts_time:([\d.]+)\s+lavfi.scene_score=([\d.]+)', raw)]
    if not samples:
        raise ValueError('视频未能解码出可分析的画面')
    cuts = shot_boundaries(samples, duration, detector, threshold, minimum)
    if len(cuts) > 201:
        raise ValueError('检测超过 200 个镜头，请提高阈值或最短镜头时长')
    shots, outputs = [], []
    total_size = 0

    async def render(name, mime, flags, offset=0):
        nonlocal total_size
        path = folder / name
        await command([settings.ffmpeg_path, '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-ss', str(offset), '-i', str(source), '-threads', '2', *flags, str(path)], disconnected)
        size = path.stat().st_size
        total_size += size
        if not size or size > 100 * 1024 * 1024 or total_size > 300 * 1024 * 1024:
            raise ValueError('分析结果过大，请缩短视频或关闭动态片段导出')
        outputs.append((path, mime))
        return len(outputs) - 1

    for index, (start, end) in enumerate(zip(cuts, cuts[1:])):
        shot = {'index': index + 1, 'start': start, 'end': end, 'duration': round(end - start, 4)}
        if frames:
            shot['frame_index'] = await render(f'分镜{index + 1:03d}_{start:.2f}s.png', 'image/png', ['-map', '0:v:0', '-frames:v', '1'], (start + end) / 2)
        if clips:
            shot['clip_index'] = await render(f'镜头{index + 1:03d}_{start:.2f}-{end:.2f}s.mp4', 'video/mp4', ['-t', str(end - start), '-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264', '-preset', 'fast', '-crf', '21', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart'], start)
        shots.append(shot)
    audio_index = await render('完整原音轨.m4a', 'audio/mp4', ['-map', '0:a:0', '-vn', '-c:a', 'aac']) if audio and has_audio else None
    return {'version': 1, 'duration': duration, 'detector': detector, 'threshold': threshold, 'minimum': minimum, 'shots': shots, 'audio_index': audio_index, 'has_audio': has_audio}, outputs

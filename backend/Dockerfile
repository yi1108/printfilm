# PRINTFILM API：FastAPI + FFmpeg，任务运行时随进程启动
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 成片合成需要 FFmpeg；中文烧录字幕需要文泉驿字体
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY static ./static

RUN mkdir -p /app/static/generated /app/static/voice_previews

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=8 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

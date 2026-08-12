# StreamVerse backend image.
#
# Shared by the `backend` (ASGI), `celery-worker`, `celery-beat` and `flower`
# services. FFmpeg is a *system* dependency here, not a Python package: the
# transcoding pipeline shells out to `ffmpeg`/`ffprobe` directly.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg      -> transcoding + thumbnail generation (Section 5)
# libmagic1   -> python-magic MIME sniffing of uploads
# postgresql-client -> pg_isready during entrypoint wait
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libmagic1 \
        postgresql-client \
        curl \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app/

RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /data/uploads /data/work /app/staticfiles

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["asgi"]

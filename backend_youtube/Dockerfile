FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# yt-dlp / ffmpeg for media acquisition + validation
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg yt-dlp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

HEALTHCHECK --interval=30s --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/youtube-fb/health').read()" || exit 1

CMD ["sh", "-c", "if [ -n \"$DATABASE_URL\" ]; then alembic upgrade head; fi && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

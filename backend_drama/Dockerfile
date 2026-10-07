FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/backend_drama

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# rsvg-convert for deterministic SVG template rasterization (ffmpeg SVG
# support is not relied upon). Verify with `rsvg-convert --version`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends librsvg2-bin \
    && rm -rf /var/lib/apt/lists/* \
    && rsvg-convert --version

COPY app ./app

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

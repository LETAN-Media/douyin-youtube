FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg for probe/extract/render + nodejs for the JianYing ASR bridge.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl nodejs npm \
    fonts-dejavu-core fonts-noto-cjk-extra \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend_audio
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY assets/jianying/package.json assets/jianying/transcribe.mjs ./assets/jianying/
# No '|| true' anywhere: install or bridge failures must fail the image build.
RUN cd assets/jianying && npm install --omit=dev
RUN cd assets/jianying && node --check transcribe.mjs \
 && test -d node_modules/jianying-subtitle
# Bridge boots and reports usage (exit 1) without args; any other exit fails.
RUN cd assets/jianying && node transcribe.mjs >/dev/null 2>&1; code=$?; [ "$code" -eq 1 ]

COPY app ./app

ENV APP_ENV=production \
    PORT=8080 \
    AUDIO_WORKDIR=/tmp/backend-audio/jobs \
    JIANYING_BRIDGE_DIR=/srv/backend_audio/assets/jianying

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]

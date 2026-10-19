FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y \
       --no-install-recommends \
       ffmpeg \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Playwright Chromium dependencies for headless Douyin profile scans.
RUN apt-get update \
    && apt-get install -y \
       --no-install-recommends \
       libnss3 \
       libnspr4 \
       libatk1.0-0 \
       libatk-bridge2.0-0 \
       libcups2 \
       libdrm2 \
       libxkbcommon0 \
       libxcomposite1 \
       libxdamage1 \
       libxfixes3 \
       libxrandr2 \
       libgbm1 \
       libpango-1.0-0 \
       libcairo2 \
       libasound2 \
       libatspi2.0-0 \
       libx11-6 \
       libxcb1 \
       libxext6 \
       libxi6 \
       libxtst6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install \
    --no-cache-dir \
    -r requirements.txt

# Pre-install Chromium at image build time (never per request).
RUN python -m playwright install --with-deps chromium || python -m playwright install chromium

COPY app ./app

COPY prompts ./prompts

# --proxy-headers: trust the platform reverse proxy (Northflank) so
# X-Forwarded-Proto=https is honoured platform-wide. OAuth itself no longer
# depends on this (authorization_response is rebuilt on PUBLIC_BASE_URL).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

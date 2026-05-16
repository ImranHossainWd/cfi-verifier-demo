# California Fruit Inc. - AI Sorting Quality Verifier
# Demo-ready image: Tesseract + Poppler bundled so the verifier can render
# and OCR PDFs without any extra setup at runtime.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps for Tesseract + Poppler + Pillow image libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr poppler-utils \
        libjpeg62-turbo libpng16-16 zlib1g \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for cache reuse
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code + engine
COPY app/    /app/app/
COPY engine/ /app/engine/
COPY web/    /app/web/
COPY forms_blank/ /app/forms_blank/

# Demo defaults: no auth (single shared Vicky user), no Stripe, local storage.
# Override in the hosting providers env-var UI to switch to clerk + s3 etc.
ENV ENV=prod \
    DEBUG=false \
    STORAGE_BACKEND=local \
    STORAGE_LOCAL_DIR=/app/storage \
    AUTH_PROVIDER=dev \
    VISION_PROVIDER=anthropic \
    STRIPE_ENABLED=false \
    PORT=8000

EXPOSE 8000

# Shell form so $PORT (which Render/Railway/Fly all inject) is expanded at runtime.
# Single worker for 512 MB free tier; bump to 2 on paid plans.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers

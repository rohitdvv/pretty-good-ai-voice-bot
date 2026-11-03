# Proctor — dashboard + REST API (docs/02). Single-image MVP.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PROCTOR_HOST=0.0.0.0 \
    PROCTOR_DB=/data/proctor.db

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code.
COPY . .

# Persist the SQLite DB across restarts (mount a volume at /data in production).
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080

# Honors $PORT when the platform injects one (config.py falls back to 8080).
CMD ["python", "-m", "proctor.server"]

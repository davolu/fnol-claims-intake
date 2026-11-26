# API and worker share this image; the compose/Railway start command picks the role.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY samples/policies.json /app/samples/policies.json
ENV PYTHONUNBUFFERED=1 STORAGE_DIR=/data/uploads PORT=8000 POLICY_SEED_FILE=/app/samples/policies.json
RUN useradd -m fnol && mkdir -p /data/uploads && chown -R fnol /data /app
USER fnol
EXPOSE 8000
# Default role: API (runs migrations first). Worker overrides CMD with `python -m app.worker`.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]

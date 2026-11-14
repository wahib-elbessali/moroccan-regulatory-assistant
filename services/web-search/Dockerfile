FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN pip install --no-cache-dir \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.29" \
    "httpx>=0.27" \
    "pyyaml>=6.0"

# Minimal Python package structure
RUN mkdir -p \
    /app/src/core/contracts \
    /app/src/core/leak \
    /app/src/ingestion \
    /data \
    && touch \
    /app/src/__init__.py \
    /app/src/core/__init__.py \
    /app/src/core/contracts/__init__.py \
    /app/src/core/leak/__init__.py \
    /app/src/ingestion/__init__.py

# Only the shared modules required by web-search
COPY src/core/contracts/errors.py /app/src/core/contracts/errors.py
COPY src/core/leak/fingerprint.py /app/src/core/leak/fingerprint.py
COPY src/ingestion/normalize.py /app/src/ingestion/normalize.py

# Web-search service
COPY services/web-search/app.py /app/app.py
COPY services/web-search/store.py /app/store.py
COPY services/web-search/leak_filter.py /app/leak_filter.py

EXPOSE 8090

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]

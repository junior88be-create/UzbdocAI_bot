FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libgl1/libglib2.0-0 are common PyMuPDF/Pillow runtime deps on slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/storage/uploads /app/storage/processed /app/storage/outputs \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080 8081

CMD ["python", "-m", "app.main"]

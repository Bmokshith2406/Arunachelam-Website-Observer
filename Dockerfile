# Build dependencies in a separate stage, following the reference nanoservice.
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runner

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY . /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN useradd --uid 8888 --create-home appuser && \
    chown -R appuser:appuser /app /opt/venv
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/healthz/live', timeout=4)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]


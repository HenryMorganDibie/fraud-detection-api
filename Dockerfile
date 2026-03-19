# ── Stage 1: test ────────────────────────────────────────────────────────────
FROM python:3.9-slim AS test

ARG API_KEY=dev-key-change-in-production
ENV API_KEY=$API_KEY

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R appuser:appuser /app
USER appuser

RUN python -m pytest tests/ -v

# ── Stage 2: production ──────────────────────────────────────────────────────
FROM python:3.9-slim AS production

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y pytest httpx anyio 2>/dev/null || true

COPY --from=test /app .

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8888

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8888", \
     "--workers", "2", \
     "--timeout-keep-alive", "75"]
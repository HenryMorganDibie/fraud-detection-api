# Fraud Detection API

A production-hardened FastAPI service serving real-time fraud predictions from a pre-trained RandomForestClassifier. The model accepts 30 input features — Time, V1–V28 (PCA-transformed), and Amount — and returns a fraud probability score between 0 and 100.

This repo is a hardened implementation of a fraud scoring API, incorporating production improvements across performance, security, testing, Docker infrastructure, and deployment strategy.

---

## Prerequisites

- Docker Desktop (or Docker Engine + Compose)
- Python 3.9+ (only needed for local development outside Docker)
- A `.env` file — see [Configuration](#configuration)

---

## Project Structure
```
checkout-fraud-api/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI app, lifespan, middleware, auth, endpoints
│   ├── model.py          # Model loading, null guard, predict logic
│   └── schemas.py        # Pydantic request/response models with NaN/Inf validation
├── model/
│   └── mock-request-body.json  # Sample request for testing
│   # fraud-model.joblib — NOT included, train your own (see below)
├── tests/
│   ├── conftest.py       # Shared fixtures, API key config
│   ├── test_api.py       # 15 endpoint tests incl. concurrent p99 benchmark
│   └── test_model.py     # 4 model unit tests
├── .env.example          # Environment variable template
├── Dockerfile            # Multi-stage build (test + production)
├── docker-compose.yml    # API and test services with resource limits
├── requirements.txt
└── README.md
```

---

## Model Setup

The model artifact is not included in this repo. To get started, train a RandomForestClassifier on your own transaction dataset with the same feature schema (Time, V1–V28, Amount) and save it with joblib.

```python
import joblib
from sklearn.ensemble import RandomForestClassifier

# Train your model
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# Save
joblib.dump(model, "model/fraud-model.joblib")
```

---

## Quick Start

**Step 1 — Set up your environment:**
```bash
cp .env.example .env
# Edit .env and set a real API_KEY value
```

**Step 2 — Build and run:**
```bash
docker-compose up --build -d api
```

The API will be available at `http://localhost:8888`.

**Step 3 — Test a prediction:**
```bash
curl -X POST http://localhost:8888/v1/fraud-score \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d @model/mock-request-body.json
```

**Step 4 — Health check:**
```bash
curl http://localhost:8888/health
```

---

## Running Tests

Tests run automatically during the Docker build in the test stage. To run them explicitly:
```bash
# Run full test suite in Docker (recommended)
docker-compose run --rm test

# Or build and run separately
docker-compose up --build -d api
docker-compose run --rm test
```

The test suite includes **19 tests**:
- Happy path, validation errors, edge cases
- Sequential p99 latency benchmark (100 requests)
- Concurrent p99 latency benchmark (20 simultaneous threads)
- NaN/Inf input rejection
- Unauthenticated request rejection (403)
- Unhealthy model state coverage

---

## API Reference

### POST `/v1/fraud-score`

Scores a transaction for fraud probability.

**Authentication**: Requires `X-API-Key` header. Returns `403` if missing or invalid.

**Request body**: JSON object with 30 float features: `Time`, `V1`–`V28`, `Amount`.

- All fields are required
- NaN and Inf values are explicitly rejected with `422`
- Missing or wrong-typed fields return `422`

**Example request:**
```json
{
  "Time": 0,
  "V1": -1.3598,
  "V2": -0.0728,
  "Amount": 149.62
}
```

**Response:**
```json
{
  "fraud-score": 12,
  "is-fraud": false,
  "model-version": "1.0.0"
}
```

| Field | Type | Description |
|---|---|---|
| `fraud-score` | int (0–100) | Fraud probability as a percentage |
| `is-fraud` | bool | True if score >= FRAUD_THRESHOLD (default 50) |
| `model-version` | string | Version of the loaded model |

**Error responses:**
| Status | Reason |
|---|---|
| `403` | Missing or invalid API key |
| `422` | Invalid input — missing field, wrong type, or non-finite float |

---

### GET `/health`

Returns model load status. No authentication required.

**Response:**
```json
{
  "status": "healthy",
  "model_loaded": true
}
```

---

## Configuration

Copy `.env.example` to `.env` and set your values before starting the service.

| Variable | Required | Default | Description |
|---|---|---|---|
| `API_KEY` | ✅ Yes | None — app will not start without this | API key for endpoint authentication |
| `FRAUD_THRESHOLD` | No | `50` | Score threshold for is-fraud flag |
| `MODEL_PATH` | No | `model/fraud-model.joblib` | Path to model artifact |
| `MODEL_VERSION` | No | `1.0.0` | Model version returned in responses |
| `APP_VERSION` | No | `1.0.0` | FastAPI app version |

---

## Performance

The service is designed to stay well under the 200ms p99 latency target:

- **Model loaded once at startup** via FastAPI lifespan — joblib deserialization happens once, zero cost per prediction
- **NumPy array from list** instead of pandas DataFrame — avoids ~0.5ms DataFrame construction overhead per request
- **Synchronous endpoint** — sklearn's `predict_proba` is CPU-bound and holds the GIL, async wrapping adds overhead with no benefit
- **2 uvicorn workers** via `--workers 2` — handles concurrent requests within a single container
- **ALB keep-alive** set to 75 seconds via `--timeout-keep-alive 75` — stays above ALB's 60s idle timeout, prevents intermittent 502s

---

## Security

- **API key authentication** on all prediction endpoints via `X-API-Key` header — protects against model extraction attacks
- **Non-root container user** — runs as `appuser`, not root
- **Joblib model format** — migrated from pickle, eliminating the arbitrary code execution risk of pickle deserialization
- **NaN/Inf rejection** — non-finite float values explicitly rejected before reaching the model
- **No secrets in codebase** — all sensitive config via environment variables, `.env` excluded from version control

---

## Docker

The Dockerfile uses a **multi-stage build**:

**Stage 1 — test:**
- Installs all dependencies including test tools
- Runs the full test suite during `docker build`
- Build fails immediately if any test fails — broken code cannot produce a production image

**Stage 2 — production:**
- Copies application from the test stage
- Strips test dependencies (pytest, httpx, anyio) from the final image
- Runs with 2 workers and ALB-compatible keep-alive timeout
```bash
# Build production image and start
docker-compose up --build -d api

# Run tests explicitly
docker-compose run --rm test
```

---

## Deployment Strategy

### Infrastructure (AWS ECS/Fargate)

- **Compute**: ECS Fargate tasks behind an Application Load Balancer — no EC2 management, pay-per-use
- **Auto-scaling**: Target tracking on CPU utilization (70%) and request count per target — scale between 2–10 tasks with 300s scale-in cooldown to prevent oscillation
- **Load balancing**: ALB with path-based routing — health check on `/health` with 30s interval, 3 unhealthy threshold
- **Networking**: Tasks in private subnets, ALB in public subnets — security groups restrict inbound to ALB only

### CI/CD

- GitHub Actions: lint → test → build Docker image → push to ECR → deploy to ECS
- Blue/green deployment via CodeDeploy — traffic shifts gradually (10% → 50% → 100%) with automatic rollback on failure
- Deployments gated on the full test suite passing including the concurrent p99 latency benchmark
- Image tags include git commit SHA — rollback to any previous tag via ECS task definition update

### Monitoring

- **Latency**: CloudWatch ALB metrics (p50, p95, p99) — alert if p99 > 150ms (warn) or > 200ms (critical)
- **Error rate**: ALB 5xx rate — alert if > 1% over 5 minutes
- **Model drift**: Fraud score distribution logged to CloudWatch — alert if rolling mean shifts > 2 standard deviations from 30-day baseline
- **Infrastructure**: Container Insights for CPU/memory per task — alert on task restart count > 0 in a 10-minute window

### Feature Serving

For production at scale, features should move to a feature store pattern to prevent training/serving skew:

- **Offline store** (S3/Redshift): Batch-computed features for training — daily refresh via Airflow or dbt
- **Online store** (DynamoDB/ElastiCache): Low-latency key-value lookup at inference time — 2–5ms for DynamoDB in the same AWS region — populated by a Kinesis streaming pipeline triggered on transaction events
- **Feature registry**: Canonical feature definitions shared by both offline pipeline and online Lambda — one definition of every feature used for both training and serving, eliminating skew at the source

The current API accepts raw features in the request body. To integrate with a feature store, the endpoint would accept a `transaction_id`, fetch pre-computed features from the online store, and pass them to `predict()` unchanged.

---

## Remaining Improvements

These items are identified but not yet implemented:

- **Batch prediction endpoint**: `POST /v1/fraud-score/batch` for scoring multiple transactions per call using NumPy vectorization
- **Out-of-distribution warning**: Flag inputs with z-score > 3 vs. training distribution with an `ood_warning` field in the response
- **Rate limiting**: Per-client rate limiting via slowapi or AWS WAF to prevent abuse and model extraction
- **Model metadata endpoint**: `GET /v1/model-info` exposing training date, feature importance, and sklearn version
- **ONNX migration**: Replace joblib with ONNX Runtime for 2–5x inference speedup and cross-framework portability
- **Graceful degradation**: Return HTTP 503 with structured error body on model load failure rather than crashing the container
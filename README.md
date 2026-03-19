# Fraud Detection API

FastAPI service serving fraud predictions from a pre-trained RandomForestClassifier.
This is a hardened version of the original service with all production improvements implemented.

## Quick Start
```bash
docker-compose up --build
```

The API will be available at `http://localhost:8888`.

### Test a prediction
```bash
curl -X POST http://localhost:8888/v1/fraud-score \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key-change-in-production" \
  -d @model/mock-request-body.json
```

### Health check
```bash
curl http://localhost:8888/health
```

### Run tests
```bash
# Recommended — runs in the test stage of the multi-stage build
docker-compose run --rm test

# Or build and run separately
docker-compose up --build -d api
docker-compose run --rm test
```

---

## API

### POST `/v1/fraud-score`

**Authentication**: Requires `X-API-Key` header. Returns `403` if missing or invalid.

**Request body**: JSON with 30 float features: `Time`, `V1`–`V28`, `Amount`.
NaN and Inf values are explicitly rejected with `422`.

**Response**:
```json
{
  "fraud-score": 12,
  "is-fraud": false,
  "model-version": "1.0.0"
}
```

- `fraud-score`: 0–100 integer representing fraud probability
- `is-fraud`: true if `fraud-score >= FRAUD_THRESHOLD` (default 50)
- `model-version`: version of the loaded model

### GET `/health`

Returns model load status. No authentication required.
```json
{
  "status": "healthy",
  "model_loaded": true
}
```

---

## Configuration

All runtime configuration is driven by environment variables:

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | `dev-key-change-in-production` | API key for endpoint authentication |
| `FRAUD_THRESHOLD` | `50` | Score threshold for is-fraud classification |
| `MODEL_PATH` | `model/fraud-model.joblib` | Path to the model artifact |
| `MODEL_VERSION` | `1.0.0` | Model version returned in responses |
| `APP_VERSION` | `1.0.0` | FastAPI app version |

Set these in `docker-compose.yml` or pass them as environment variables at runtime.

---

## Performance

The service is designed to stay well under the 200ms p99 latency target:

- **Model loaded once at startup** via FastAPI lifespan. Joblib deserialization happens once at startup — zero cost per prediction.
- **NumPy array from list** instead of pandas DataFrame. Avoids DataFrame construction overhead (~0.5ms per request).
- **Synchronous endpoint**. sklearn's `predict_proba` is CPU-bound and releases the GIL only partially — async wrapping adds overhead with no benefit.
- **2 uvicorn workers** configured explicitly via `--workers 2`, handling concurrent requests within a single container.
- **ALB keep-alive** set to 75 seconds via `--timeout-keep-alive 75` to stay above ALB's 60s idle timeout and prevent intermittent 502s.

The test suite includes both a sequential and a concurrent p99 latency benchmark:
- `test_prediction_latency_p99_sequential` — 100 back-to-back requests, asserts p99 < 200ms
- `test_prediction_latency_p99_concurrent` — 20 simultaneous threads, asserts p99 < 200ms under real concurrency

---

## Security

- **API key authentication** on all prediction endpoints via `X-API-Key` header
- **Non-root container user** — runs as `appuser`, not root
- **Model format** — migrated from pickle to joblib, eliminating the arbitrary code execution risk of pickle deserialization
- **NaN/Inf rejection** — non-finite float values are explicitly rejected before reaching the model

---

## Docker

The Dockerfile uses a **multi-stage build**:

- **Stage 1 (test)**: Installs all dependencies including test tools, runs the full test suite during the build. The build fails if any test fails.
- **Stage 2 (production)**: Copies only the application from the test stage, strips test dependencies from the final image.

This ensures the production image is lean and that tests are always run before a production image is produced.
```bash
# Build production image only
docker-compose up --build -d api

# Run tests explicitly
docker-compose run --rm test
```

---

## Deployment Strategy

### Infrastructure (AWS ECS/Fargate)

- **Compute**: ECS Fargate tasks behind an Application Load Balancer. No EC2 management overhead, pay-per-use.
- **Auto-scaling**: Target tracking on CPU utilization (70%) and request count per target. Scale between 2–10 tasks. Scale-in cooldown of 300 seconds to prevent oscillation.
- **Load balancing**: ALB with path-based routing. Health check on `/health` endpoint with 30s interval, 3 unhealthy threshold.
- **Networking**: Tasks in private subnets, ALB in public subnets. Security groups restrict inbound to ALB only.

### CI/CD

- GitHub Actions pipeline: lint → test → build Docker image → push to ECR → deploy to ECS.
- Blue/green deployment via CodeDeploy. Traffic shifts gradually (10% → 50% → 100%) with automatic rollback on failure.
- Deployments gated on the full test suite passing, including the concurrent p99 latency benchmark.

### Monitoring

- **Latency**: CloudWatch metrics from ALB (p50, p95, p99). Alert if p99 > 150ms (warn) or > 200ms (critical).
- **Error rate**: 4xx/5xx rate from ALB. Alert if 5xx rate exceeds 1% over 5 minutes.
- **Model drift**: Log fraud score distributions to CloudWatch. Alert if rolling mean shifts more than 2 standard deviations from the 30-day baseline.
- **Infrastructure**: Container Insights for per-task CPU/memory. Alert on task restart count > 0 in a 10-minute window.

### Feature Serving

For production at scale, features should move to a feature store pattern:

- **Offline store** (S3/Redshift): Batch-computed features for training. Daily refresh via Airflow or dbt.
- **Online store** (DynamoDB/ElastiCache): Low-latency feature lookup at inference time (2–5ms for DynamoDB in the same region). Populated by a streaming pipeline (Kinesis) triggered on transaction events.
- **Feature registry**: Central catalog of feature definitions shared by both the offline pipeline and online Lambda. Prevents training/serving skew by ensuring both paths use identical feature computation logic.

The current API accepts raw features in the request. To integrate with a feature store, the endpoint would accept a `transaction_id`, fetch pre-computed features from the online store, and run the prediction.

---

## Improvements With More Time

These items are acknowledged but not yet implemented:

- **Batch prediction endpoint**: `POST /v1/fraud-score/batch` for scoring multiple transactions in one call, taking advantage of NumPy vectorization.
- **Out-of-distribution warning**: Flag inputs statistically anomalous vs. training data (z-score > 3) with an `ood_warning` field in the response.
- **Rate limiting**: Per-client rate limiting via slowapi or AWS WAF to protect against abuse and model extraction attacks.
- **Model metadata endpoint**: Expose training date, feature importance, and sklearn version at `GET /v1/model-info`.
- **ONNX migration**: Replace joblib with ONNX Runtime for a 2–5x inference speedup and cross-framework compatibility.
- **Graceful degradation**: Return HTTP 503 with a structured error body if the model fails to load, rather than crashing the container.
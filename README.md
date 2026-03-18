# Fraud Detection API

FastAPI service serving fraud predictions from a pre-trained RandomForestClassifier.

## Quick Start

```bash
docker-compose up --build
```

The API will be available at `http://localhost:8888`.

### Test a prediction

```bash
curl -X POST http://localhost:8888/fraud-score \
  -H "Content-Type: application/json" \
  -d @model/mock-request-body.json
```

### Health check

```bash
curl http://localhost:8888/health
```

## API

### POST `/fraud-score`

**Request body**: JSON with 30 float features: `Time`, `V1`-`V28`, `Amount`.

**Response**:
```json
{
  "fraud-score": 12,
  "is-fraud": false,
  "model-version": "1.0.0"
}
```

- `fraud-score`: 0-100 integer representing fraud probability
- `is-fraud`: true if `fraud-score >= 50`
- `model-version`: version of the loaded model

### GET `/health`

Returns model load status.

## Performance

The service is designed to stay well under the 200ms p99 latency target:

- **Model loaded once at startup** via FastAPI lifespan, not per-request. RandomForest pickle deserialization takes ~100ms at startup but zero cost per prediction.
- **NumPy array from list** instead of pandas DataFrame. Avoids DataFrame construction overhead (~0.5ms per request).
- **Synchronous endpoint**. sklearn's `predict_proba` is CPU-bound and releases the GIL only partially, so async wrapping would add overhead without benefit.
- **Single worker, horizontal scaling**. Rather than running multiple uvicorn workers (which duplicates the ~50MB model in memory per worker), scaling is handled at the container level via ECS task count.

The test suite includes a p99 latency benchmark (`test_prediction_latency_p99`) that runs 100 sequential requests and asserts p99 < 200ms.

## Running Tests

```bash
# Locally (requires Python 3.9 + scikit-learn==1.0.2)
pip install -r requirements.txt
pytest tests/

# In Docker (recommended)
docker-compose run --rm api pytest tests/ -v
```

## Deployment Strategy

### Infrastructure (AWS ECS/Fargate)

- **Compute**: ECS Fargate tasks behind an Application Load Balancer. No EC2 management overhead, pay-per-use.
- **Auto-scaling**: Target tracking on CPU utilization (70%) and request count per target. Scale between 2-10 tasks for the prediction service.
- **Load balancing**: ALB with path-based routing. Health check on `/health` endpoint with 10s interval, 3 unhealthy threshold.
- **Networking**: Tasks in private subnets, ALB in public subnets. Security groups restrict inbound to ALB only.

### CI/CD

- GitHub Actions pipeline: lint, test, build Docker image, push to ECR, deploy to ECS.
- Blue/green deployment via CodeDeploy integration to avoid downtime during model updates.

### Monitoring

- **Latency**: CloudWatch metrics from ALB (p50, p95, p99 target tracking). Alert if p99 > 200ms.
- **Error rate**: 4xx/5xx rate from ALB metrics. Alert if error rate > 1% over 5 minutes.
- **Model performance**: Log prediction scores to CloudWatch. Track score distribution drift over time. Set up weekly batch evaluation against labeled data.
- **Infrastructure**: CPU/memory utilization per task, task health, container restarts.

### Feature Serving

For production at scale, features should move to a feature store pattern:

- **Offline store** (S3/Redshift): Batch-computed features for training. Daily refresh via Airflow.
- **Online store** (DynamoDB/ElastiCache): Low-latency feature lookup at inference time. Populated by streaming pipeline (Kinesis) or batch sync.
- **Feature registry**: Central catalog of feature definitions, owners, and lineage. Prevents training/serving skew by using the same transformation logic for both paths.

The current API accepts raw features in the request. To integrate with a feature store, the endpoint would accept a transaction ID, fetch pre-computed features from the online store, and run the prediction.

## Improvements With More Time

- **Model format**: Replace pickle with ONNX or joblib for safer serialization and cross-version compatibility. Pickle is fragile across sklearn versions.
- **Input validation**: Add range checks or distribution-based validation on feature values (e.g. flag inputs that are statistical outliers vs. training data).
- **Batch prediction endpoint**: Add a POST `/fraud-score/batch` for scoring multiple transactions in one call, taking advantage of numpy vectorization.
- **Structured JSON logging**: Switch from plaintext to JSON logs for better parsing in CloudWatch/ELK.
- **Graceful degradation**: Return a cached/default response if the model fails to load, rather than crashing the container.
- **Rate limiting**: Add per-client rate limiting to protect against abuse.
- **API versioning**: Prefix routes with `/v1/` to allow non-breaking model and schema updates.
- **Load testing**: Add a proper load test suite (e.g. Locust) to validate p99 under sustained concurrency, not just sequential requests.
- **Model metadata endpoint**: Expose model training date, feature importance, and sklearn version at `/model-info`.
- **Configuration management**: Move thresholds, model path, and port to environment variables or a config file instead of hardcoded values.

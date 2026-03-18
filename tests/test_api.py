import time
import threading
import math
import statistics


def test_fraud_score_valid(client, valid_payload):
    resp = client.post("/v1/fraud-score", json=valid_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "fraud-score" in data
    assert "is-fraud" in data
    assert "model-version" in data
    assert 0 <= data["fraud-score"] <= 100
    assert isinstance(data["is-fraud"], bool)
    assert data["is-fraud"] == (data["fraud-score"] >= 50)


def test_fraud_score_missing_field(client, valid_payload):
    del valid_payload["Amount"]
    resp = client.post("/v1/fraud-score", json=valid_payload)
    assert resp.status_code == 422


def test_fraud_score_wrong_type(client, valid_payload):
    valid_payload["Amount"] = "not_a_number"
    resp = client.post("/v1/fraud-score", json=valid_payload)
    assert resp.status_code == 422


def test_fraud_score_empty_body(client):
    resp = client.post("/v1/fraud-score", json={})
    assert resp.status_code == 422


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["model_loaded"] is True


def test_response_has_request_id(client, valid_payload):
    resp = client.post("/v1/fraud-score", json=valid_payload)
    assert "x-request-id" in resp.headers
    assert "x-response-time-ms" in resp.headers


def test_custom_request_id(client, valid_payload):
    resp = client.post("/v1/fraud-score", json=valid_payload,
                       headers={"X-Request-ID": "test-123"})
    assert resp.headers["x-request-id"] == "test-123"


def test_prediction_latency_p99_sequential(client, valid_payload):
    """Sequential p99 baseline — single client, no concurrency."""
    latencies = []
    for _ in range(100):
        start = time.perf_counter()
        resp = client.post("/v1/fraud-score", json=valid_payload)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        latencies.append(elapsed_ms)
    p99 = sorted(latencies)[98]
    assert p99 < 200, f"Sequential p99 {p99:.1f}ms exceeds 200ms target"


def test_prediction_latency_p99_concurrent(client, valid_payload):
    """Concurrent p99 — 20 simultaneous clients, reflects real production load."""
    latencies = []
    lock = threading.Lock()
    errors = []

    def fire():
        try:
            start = time.perf_counter()
            resp = client.post("/v1/fraud-score", json=valid_payload)
            elapsed_ms = (time.perf_counter() - start) * 1000
            with lock:
                latencies.append(elapsed_ms)
                if resp.status_code != 200:
                    errors.append(resp.status_code)
        except Exception as e:
            with lock:
                errors.append(str(e))

    threads = [threading.Thread(target=fire) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent test: {errors}"
    assert len(latencies) == 20
    p99 = sorted(latencies)[18]
    assert p99 < 200, f"Concurrent p99 {p99:.1f}ms exceeds 200ms target"


def test_fraud_score_nan_rejected(client, valid_payload):
    """NaN values should be rejected with 422."""
    valid_payload["Amount"] = float("nan")
    resp = client.post("/v1/fraud-score", json=valid_payload)
    assert resp.status_code == 422


def test_fraud_score_inf_rejected(client, valid_payload):
    """Inf values should be rejected with 422."""
    valid_payload["Amount"] = float("inf")
    resp = client.post("/v1/fraud-score", json=valid_payload)
    assert resp.status_code == 422


def test_fraud_score_extreme_values(client):
    """Test with extreme float values to check model stability."""
    payload = {"Time": 1e8, "Amount": 1e6}
    for i in range(1, 29):
        payload[f"V{i}"] = (-1) ** i * 100.0
    resp = client.post("/v1/fraud-score", json=payload)
    assert resp.status_code == 200
    assert 0 <= resp.json()["fraud-score"] <= 100


def test_fraud_score_all_zeros(client):
    """Test with all-zero features."""
    payload = {"Time": 0.0, "Amount": 0.0}
    for i in range(1, 29):
        payload[f"V{i}"] = 0.0
    resp = client.post("/v1/fraud-score", json=payload)
    assert resp.status_code == 200
    assert 0 <= resp.json()["fraud-score"] <= 100


def test_fraud_score_negative_amount(client, valid_payload):
    """Negative amounts are valid floats - model should handle them."""
    valid_payload["Amount"] = -50.0
    resp = client.post("/v1/fraud-score", json=valid_payload)
    assert resp.status_code == 200
    assert 0 <= resp.json()["fraud-score"] <= 100


def test_health_unhealthy(monkeypatch):
    """Health endpoint returns unhealthy when model is not loaded."""
    from fastapi.testclient import TestClient
    import app.model as model_module
    import app.main as main_module

    monkeypatch.setattr(model_module, "_model", None)
    client = TestClient(main_module.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["model_loaded"] is False
import pytest
from app.model import load_model, get_model, predict, MODEL_PATH


@pytest.fixture(autouse=True)
def _load():
    load_model()


def test_model_loads():
    assert get_model() is not None


def test_model_has_predict_proba():
    assert hasattr(get_model(), "predict_proba")


def test_predict_returns_valid_score():
    features = [0.0] * 30
    result = predict(features)
    assert 0 <= result["fraud-score"] <= 100
    assert isinstance(result["is-fraud"], bool)
    assert result["model-version"] == "1.0.0"


def test_predict_consistency():
    features = [0.0] * 30
    r1 = predict(features)
    r2 = predict(features)
    assert r1["fraud-score"] == r2["fraud-score"]

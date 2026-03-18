import pickle
import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent.parent / "model" / "fraud-model.pickle"
FRAUD_THRESHOLD = 50

_model: Optional[RandomForestClassifier] = None


def load_model(path: Path = MODEL_PATH) -> None:
    global _model
    with open(path, "rb") as f:
        _model = pickle.load(f)
    logger.info("Model loaded from %s", path)


def get_model() -> Optional[RandomForestClassifier]:
    return _model


def predict(features: list[float]) -> dict[str, Any]:
    arr = np.array(features).reshape(1, -1)
    proba = _model.predict_proba(arr)[0]
    fraud_probability = float(proba[1]) * 100
    score = int(round(fraud_probability))
    score = max(0, min(100, score))
    return {
        "fraud-score": score,
        "is-fraud": score >= FRAUD_THRESHOLD,
        "model-version": "1.0.0",
    }

import os
import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger(__name__)

# ── Config from environment variables ────────────────────────────────────────
MODEL_PATH = Path(os.getenv("MODEL_PATH", str(Path(__file__).parent.parent / "model" / "fraud-model.joblib")))
FRAUD_THRESHOLD = int(os.getenv("FRAUD_THRESHOLD", "50"))
MODEL_VERSION = os.getenv("MODEL_VERSION", "1.0.0")

_model: Optional[RandomForestClassifier] = None


def load_model(path: Path = MODEL_PATH) -> None:
    global _model
    try:
        _model = joblib.load(path)
        logger.info("Model loaded from %s", path)
    except FileNotFoundError:
        raise RuntimeError(f"Model file not found at {path}. Check MODEL_PATH environment variable.")
    except Exception as e:
        raise RuntimeError(f"Failed to load model from {path}: {e}")


def get_model() -> Optional[RandomForestClassifier]:
    return _model


def predict(features: list[float]) -> dict[str, Any]:
    # ── Null guard ────────────────────────────────────────────────────────────
    if _model is None:
        raise RuntimeError("Model is not loaded. Check startup logs.")

    arr = np.array(features).reshape(1, -1)
    proba = _model.predict_proba(arr)[0]
    fraud_probability = float(proba[1]) * 100
    score = int(round(fraud_probability))
    score = max(0, min(100, score))
    return {
        "fraud-score": score,
        "is-fraud": score >= FRAUD_THRESHOLD,
        "model-version": MODEL_VERSION,
    }
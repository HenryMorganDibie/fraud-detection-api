import math
from pydantic import BaseModel, Field, field_validator


FEATURE_NAMES = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount"]


class FraudRequest(BaseModel):
    Time: float
    V1: float
    V2: float
    V3: float
    V4: float
    V5: float
    V6: float
    V7: float
    V8: float
    V9: float
    V10: float
    V11: float
    V12: float
    V13: float
    V14: float
    V15: float
    V16: float
    V17: float
    V18: float
    V19: float
    V20: float
    V21: float
    V22: float
    V23: float
    V24: float
    V25: float
    V26: float
    V27: float
    V28: float
    Amount: float

    # ── NaN / Inf validator ───────────────────────────────────────────────────
    @field_validator("*", mode="before")
    @classmethod
    def reject_non_finite(cls, v):
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"Non-finite float value not allowed: {v}")
        return v

    def to_feature_list(self) -> list[float]:
        return [getattr(self, name) for name in FEATURE_NAMES]


class FraudResponse(BaseModel):
    fraud_score: int = Field(..., alias="fraud-score", ge=0, le=100)
    is_fraud: bool = Field(..., alias="is-fraud")
    model_version: str = Field(..., alias="model-version")

    model_config = {"populate_by_name": True, "protected_namespaces": ()}
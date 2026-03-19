import time
import uuid
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Security, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import APIKeyHeader

from app.model import load_model, get_model, predict
from app.schemas import FraudRequest, FraudResponse

# ── Structured JSON logging ──────────────────────────────────────────────────
try:
    from pythonjsonlogger import jsonlogger
    handler = logging.StreamHandler()
    handler.setFormatter(jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("API_KEY environment variable is not set. See .env.example.")

# ── API key auth ─────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key. Provide a valid X-API-Key header.",
        )
    return api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="Fraud Detection API", version=APP_VERSION, lifespan=lifespan)


# ── Custom validation error handler (handles NaN/Inf serialization) ──────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "Request validation failed — check for invalid or non-finite float values."},
    )


@app.middleware("http")
async def add_request_metadata(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    logger.info("request completed", extra={
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "time_ms": round(elapsed_ms, 1),
    })
    return response


# ── Endpoints ────────────────────────────────────────────────────────────────
@app.post("/v1/fraud-score", response_model=FraudResponse, dependencies=[Depends(verify_api_key)])
def fraud_score(request: FraudRequest) -> dict:
    return predict(request.to_feature_list())


@app.get("/health")
def health() -> dict[str, object]:
    model_loaded = get_model() is not None
    status = "healthy" if model_loaded else "unhealthy"
    return {"status": status, "model_loaded": model_loaded}
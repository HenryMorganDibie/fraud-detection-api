import time
import uuid
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.model import load_model, get_model, predict
from app.schemas import FraudRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="Fraud Detection API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_request_metadata(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    logger.info("request_id=%s method=%s path=%s status=%s time_ms=%.1f",
                request_id, request.method, request.url.path,
                response.status_code, elapsed_ms)
    return response


@app.post("/fraud-score")
def fraud_score(request: FraudRequest) -> JSONResponse:
    result = predict(request.to_feature_list())
    return JSONResponse(content=result)


@app.get("/health")
def health() -> dict[str, object]:
    model_loaded = get_model() is not None
    status = "healthy" if model_loaded else "unhealthy"
    return {"status": status, "model_loaded": model_loaded}

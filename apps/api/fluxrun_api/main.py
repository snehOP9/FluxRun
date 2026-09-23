import json
import logging
import re
import time
import uuid
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.exc import IntegrityError
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from .config import get_settings
from .routers import auth, projects, workspaces, tracking, artifacts, administration
from .routers import registry, traces, evaluations, reviews

settings = get_settings()
logger = logging.getLogger("fluxrun")
logging.basicConfig(level=logging.INFO, format="%(message)s")
REQUESTS = Counter("fluxrun_http_requests", "API requests", ["method", "route", "status"])
LATENCY = Histogram("fluxrun_http_seconds", "API latency", ["route"])
app = FastAPI(title="FluxRun API", version="0.4.0", openapi_url="/api/v1/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-Request-ID", "Authorization", "Idempotency-Key"])


def failure(request, status, code, message, details=None):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "request_id": getattr(request.state, "request_id", "unknown"), "details": details or {}}})


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request.state.request_id = supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", supplied) else f"req_{uuid.uuid4().hex}"
        start = time.perf_counter()
        try:
            if request.method in {"POST", "PUT", "PATCH"} and not request.url.path.endswith("/content"):
                size = 0
                chunks = []
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > settings.max_request_bytes:
                        return failure(request, 413, "PAYLOAD_TOO_LARGE", "Request exceeds the configured limit")
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            response = await call_next(request)
        except Exception as exc:
            logger.error(json.dumps({"event": "request_failed", "request_id": request.state.request_id, "error_class": type(exc).__name__}))
            response = failure(request, 500, "INTERNAL_ERROR", "An unexpected error occurred; use the request ID to inspect server logs")
        response.headers.update({"X-Request-ID": request.state.request_id, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "Cache-Control": "no-store"})
        route = getattr(request.scope.get("route"), "path", "unmatched")
        duration = time.perf_counter() - start
        REQUESTS.labels(request.method, route, response.status_code).inc()
        LATENCY.labels(route).observe(duration)
        logger.info(json.dumps({"event": "request", "request_id": request.state.request_id, "route": route, "status": response.status_code, "duration_ms": round(duration * 1000, 2)}))
        return response


app.add_middleware(RequestContextMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = [{"location": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
    return failure(request, 422, "VALIDATION_ERROR", "One or more fields are invalid", details)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    codes = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 422: "VALIDATION_ERROR", 429: "RATE_LIMITED", 503: "SERVICE_UNAVAILABLE"}
    return failure(request, exc.status_code, codes.get(exc.status_code, "REQUEST_REJECTED"), str(exc.detail))


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, exc: IntegrityError):
    return failure(request, 409, "CONFLICT", "This resource already exists or changed concurrently. Refresh and retry.")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "fluxrun-api", "version": "0.4.0"}


@app.get("/metrics", include_in_schema=False)
def platform_metrics():
    if not settings.metrics_enabled:
        raise HTTPException(404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


for router in (auth.router, workspaces.router, projects.router, tracking.router, artifacts.router, administration.router, registry.router, traces.router, evaluations.router, reviews.router):
    app.include_router(router)

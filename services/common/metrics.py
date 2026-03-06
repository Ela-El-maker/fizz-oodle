from __future__ import annotations

import re
import time
from typing import Any

from fastapi import FastAPI, Response
try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, REGISTRY, generate_latest
    _PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover - fallback for minimal dev envs
    _PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _NoOpCollector:
        def labels(self, **_kwargs):
            return self

        def inc(self, *_args, **_kwargs):
            return None

        def observe(self, *_args, **_kwargs):
            return None

    class _NoOpRegistry:
        _names_to_collectors: dict[str, Any] = {}

    REGISTRY = _NoOpRegistry()

    def Counter(*_args, **_kwargs):  # type: ignore[misc]
        return _NoOpCollector()

    def Histogram(*_args, **_kwargs):  # type: ignore[misc]
        return _NoOpCollector()

    def generate_latest(*_args, **_kwargs):  # type: ignore[misc]
        return b""


def _get_or_create_counter(name: str, documentation: str, labelnames: tuple[str, ...]) -> Counter:
    if not _PROMETHEUS_AVAILABLE:
        return Counter()  # type: ignore[return-value]
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if isinstance(existing, Counter):
        return existing
    return Counter(name, documentation, labelnames=labelnames)


def _get_or_create_histogram(name: str, documentation: str, labelnames: tuple[str, ...]) -> Histogram:
    if not _PROMETHEUS_AVAILABLE:
        return Histogram()  # type: ignore[return-value]
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if isinstance(existing, Histogram):
        return existing
    return Histogram(name, documentation, labelnames=labelnames)


def setup_metrics(app: FastAPI, service_name: str) -> dict[str, Any]:
    request_count = _get_or_create_counter(
        "http_requests_total",
        "Total HTTP requests by service/method/path/status.",
        ("service", "method", "path", "status"),
    )
    request_latency = _get_or_create_histogram(
        "http_request_duration_seconds",
        "HTTP request duration seconds by service/method/path.",
        ("service", "method", "path"),
    )

    _UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
    _NUM_RE = re.compile(r"/\d+(?=/|$)")

    def _normalize_path(raw: str) -> str:
        path = _UUID_RE.sub("{id}", raw)
        path = _NUM_RE.sub("/{id}", path)
        return path

    @app.middleware("http")
    async def metrics_middleware(request, call_next):  # type: ignore[no-untyped-def]
        path = _normalize_path(request.url.path)
        method = request.method
        start = time.perf_counter()
        status_code = "500"
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - start
            request_count.labels(service=service_name, method=method, path=path, status=status_code).inc()
            request_latency.labels(service=service_name, method=method, path=path).observe(elapsed)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return {
        "request_count": request_count,
        "request_latency": request_latency,
    }

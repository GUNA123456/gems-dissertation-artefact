"""obs.py — shared observability for every StyleHub service (Phase 1 of the v2 rebuild).

Canonical copy lives in src/common/; each service directory holds an identical copy
(synced by sync_shared.sh) because every Dockerfile builds from its own directory only.

Round 1's telemetry had two structural gaps this module closes:

  1. No service exposed its own metrics — all latency came from an external prober, so
     per-service request rates, error rates and latency distributions did not exist.
     Here every service serves /metrics for Prometheus to scrape directly.

  2. No error metric existed anywhere, so error cascades were unmeasurable even after
     the error-propagation rewrite. service_dependency_errors_total closes that.

It also carries the dependency-edge counting that used to live in depgraph.py (same
metric name, service_dependency_calls_total, so discover_topology.py keeps working),
and optional OpenTelemetry tracing, enabled ONLY when OTEL_EXPORTER_OTLP_ENDPOINT is
set — images run identically on a cluster with no collector.

Usage (one line after `app = FastAPI(...)`):

    import obs
    obs.install(app, "stylehub-cart-service", dependencies={"redis": REDIS_HOST})

Design rules, learned the hard way in Round 1:
  * Nothing in here may ever raise into the request path — telemetry must not take
    down the service it observes.
  * Health and metrics endpoints are excluded from request metrics: the traffic
    generator probes /healthz every 5 s per service, which would otherwise dominate
    every counter and histogram.
  * A dependency URL resolving to localhost is logged loudly at startup. Two Round 1
    bugs (duplicate AD_URL, missing SHIPPING_SERVICE_URL) were silent localhost
    fallbacks that quietly deleted graph edges.
"""
import logging
import os
import time
import urllib.parse

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

logger = logging.getLogger("obs")

_service_name = os.getenv("SERVICE_NAME", "unknown")
_installed = False

# Request metrics: route template as the path label (bounded cardinality — never the
# raw URL, which would explode on /product/{id}).
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled, by route and status.",
    ["service", "method", "path", "status"],
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds", "Request handling latency, by route.",
    ["service", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Dependency-edge metrics. Names match the Round 1 pushgateway metrics exactly so
# discover_topology.py works unchanged; the errors counter is new in Phase 1.
DEP_CALLS = Counter(
    "service_dependency_calls_total", "Outbound calls observed from source to target.",
    ["source", "target"],
)
DEP_ERRORS = Counter(
    "service_dependency_errors_total",
    "Outbound calls that failed (exception, or HTTP 5xx from the target).",
    ["source", "target"],
)

_SKIP_PATHS = {"/healthz", "/metrics"}


def _classify(url):
    """Map an outbound URL to a canonical in-cluster service name, or None."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return None
    name = host.split(".")[0]
    if name.startswith("stylehub-"):
        return name
    if name in ("redis", "stylehub-redis"):
        return "stylehub-redis"
    return None


def record_dependency(target, error=False):
    """Record one observed call to `target`. For non-HTTP edges (cart -> redis) that
    the requests patch below cannot see."""
    try:
        if not target:
            return
        DEP_CALLS.labels(source=_service_name, target=target).inc()
        if error:
            DEP_ERRORS.labels(source=_service_name, target=target).inc()
    except Exception:
        pass


def _patch_requests():
    """Count every outbound HTTP call and its outcome at the single chokepoint all
    requests.get/post/delete calls funnel through. 5xx counts as an error even though
    no exception was raised — a dependency answering 500 has still failed its caller."""
    try:
        import requests
    except ImportError:
        return  # leaf services without outbound calls don't ship requests

    original = requests.Session.request

    def instrumented(self, method, url, *args, **kwargs):
        target = None
        try:
            target = _classify(url)
        except Exception:
            pass
        try:
            resp = original(self, method, url, *args, **kwargs)
        except Exception:
            if target:
                record_dependency(target, error=True)
            raise
        if target:
            record_dependency(target, error=resp.status_code >= 500)
        return resp

    requests.Session.request = instrumented


def _init_tracing(app):
    """OpenTelemetry auto-instrumentation, gated on OTEL_EXPORTER_OTLP_ENDPOINT.

    Traces are ground truth and demonstration material; the model's input stays
    metrics-only (0.32 ms inference — the lightweight-pipeline argument in the
    literature review depends on that division)."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": _service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,metrics")
        try:
            from opentelemetry.instrumentation.requests import RequestsInstrumentor
            RequestsInstrumentor().instrument()
        except Exception:
            pass
        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor
            RedisInstrumentor().instrument()
        except Exception:
            pass
        logger.info(f"obs: tracing enabled -> {endpoint}")
        return True
    except Exception as e:
        logger.warning(f"obs: tracing requested but failed to initialise ({e}); continuing without")
        return False


def _audit_dependencies(dependencies):
    """Log every resolved dependency URL at startup; shout if one fell back to
    localhost — in Kubernetes that always means a missing/broken env var."""
    for name, url in (dependencies or {}).items():
        if "localhost" in str(url) or "127.0.0.1" in str(url):
            logger.warning(
                f"obs: dependency '{name}' resolved to {url} — this is a localhost "
                f"FALLBACK and will fail in-cluster. Check the deployment env vars."
            )
        else:
            logger.info(f"obs: dependency '{name}' -> {url}")


def install(app, service_name=None, dependencies=None):
    """Wire observability into a FastAPI app. Call once, right after FastAPI()."""
    global _service_name, _installed
    if service_name:
        _service_name = service_name
    if _installed:
        return
    _installed = True

    _patch_requests()
    _audit_dependencies(dependencies)
    traced = _init_tracing(app)

    @app.middleware("http")
    async def _obs_middleware(request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            try:
                route = request.scope.get("route")
                path = getattr(route, "path", None) or "unmatched"
                if path not in _SKIP_PATHS:
                    HTTP_REQUESTS.labels(
                        service=_service_name, method=request.method,
                        path=path, status=str(status),
                    ).inc()
                    HTTP_DURATION.labels(service=_service_name, path=path).observe(
                        time.perf_counter() - start
                    )
            except Exception:
                pass

    # An explicit route, not app.mount(): the ASGI mount answers only /metrics/ and 307s
    # the bare path, which pollutes http_requests_total with "unmatched" redirect hits.
    # A real route serves /metrics with 200 and is skipped cleanly by _SKIP_PATHS.
    @app.get("/metrics")
    def _metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    logger.info(f"obs: installed for {_service_name} (metrics=/metrics, tracing={'on' if traced else 'off'})")

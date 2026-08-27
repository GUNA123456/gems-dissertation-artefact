#!/usr/bin/env python3
"""
Continuous traffic generator for the GEMS chaos experiments.


"""
import time
import urllib.request
import urllib.error
import urllib.parse
import socket
import threading

PUSHGATEWAY_URL = "http://prometheus-prometheus-pushgateway.monitoring.svc.cluster.local:9091"
INTERVAL_SECONDS = 5
REQUEST_TIMEOUT = 8  # must exceed the largest injected chaos delay (2000ms + 200ms jitter)

# Probing /healthz proves a service is alive but never makes it call its own dependencies,
# so the call graph stays invisible and edges like checkout->payment never fire. The journey
# loop below drives real storefront flows through the frontend, which fans out to the rest of
# the system, so depgraph.py can observe the dependency edges that actually exist at runtime.
FRONTEND = "stylehub-frontend.default.svc.cluster.local"
JOURNEY_INTERVAL_SECONDS = 15
PRODUCT_IDS = ["SH-001", "SH-002", "SH-003", "SH-004", "SH-005"]
CURRENCIES = ["EUR", "GBP", "INR"]

# service label matches NODE_MAP in extract_telemetry.py exactly (used as an exact match,
# not a pod-name prefix match, so it's stable across pod restarts/pod-kill chaos)
SERVICES = {
    "stylehub-frontend": ("stylehub-frontend.default.svc.cluster.local", 80, "/"),  # no /healthz on frontend
    "stylehub-ad-service": ("stylehub-ad-service.default.svc.cluster.local", 8087, "/healthz"),
    "stylehub-cart-service": ("stylehub-cart-service.default.svc.cluster.local", 8082, "/healthz"),
    "stylehub-checkout-service": ("stylehub-checkout-service.default.svc.cluster.local", 8086, "/healthz"),
    "stylehub-currency-service": ("stylehub-currency-service.default.svc.cluster.local", 8083, "/healthz"),
    "stylehub-email-service": ("stylehub-email-service.default.svc.cluster.local", 8088, "/healthz"),
    "stylehub-payment-service": ("stylehub-payment-service.default.svc.cluster.local", 8089, "/healthz"),
    "stylehub-product-catalog-service": ("stylehub-product-catalog-service.default.svc.cluster.local", 8081, "/healthz"),
    "stylehub-recommendation-service": ("stylehub-recommendation-service.default.svc.cluster.local", 8084, "/healthz"),
    "stylehub-shipping-service": ("stylehub-shipping-service.default.svc.cluster.local", 8085, "/healthz"),
}


def probe(service_name, host, port, path):
    url = f"http://{host}:{port}{path}"
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
            resp.read()
        elapsed_ms = (time.monotonic() - start) * 1000
        return service_name, elapsed_ms, None
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return service_name, elapsed_ms, str(e)


def push_metrics(results):
    lines = ["# TYPE service_request_latency_ms gauge"]
    for service_name, elapsed_ms, err in results:
        lines.append(f'service_request_latency_ms{{service="{service_name}"}} {elapsed_ms:.2f}')
    body = ("\n".join(lines) + "\n").encode("utf-8")

    req = urllib.request.Request(
        f"{PUSHGATEWAY_URL}/metrics/job/traffic_probe",
        data=body,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except (urllib.error.URLError, socket.timeout) as e:
        print(f"push failed: {e}", flush=True)
        return False


def _hit(method, path, form=None, currency=None):
    """One storefront request. Returns True on any HTTP response, including 4xx/5xx —
    the point is that the call chain executed, not that the order succeeded."""
    url = f"http://{FRONTEND}:80{path}"
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if currency is not None:
        # Prices are only converted when the storefront is browsed in a non-USD currency,
        # which is the sole path that reaches currency-service. Without this the edge exists
        # in the code but never appears in the discovered graph.
        req.add_header("Cookie", f"user_currency={currency}")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, socket.timeout, ConnectionError):
        return False


def journey(n):
    """One full browse -> add to cart -> checkout flow.

    Each step drives a different part of the dependency graph:
      /                 frontend -> catalog, cart, ad
      /product/{id}     frontend -> catalog, recommendation
      /add-to-cart      frontend -> cart -> redis
      /cart             frontend -> cart, catalog, shipping
      /checkout         frontend -> checkout -> cart, shipping, payment, email
    """
    pid = PRODUCT_IDS[n % len(PRODUCT_IDS)]
    # Alternate between USD and a foreign currency so the conversion path is exercised.
    cur = None if n % 2 == 0 else CURRENCIES[(n // 2) % len(CURRENCIES)]
    steps = [
        ("GET", "/", None, cur),
        ("GET", f"/product/{pid}", None, cur),
        ("POST", "/add-to-cart", {"product_id": pid, "quantity": 1}, None),
        ("GET", "/cart", None, cur),
    ]
    # Only check out every third journey, so the cart spends time in a non-empty state
    # rather than being emptied immediately after every add.
    if n % 3 == 2:
        # Carry the journey's currency cookie into checkout (Phase 2): the frontend passes
        # it through as user_currency, which is the only path that exercises the new
        # checkout->currency edge. Without this, every journey checkout is USD and that
        # edge never sees organic traffic.
        steps.append(("POST", "/checkout", {}, cur))
    return sum(1 for m, p, f, c in steps if _hit(m, p, f, c)), len(steps)


def journey_loop():
    n = 0
    while True:
        start = time.monotonic()
        try:
            ok, total = journey(n)
            print(f"journey {n}: {ok}/{total} steps reached the storefront", flush=True)
        except Exception as e:
            print(f"journey {n} failed: {e}", flush=True)
        n += 1
        time.sleep(max(0.0, JOURNEY_INTERVAL_SECONDS - (time.monotonic() - start)))


def main():
    print(f"traffic_generator starting: {len(SERVICES)} services, interval={INTERVAL_SECONDS}s, "
          f"journeys every {JOURNEY_INTERVAL_SECONDS}s", flush=True)
    threading.Thread(target=journey_loop, daemon=True).start()
    while True:
        cycle_start = time.monotonic()
        results = []
        threads = []
        lock = threading.Lock()

        def worker(name, host, port, path):
            r = probe(name, host, port, path)
            with lock:
                results.append(r)

        for name, (host, port, path) in SERVICES.items():
            t = threading.Thread(target=worker, args=(name, host, port, path))
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=REQUEST_TIMEOUT + 2)

        ok = push_metrics(results)
        errs = [r for r in results if r[2] is not None]
        summary = ", ".join(f"{n}={ms:.0f}ms" for n, ms, e in results if e is None)
        print(f"cycle: pushed={ok} errors={len(errs)} | {summary}", flush=True)

        elapsed = time.monotonic() - cycle_start
        time.sleep(max(0.0, INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    main()

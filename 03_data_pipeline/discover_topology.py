#!/usr/bin/env python3
"""Discover the service dependency graph from observed runtime calls.

Replaces the hand-authored `topology.json`, whose static edge list contradicts the premise
the literature review is built on: Winchester et al. (2024) show runtime topologies deviate
substantially from any declared view, which is the stated justification for building GEMS at
all. Edges here come from `service_dependency_calls_total`, published by depgraph.py inside
each calling service, so E_t reflects calls that actually happened in a given window.

Usage:
  discover_topology.py                      # last 10 minutes, human-readable comparison
  discover_topology.py --window 30m --json topology_discovered.json
  discover_topology.py --compare topology.json
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

# Node ordering is contractual: it must match NODE_MAP in extract_telemetry.py, because the
# model's feature matrix rows and the adjacency matrix are indexed by the same positions.
NODE_MAP = [
    "stylehub-frontend",
    "stylehub-ad-service",
    "stylehub-cart-service",
    "stylehub-checkout-service",
    "stylehub-currency-service",
    "stylehub-email-service",
    "stylehub-payment-service",
    "stylehub-product-catalog-service",
    "stylehub-recommendation-service",
    "stylehub-shipping-service",
    "stylehub-redis",
]


def query(prom_url, expr):
    url = f"{prom_url}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=20) as resp:
        payload = json.loads(resp.read())
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus rejected the query: {payload}")
    return payload["data"]["result"]


def discover(prom_url, window):
    """Return {(src_idx, dst_idx): calls_in_window} for every edge observed in the window.

    Edge *existence* and edge *weight* are deliberately answered by two different queries.
    `increase()` extrapolates and silently drops any series with fewer than two samples in
    the range, which is exactly the low-traffic case — an edge like checkout->email fires a
    handful of times an hour and would vanish from the graph despite being real. Existence is
    therefore taken from max_over_time (the counter is present and non-zero at all), and the
    weight from the max-min delta, which is an exact observed count rather than an
    extrapolated fractional one.
    """
    totals = f"sum by (source, target) (max_over_time(service_dependency_calls_total[{window}]))"
    deltas = (f"sum by (source, target) (max_over_time(service_dependency_calls_total[{window}]) "
              f"- min_over_time(service_dependency_calls_total[{window}]))")

    def as_map(expr):
        out = {}
        for series in query(prom_url, expr):
            key = (series["metric"].get("source", ""), series["metric"].get("target", ""))
            out[key] = float(series["value"][1])
        return out

    present, moved = as_map(totals), as_map(deltas)
    edges, unknown = {}, set()
    for (src, dst), total in present.items():
        if total <= 0:
            continue
        if src not in NODE_MAP or dst not in NODE_MAP:
            unknown.add((src, dst))
            continue
        edges[(NODE_MAP.index(src), NODE_MAP.index(dst))] = moved.get((src, dst), 0.0)
    return edges, unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prometheus-url", default="http://localhost:9090")
    ap.add_argument("--window", default="10m", help="lookback window, e.g. 10m, 1h (default: %(default)s)")
    ap.add_argument("--json", help="write the discovered topology to this path")
    ap.add_argument("--compare", help="compare against an existing static topology JSON")
    args = ap.parse_args()

    try:
        edges, unknown = discover(args.prometheus_url, args.window)
    except Exception as e:
        print(f"❌ Could not reach Prometheus at {args.prometheus_url}: {e}")
        sys.exit(1)

    if not edges:
        print(f"⚠️  No dependency calls observed in the last {args.window}.")
        print("    Check that the instrumented services are running and traffic is flowing:")
        print("      kubectl logs -n default deploy/traffic-generator --tail=5")
        sys.exit(1)

    print(f"🔍 Discovered dependency graph over the last {args.window}")
    print(f"   {len(edges)} edges across {len(NODE_MAP)} services\n")
    print(f"   {'source':<34}{'target':<34}{'calls':>9}")
    print("   " + "-" * 75)
    for (s, d), n in sorted(edges.items(), key=lambda kv: -kv[1]):
        print(f"   {NODE_MAP[s].replace('stylehub-',''):<34}"
              f"{NODE_MAP[d].replace('stylehub-',''):<34}{n:>9.0f}")
    if unknown:
        print(f"\n   ⚠️  {len(unknown)} edge(s) referenced services outside NODE_MAP: {sorted(unknown)}")

    if args.compare:
        with open(args.compare) as f:
            static = json.load(f)
        declared = {tuple(e) for e in static.get("edges", static.get("edge_index", []))}
        found = set(edges)
        print(f"\n📐 Comparison against {args.compare}")
        print(f"   declared: {len(declared)}   discovered: {len(found)}")
        only_declared = declared - found
        only_found = found - declared
        if only_declared:
            print(f"\n   Declared but NEVER observed ({len(only_declared)}) — edges the static file asserts")
            print("   that carried no traffic in this window:")
            for s, d in sorted(only_declared):
                print(f"     {NODE_MAP[s].replace('stylehub-',''):<32} -> {NODE_MAP[d].replace('stylehub-','')}")
        if only_found:
            print(f"\n   Observed but NOT declared ({len(only_found)}) — real edges the static file misses:")
            for s, d in sorted(only_found):
                print(f"     {NODE_MAP[s].replace('stylehub-',''):<32} -> {NODE_MAP[d].replace('stylehub-','')}")
        agree = len(declared & found)
        print(f"\n   Agreement: {agree}/{len(declared | found)} edges "
              f"({100 * agree / max(len(declared | found), 1):.1f}%)")

    if args.json:
        out = {
            "nodes": NODE_MAP,
            "edge_index": [[s, d] for (s, d) in sorted(edges)],
            "edge_weights": [edges[(s, d)] for (s, d) in sorted(edges)],
            "window": args.window,
            "source": "discovered from service_dependency_calls_total",
        }
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\n💾 Written to {args.json}")


if __name__ == "__main__":
    main()

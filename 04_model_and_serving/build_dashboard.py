#!/usr/bin/env python3
"""Create the GEMS model dashboard in Grafana via its HTTP API (idempotent).

Honesty rules encoded here (Step 3c, Current_Experiment_Plan.md):
  * the alarm line is read from the CHECKPOINT (tau), never hard-coded — the
    old 0.805 literal silently disagreed with any retrained checkpoint;
  * the probability and latency panels share x=0/w=18 so their time axes
    align pixel-for-pixel — the two curves whose crossings ARE the argument
    must be readable with one vertical eye-line;
  * a "prediction age" tile displays time() - gems_prediction_as_of_seconds,
    surfacing the Pushgateway restamping lag instead of hiding it. Timing
    claims still come from the tick log, never from any panel.
"""
import argparse
import base64
import json
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--checkpoint", default="gems_model_v2.pt")
ap.add_argument("--grafana", default="http://localhost:30300")
args = ap.parse_args()

import torch  # after argparse so --help works without the venv
c = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
TAU = round(float(c["tau"]), 3)
SLO_FLOOR = float(c["slo"]["latency_floor_s"])
print("checkpoint %s: tau=%.3f slo_floor=%.1fs" % (args.checkpoint, TAU, SLO_FLOOR))

AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()


def api(path, payload=None):
    req = urllib.request.Request(args.grafana + path,
                                 data=json.dumps(payload).encode() if payload else None,
                                 headers={"Authorization": AUTH,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


ds = next(d for d in api("/api/datasources") if d["type"] == "prometheus")
DS = {"type": "prometheus", "uid": ds["uid"]}
print("prometheus datasource uid:", ds["uid"])


def target(expr, legend, instant=False):
    t = {"expr": expr, "legendFormat": legend, "refId": "A", "datasource": DS}
    if instant:
        t.update({"instant": True, "range": False})
    return t


def ts_panel(pid, title, targets, x, y, w, h, unit="", thresh_line=None, maxv=None):
    p = {"id": pid, "type": "timeseries", "title": title, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": targets,
         "fieldConfig": {"defaults": {"unit": unit, "min": 0,
                                      "custom": {"lineWidth": 2, "fillOpacity": 8}},
                         "overrides": []},
         "options": {"legend": {"displayMode": "table", "placement": "right",
                                "calcs": ["lastNotNull"]}}}
    if maxv:
        p["fieldConfig"]["defaults"]["max"] = maxv
    if thresh_line is not None:
        p["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"] = {"mode": "line"}
        p["fieldConfig"]["defaults"]["thresholds"] = {
            "mode": "absolute",
            "steps": [{"color": "green", "value": None},
                      {"color": "red", "value": thresh_line}]}
    return p


def stat_panel(pid, title, targets, x, y, w, h, mappings=None, unit="",
               thresholds=None, color_mode="background"):
    return {"id": pid, "type": "stat", "title": title, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": targets,
            "fieldConfig": {"defaults": {
                "unit": unit,
                "mappings": mappings or [],
                "thresholds": thresholds or {
                    "mode": "absolute",
                    "steps": [{"color": "green", "value": None}]}},
                "overrides": []},
            "options": {"colorMode": color_mode, "graphMode": "none",
                        "reduceOptions": {"calcs": ["lastNotNull"]}}}


dashboard = {
    "uid": "gems-model",
    "title": "GEMS — Cascade Prediction Model (live)",
    "timezone": "utc",
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "panels": [
        # Row 1: forecast (x=0,w=18) + verdict tiles
        ts_panel(1, "Breach probability per service — next 6 min (alarm line %.3f from checkpoint)" % TAU,
                 [target("gems_breach_probability", "{{service}}")],
                 0, 0, 18, 9, thresh_line=TAU, maxv=1.0),
        stat_panel(2, "MODEL ALARM", [target("gems_alarm", "")], 18, 0, 6, 5,
                   mappings=[{"type": "value", "options": {
                       "0": {"text": "QUIET", "color": "green"},
                       "1": {"text": "ALARM", "color": "red"}}}]),
        stat_panel(3, "STATIC MONITOR", [target("gems_static_fire", "")], 18, 5, 6, 4,
                   mappings=[{"type": "value", "options": {
                       "0": {"text": "quiet", "color": "green"},
                       "1": {"text": "FIRING", "color": "orange"}}}]),
        # Row 2: observed truth, SAME x/w as the forecast so time axes align
        ts_panel(5, "Mean request latency by service — v2 SLO floor %.1fs" % SLO_FLOOR,
                 [target('sum by (service)(rate(http_request_duration_seconds_sum{service=~\"stylehub-.*\"}[2m]))'
                         '/sum by (service)(rate(http_request_duration_seconds_count{service=~\"stylehub-.*\"}[2m]))',
                         "{{service}}")],
                 0, 9, 18, 8, unit="s", thresh_line=SLO_FLOOR),
        # The precursor channel, so the cart-mem demo tells its whole story on
        # one screen: memory climbs toward the red 256Mi OOM limit while the
        # latency panel above stays flat — then the probability panel alarms.
        # Direct cadvisor data: NO Pushgateway lag on this panel.
        ts_panel(16, "Container memory (working set) — the PRECURSOR channel "
                     "(red line = 256Mi OOM limit)",
                 [target('label_replace(container_memory_working_set_bytes'
                         '{namespace="default",container!="",container!="POD",'
                         'pod=~"stylehub-.*"}, "svc", "$1", "pod", '
                         '"stylehub-(.+)-[^-]+-[^-]+")', "{{svc}}")],
                 0, 17, 18, 8, unit="bytes", thresh_line=268435456.0),
        {"id": 4, "type": "bargauge",
         "title": "Root-cause ranking — READ ONLY WHEN MODEL ALARM IS RED",
         "datasource": DS,
         "gridPos": {"x": 18, "y": 9, "w": 6, "h": 5},
         "targets": [target("sort_desc(gems_cause_score)", "{{service}}", instant=True)],
         "fieldConfig": {"defaults": {"min": 0, "max": 1,
             "thresholds": {"mode": "absolute",
                            "steps": [{"color": "blue", "value": None},
                                      {"color": "red", "value": 0.7}]}},
             "overrides": []},
         "options": {"displayMode": "gradient", "orientation": "horizontal",
                     "reduceOptions": {"calcs": ["lastNotNull"]}}},
        # honesty tile: how stale is the model curve on THIS dashboard?
        stat_panel(6, "PREDICTION AGE (Pushgateway lag — timing evidence lives in the tick log)",
                   [target("time() - gems_prediction_as_of_seconds", "")],
                   18, 14, 6, 3, unit="s", color_mode="value",
                   thresholds={"mode": "absolute",
                               "steps": [{"color": "green", "value": None},
                                         {"color": "orange", "value": 120},
                                         {"color": "red", "value": 240}]}),
    ],
}

res = api("/api/dashboards/db", {"dashboard": dashboard, "overwrite": True,
                                 "message": "GEMS model dashboard (Step 3c)"})
print("dashboard:", res["status"], "->", args.grafana + res["url"])

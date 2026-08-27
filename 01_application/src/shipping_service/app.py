"""
StyleHub - Shipping Service
Clean FastAPI Microservice calculating shipping quotes & order tracking
"""

from fastapi import FastAPI
from typing import List, Dict
import os, uuid

app = FastAPI(title="StyleHub Shipping Service")

import obs  # /metrics + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-shipping-service")

@app.get("/healthz")
def health(): return {"status": "ok", "service": "shipping-service"}

@app.post("/api/shipping/quote")
def get_quote(items: List[Dict]):
    total_items = sum(item.get("quantity", 1) for item in items)
    cost = 8.99 + (total_items * 1.50)
    return {
        "cost_usd": {
            "currency_code": "USD",
            "units": int(cost),
            "nanos": int((cost - int(cost)) * 1e9)
        }
    }

@app.post("/api/shipping/ship")
def ship_order(address: Dict, items: List[Dict]):
    tracking_id = f"SH-TRK-{uuid.uuid4().hex[:10].upper()}"
    return {"tracking_id": tracking_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8085")), timeout_keep_alive=120)

"""
StyleHub - Ad Service
Clean FastAPI Microservice serving targeted advertisements
"""

from fastapi import FastAPI
from typing import List
import os

app = FastAPI(title="StyleHub Ad Service")

import obs  # /metrics + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-ad-service")

ADS_DB = {
    "clothing": [{"redirect_url": "/product/SH-001", "text": "🔥 Summer Sale: Up to 40% OFF Denim Jackets!"}],
    "footwear": [{"redirect_url": "/product/SH-003", "text": "👟 Premium Italian Leather Sneakers in stock."}],
    "accessories": [{"redirect_url": "/product/SH-005", "text": "🕶️ Polarized Acetate Sunglasses."}]
}

DEFAULT_ADS = [{"redirect_url": "/", "text": "🎉 Free Shipping on orders over $50 with code STYLEHUB2026!"}]

@app.get("/healthz")
def health(): return {"status": "ok", "service": "ad-service"}

@app.post("/api/ads")
def get_ads(context_keys: List[str]):
    matched = []
    for k in context_keys:
        if k.lower() in ADS_DB:
            matched.extend(ADS_DB[k.lower()])
    return {"ads": matched or DEFAULT_ADS}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8087")), timeout_keep_alive=120)

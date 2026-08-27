"""
StyleHub - Recommendation Service
Clean FastAPI Microservice providing product recommendations
"""

from fastapi import FastAPI, HTTPException
from typing import List
import logging, os, requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RecommendationService")

app = FastAPI(title="StyleHub Recommendation Service")

CATALOG_URL = os.getenv("PRODUCT_CATALOG_SERVICE_URL", "http://localhost:8081")

TIMEOUT_S = float(os.getenv("HTTP_TIMEOUT_SECONDS", "2"))  # Phase 4 single timeout policy

import obs  # /metrics + dependency-edge counters + optional OTel tracing
obs.install(app, "stylehub-recommendation-service", dependencies={"product-catalog": CATALOG_URL})

@app.get("/healthz")
def health(): return {"status": "ok", "service": "recommendation-service"}

# Phase 2: this was a stub — a hardcoded PID list and random.sample, zero outbound calls,
# which left the recommendation->catalog edge declared in the topology but nonexistent in
# reality (one of the three "phantom edges" the discovered graph exposed). Now the
# recommendations come from the live catalog, related-by-category to the seed products.
#
# Failure policy: the catalog is this service's ONLY reason to exist, so a catalog failure
# is a 502 here — and the FRONTEND degrades gracefully (recommendations are on its
# documented optional list). Net effect of a catalog kill: rec->catalog error edge, then
# frontend->rec error edge, while the product page itself still renders. A second,
# distinct cascade shape for the model to learn.
@app.post("/api/recommendations")
def get_recommendations(user_id: str = "user-demo-123", product_ids: List[str] = []):
    try:
        res = requests.get(f"{CATALOG_URL}/api/products", timeout=TIMEOUT_S)
        res.raise_for_status()
        products = res.json().get("products", [])
    except requests.RequestException as e:
        logger.error(f"CRITICAL dependency 'product-catalog-service' failed: {type(e).__name__}")
        raise HTTPException(status_code=502,
                            detail=f"product-catalog-service unavailable ({type(e).__name__})")

    seed_categories = {c for p in products if p["id"] in product_ids for c in p.get("categories", [])}
    others = [p["id"] for p in products if p["id"] not in product_ids]
    if seed_categories:
        related = [p["id"] for p in products
                   if p["id"] not in product_ids
                   and seed_categories & set(p.get("categories", []))]
        # Related items first; pad with the rest of the catalog so there are up to 4.
        others = related + [pid for pid in others if pid not in related]
    if not others:  # seeds covered the whole catalog — fall back to anything
        others = [p["id"] for p in products]
    return {"product_ids": others[:4]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8084")), timeout_keep_alive=120)

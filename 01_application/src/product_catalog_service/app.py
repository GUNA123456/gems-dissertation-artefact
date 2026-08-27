"""
StyleHub - Product Catalog Service
Clean FastAPI Microservice managing fashion apparel catalog & search
"""

from fastapi import FastAPI, HTTPException
import os, sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI(title="StyleHub Product Catalog Service")

import obs  # /metrics + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-product-catalog-service")

PRODUCTS_DB = [
    {"id": "SH-001", "name": "Vintage Denim Jacket", "description": "Classic vintage washed denim jacket with reinforced stitching.", "picture": "/static/img/products/denim-jacket.jpg", "price_usd": {"currency_code": "USD", "units": 89, "nanos": 99000000}, "categories": ["clothing", "jackets"]},
    {"id": "SH-002", "name": "Urban Streetwear Hoodie", "description": "Heavyweight organic cotton blend hoodie with relaxed fit.", "picture": "/static/img/products/streetwear-hoodie.jpg", "price_usd": {"currency_code": "USD", "units": 64, "nanos": 50000000}, "categories": ["clothing", "hoodies"]},
    {"id": "SH-003", "name": "Minimalist Leather Sneakers", "description": "Premium Italian leather low-top sneakers.", "picture": "/static/img/products/leather-sneakers.jpg", "price_usd": {"currency_code": "USD", "units": 120, "nanos": 0}, "categories": ["footwear", "shoes"]},
    {"id": "SH-004", "name": "Tailored Slim-Fit Chinos", "description": "Breathable stretch-cotton chinos.", "picture": "/static/img/products/slim-chinos.jpg", "price_usd": {"currency_code": "USD", "units": 55, "nanos": 0}, "categories": ["clothing", "pants"]},
    {"id": "SH-005", "name": "Classic Polarized Sunglasses", "description": "UV400 protection polarized lenses.", "picture": "/static/img/products/sunglasses.jpg", "price_usd": {"currency_code": "USD", "units": 42, "nanos": 50000000}, "categories": ["accessories", "eyewear"]},
    {"id": "SH-006", "name": "Canvas Minimalist Backpack", "description": "Water-resistant canvas backpack with laptop compartment.", "picture": "/static/img/products/backpack.jpg", "price_usd": {"currency_code": "USD", "units": 78, "nanos": 0}, "categories": ["accessories", "bags"]}
]

@app.get("/healthz")
def health(): return {"status": "ok", "service": "product-catalog-service"}

@app.get("/api/products")
def list_products():
    return {"products": PRODUCTS_DB}

@app.get("/api/products/search")
def search_products(q: str = ""):
    query = q.lower()
    results = [p for p in PRODUCTS_DB if query in p["name"].lower() or query in p["description"].lower() or any(query in c.lower() for c in p["categories"])]
    return {"products": results}

@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    for p in PRODUCTS_DB:
        if p["id"] == product_id:
            return p
    raise HTTPException(status_code=404, detail="Product not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8081")), timeout_keep_alive=120)

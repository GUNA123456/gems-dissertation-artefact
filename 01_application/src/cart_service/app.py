"""
StyleHub - Cart Service
Clean FastAPI Microservice managing user shopping carts backed by Redis
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os, json, logging

# Inline data models (self-contained, no shared module dependency)
class CartItem(BaseModel):
    product_id: str
    quantity: int

class AddItemRequest(BaseModel):
    user_id: str
    item: CartItem

class UpdateQuantityRequest(BaseModel):
    user_id: str
    product_id: str
    quantity: int

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CartService")

app = FastAPI(title="StyleHub Cart Service")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

import obs  # /metrics + dependency-edge counters + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-cart-service", dependencies={"redis": f"{REDIS_HOST}:{REDIS_PORT}"})

import redis as redis_lib


_redis_client = None
_redis_ok = None  # None=no operation yet, True=last op succeeded, False=last op failed

def _get_redis():
    global _redis_client
    if _redis_client is None:
        client = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0,
                                 socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _redis_client = client
        logger.info(f"⚡ Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
    return _redis_client

def _redis_op(op):
    """Run one Redis operation with the cascade-visible failure policy: any failure is a
    503 naming redis, the connection is discarded so the next call reconnects fresh, and
    the cart->redis edge (not HTTP, invisible to the obs requests patch) is recorded."""
    global _redis_client, _redis_ok
    try:
        result = op(_get_redis())
        _redis_ok = True
        obs.record_dependency("stylehub-redis")
        return result
    except Exception as e:
        _redis_client = None  # discard; next operation attempts a fresh connection
        _redis_ok = False
        obs.record_dependency("stylehub-redis", error=True)
        logger.error(f"Redis operation failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503, detail=f"redis unavailable: {type(e).__name__}")

def _get_cart(user_id: str):
    raw = _redis_op(lambda r: r.get(f"cart:{user_id}"))
    return json.loads(raw) if raw else []

def _save_cart(user_id: str, items: list):
    _redis_op(lambda r: r.set(f"cart:{user_id}", json.dumps(items)))

@app.get("/healthz")
def health():
   
    storage = {None: "redis-unused-yet", True: "redis", False: "redis-unavailable"}[_redis_ok]
    return {"status": "ok", "service": "cart-service", "storage": storage}

@app.get("/api/cart/{user_id}")
def get_cart(user_id: str):
    items = _get_cart(user_id)
    return {"user_id": user_id, "items": items}

@app.post("/api/cart/add")
def add_item(req: AddItemRequest):
    items = _get_cart(req.user_id)
    found = False
    for i in items:
        if i["product_id"] == req.item.product_id:
            i["quantity"] += req.item.quantity
            found = True
            break
    if not found:
        items.append({"product_id": req.item.product_id, "quantity": req.item.quantity})
    _save_cart(req.user_id, items)
    return {"status": "success"}

@app.post("/api/cart/update-quantity")
def update_quantity(req: UpdateQuantityRequest):
    items = _get_cart(req.user_id)
    if req.quantity <= 0:
        items = [i for i in items if i["product_id"] != req.product_id]
    else:
        for i in items:
            if i["product_id"] == req.product_id:
                i["quantity"] = req.quantity
                break
    _save_cart(req.user_id, items)
    return {"status": "success"}

@app.delete("/api/cart/{user_id}/item/{product_id}")
def remove_item(user_id: str, product_id: str):
    items = _get_cart(user_id)
    filtered = [i for i in items if i["product_id"] != product_id]
    _save_cart(user_id, filtered)
    return {"status": "success"}

@app.delete("/api/cart/{user_id}")
def empty_cart(user_id: str):
    _save_cart(user_id, [])
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8082")), timeout_keep_alive=120)

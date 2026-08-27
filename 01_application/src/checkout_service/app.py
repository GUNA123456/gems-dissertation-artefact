"""
StyleHub - Checkout Orchestrator Service
Clean FastAPI Microservice orchestrating Cart, Shipping, Payment, and Email REST calls
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os, uuid, logging, requests

# Inline data models (self-contained, no shared module dependency)
class Address(BaseModel):
    street_address: str
    city: str
    state: str
    country: str = "United States"
    zip_code: int

class CreditCardInfo(BaseModel):
    credit_card_number: str
    credit_card_cvv: int
    credit_card_expiration_year: int
    credit_card_expiration_month: int

class PlaceOrderRequest(BaseModel):
    user_id: str
    user_currency: str = "USD"
    email: str
    address: Address
    credit_card: CreditCardInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CheckoutService")

app = FastAPI(title="StyleHub Checkout Service")

CART_URL = os.getenv("CART_SERVICE_URL", os.getenv("CART_SERVICE_ADDR", "http://localhost:8082"))
SHIPPING_URL = os.getenv("SHIPPING_SERVICE_URL", os.getenv("SHIPPING_SERVICE_ADDR", "http://localhost:8085"))
PAYMENT_URL = os.getenv("PAYMENT_SERVICE_URL", os.getenv("PAYMENT_SERVICE_ADDR", "http://localhost:8089"))
EMAIL_URL = os.getenv("EMAIL_SERVICE_URL", os.getenv("EMAIL_SERVICE_ADDR", "http://localhost:8088"))
# Phase 2: both of these were declared in the original topology but never implemented —
# two of the three "phantom edges" the discovered graph exposed. Now real.
CATALOG_URL = os.getenv("PRODUCT_CATALOG_SERVICE_URL", "http://localhost:8081")
CURRENCY_URL = os.getenv("CURRENCY_SERVICE_URL", "http://localhost:8083")

TIMEOUT_S = float(os.getenv("HTTP_TIMEOUT_SECONDS", "2"))  # Phase 4 single timeout policy

import obs  # /metrics + dependency-edge counters + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-checkout-service", dependencies={
    "cart": CART_URL, "shipping": SHIPPING_URL, "payment": PAYMENT_URL, "email": EMAIL_URL,
    "product-catalog": CATALOG_URL, "currency": CURRENCY_URL,
})

@app.get("/healthz")
def health(): return {"status": "ok", "service": "checkout-service"}


def _call_critical(dependency, fn):
    """Run one critical outbound call; translate any failure into a 502 that names
    the dependency, so the caller (and the metrics) see exactly what broke."""
    try:
        resp = fn()
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        logger.error(f"CRITICAL dependency '{dependency}' failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"{dependency} unavailable ({type(e).__name__}) — order not placed",
        )


@app.post("/api/checkout")
def place_order(req: PlaceOrderRequest):
    order_id = f"ORD-SH-{uuid.uuid4().hex[:8].upper()}"
    logger.info(f"🛒 [CHECKOUT STARTED] Order: {order_id} | User: {req.user_id}")

    # 1. Fetch Cart — CRITICAL (an order for an unknown cart is not an order)
    cart_res = _call_critical("cart-service", lambda: requests.get(
        f"{CART_URL}/api/cart/{req.user_id}", timeout=TIMEOUT_S))
    cart_items = cart_res.json().get("items", [])
    if not cart_items:
        raise HTTPException(status_code=400, detail="cart is empty — nothing to order")

    # 2. Price validation — CRITICAL (Phase 2 edge: checkout->catalog). An order whose
    # prices cannot be verified against the catalog must not proceed to payment; Round 1
    # charged a hardcoded 45 USD regardless of what was in the cart.
    total_usd = 0.0
    for item in cart_items:
        p_res = _call_critical("product-catalog-service", lambda pid=item["product_id"]: requests.get(
            f"{CATALOG_URL}/api/products/{pid}", timeout=TIMEOUT_S))
        price = p_res.json().get("price_usd", {})
        total_usd += (price.get("units", 0) + price.get("nanos", 0) / 1e9) * item.get("quantity", 1)

    # 3. Currency conversion — OPTIONAL (Phase 2 edge: checkout->currency). If the
    # customer shops in EUR/GBP/INR and currency-service is down, the order proceeds in
    # USD — but the degradation is counted and REPORTED, never silent.
    charge_currency, charge_units, charge_nanos = "USD", int(total_usd), int((total_usd % 1) * 1e9)
    currency_converted = True
    if req.user_currency != "USD":
        currency_converted = False
        try:
            c_res = requests.post(f"{CURRENCY_URL}/api/currency/convert",
                                  params={"from_code": "USD", "to_code": req.user_currency,
                                          "units": int(total_usd),
                                          "nanos": int((total_usd % 1) * 1e9)}, timeout=TIMEOUT_S)
            c_res.raise_for_status()
            c = c_res.json()
            charge_currency, charge_units, charge_nanos = c["currency_code"], c["units"], c["nanos"]
            currency_converted = True
        except requests.RequestException as e:
            logger.warning(f"optional dependency 'currency-service' failed: {type(e).__name__}; charging USD")

    # 4. Ship Order — CRITICAL (no shipment booked means nothing will arrive)
    ship_res = _call_critical("shipping-service", lambda: requests.post(
        f"{SHIPPING_URL}/api/shipping/ship",
        json={"address": req.address.model_dump(), "items": cart_items}, timeout=TIMEOUT_S))
    tracking_id = ship_res.json().get("tracking_id", f"SH-TRK-{uuid.uuid4().hex[:8].upper()}")

    # 5. Charge Payment — CRITICAL (an unpaid order must never report success).
    # The amount is now the catalog-validated order total, not Round 1's hardcoded 45.
    _call_critical("payment-service", lambda: requests.post(
        f"{PAYMENT_URL}/api/payment/charge",
        json={"amount": {"currency_code": charge_currency, "units": charge_units, "nanos": charge_nanos},
              "credit_card": req.credit_card.model_dump()}, timeout=TIMEOUT_S))

    # 6. Email & empty cart — OPTIONAL: degrade, but visibly (counted + reported)
    email_sent = True
    try:
        requests.post(f"{EMAIL_URL}/api/email/confirmation", params={"email": req.email},
                      json={"order_id": order_id, "shipping_tracking_id": tracking_id},
                      timeout=TIMEOUT_S).raise_for_status()
    except requests.RequestException as e:
        email_sent = False
        logger.warning(f"optional dependency 'email-service' failed: {type(e).__name__}")
    try:
        requests.delete(f"{CART_URL}/api/cart/{req.user_id}", timeout=TIMEOUT_S)
    except requests.RequestException as e:
        logger.warning(f"post-order cart empty failed: {type(e).__name__}")

    return {
        "order": {
            "order_id": order_id,
            "shipping_tracking_id": tracking_id,
            "items": cart_items,
            "total": {"currency_code": charge_currency, "units": charge_units, "nanos": charge_nanos},
            # Degradation is reported, never hidden: a caller (and the dataset labeller)
            # can distinguish a full success from one with a failed confirmation email or
            # a currency conversion that fell back to USD.
            "email_sent": email_sent,
            "currency_converted": currency_converted
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8086")), timeout_keep_alive=120)

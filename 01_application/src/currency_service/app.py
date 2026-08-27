"""
StyleHub - Currency Service
Clean FastAPI Microservice for multi-currency conversion
"""

from fastapi import FastAPI, HTTPException
import os

app = FastAPI(title="StyleHub Currency Service")

import obs  # /metrics + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-currency-service")

EXCHANGE_RATES = {"USD": 1.0, "EUR": 0.92, "GBP": 0.78, "JPY": 155.0, "CAD": 1.36, "INR": 83.5}

@app.get("/healthz")
def health(): return {"status": "ok", "service": "currency-service"}

@app.get("/api/currency/supported")
def get_supported_currencies():
    return {"currencies": list(EXCHANGE_RATES.keys())}

@app.get("/api/currency/rates")
def get_rates():
    """Full rate table in one response. Exists so the frontend can convert prices
    locally instead of one HTTP round-trip per price — the N+1 pattern that put the
    storefront's NORMAL latency at ~745 ms and made a flat latency SLO useless."""
    return {"base": "USD", "rates": EXCHANGE_RATES}

@app.post("/api/currency/convert")
def convert_currency(from_code: str, to_code: str, units: int, nanos: int = 0):
    from_c, to_c = from_code.upper(), to_code.upper()
    if from_c not in EXCHANGE_RATES or to_c not in EXCHANGE_RATES:
        raise HTTPException(status_code=400, detail="Unsupported currency")
    
    usd_val = (units + nanos / 1e9) / EXCHANGE_RATES[from_c]
    converted = usd_val * EXCHANGE_RATES[to_c]
    return {
        "currency_code": to_c,
        "units": int(converted),
        "nanos": int((converted - int(converted)) * 1e9)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8083")), timeout_keep_alive=120)

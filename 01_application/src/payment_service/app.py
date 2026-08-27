"""
StyleHub - Payment Processing Service
Clean FastAPI Microservice for credit card validation & transactions
"""

from fastapi import FastAPI, HTTPException
from typing import Dict
import os, uuid, logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PaymentService")

app = FastAPI(title="StyleHub Payment Service")

import obs  # /metrics + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-payment-service")

@app.get("/healthz")
def health(): return {"status": "ok", "service": "payment-service"}

@app.post("/api/payment/charge")
def charge_payment(amount: Dict, credit_card: Dict):
    card_num = credit_card.get("credit_card_number", "").replace("-", "").replace(" ", "")
    if len(card_num) < 13 or not card_num.isdigit():
        raise HTTPException(status_code=400, detail="Invalid credit card format")
    
    tx_id = f"TX-SH-{uuid.uuid4().hex[:12].upper()}"
    units = amount.get("units", 0)
    currency = amount.get("currency_code", "USD")
    logger.info(f"💳 [PAYMENT SUCCESS] Transaction {tx_id} charged {units} {currency}")
    return {"transaction_id": tx_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8089")), timeout_keep_alive=120)

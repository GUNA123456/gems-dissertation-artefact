"""
StyleHub - Email Service
Clean FastAPI Microservice for order receipt & confirmation notifications
"""

from fastapi import FastAPI
from typing import Dict
import os, logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EmailService")

app = FastAPI(title="StyleHub Email Service")

import obs  # /metrics + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-email-service")

@app.get("/healthz")
def health(): return {"status": "ok", "service": "email-service"}

@app.post("/api/email/confirmation")
def send_confirmation(email: str, order: Dict):
    order_id = order.get("order_id", "UNKNOWN")
    tracking = order.get("shipping_tracking_id", "N/A")
    logger.info(f"📧 [EMAIL DISPATCH] Sent receipt to {email} | Order ID: {order_id} | Tracking: {tracking}")
    return {"status": "sent"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8088")), timeout_keep_alive=120)

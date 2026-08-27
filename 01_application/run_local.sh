#!/bin/bash
# StyleHub Native Local Microservices Launcher
# Runs all Python microservices locally

echo "🚀 Setting up StyleHub local Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --quiet fastapi uvicorn pydantic requests redis python-multipart

echo "⚡ Starting StyleHub Microservices..."

PORT=8081 python3 src/product_catalog_service/app.py &
PORT=8082 python3 src/cart_service/app.py &
PORT=8083 python3 src/currency_service/app.py &
PORT=8084 python3 src/recommendation_service/app.py &
PORT=8085 python3 src/shipping_service/app.py &
PORT=8086 python3 src/checkout_service/app.py &
PORT=8087 python3 src/ad_service/app.py &
PORT=8088 python3 src/email_service/app.py &
PORT=8089 python3 src/payment_service/app.py &
PORT=8080 python3 src/frontend/app.py &

echo "✅ All StyleHub Microservices Started!"
echo "👉 Open your browser at: http://localhost:8080"
echo "Press Ctrl+C to stop all services."
wait

#!/bin/bash
# Script to build all 10 StyleHub microservice Docker images directly inside Minikube

set -e

echo "🐳 Pointing Docker CLI to Minikube Docker Daemon..."
eval $(minikube -p minikube docker-env)

echo "🔨 Building StyleHub Microservices Container Images..."

docker build -t stylehub/frontend:latest ./src/frontend
docker build -t stylehub/product-catalog-service:latest ./src/product_catalog_service
docker build -t stylehub/cart-service:latest ./src/cart_service
docker build -t stylehub/currency-service:latest ./src/currency_service
docker build -t stylehub/recommendation-service:latest ./src/recommendation_service
docker build -t stylehub/shipping-service:latest ./src/shipping_service
docker build -t stylehub/checkout-service:latest ./src/checkout_service
docker build -t stylehub/ad-service:latest ./src/ad_service
docker build -t stylehub/email-service:latest ./src/email_service
docker build -t stylehub/payment-service:latest ./src/payment_service

echo "✅ All 10 StyleHub Container Images Successfully Built inside Minikube!"

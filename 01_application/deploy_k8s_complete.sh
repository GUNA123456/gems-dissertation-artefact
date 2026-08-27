#!/bin/bash
# Automated complete deployment script for StyleHub, Prometheus, Grafana, and Chaos Mesh on Minikube

set -e

echo "🐳 Building microservice container images inside Minikube..."
./build_k8s_images.sh

echo "📦 Deploying StyleHub REST Microservices via Helm..."
helm install stylehub ./stylehub-helm

echo "🌀 Deploying Chaos Mesh Operator..."
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --set chaosDaemon.runtime=docker --set chaosDaemon.socketPath=/var/run/docker.sock

echo "📊 Deploying Prometheus Monitoring Stack..."
helm install prometheus prometheus-community/prometheus -n monitoring --create-namespace

echo "📈 Deploying Grafana Dashboard..."
kubectl apply -f "/Users/gunadeep/second brain/01_Projects_Manual/GEMS_Model_Sandbox/grafana-datasources-configmap.yaml"
kubectl apply -f "/Users/gunadeep/second brain/01_Projects_Manual/GEMS_Model_Sandbox/grafana-deployment.yaml"

echo "🎉 Complete Kubernetes Environment Successfully Deployed!"

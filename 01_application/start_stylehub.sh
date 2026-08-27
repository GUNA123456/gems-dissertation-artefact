#!/bin/bash
# ============================================================
#  StyleHub - Persistent Port-Forward Manager
#  Starts all port-forwards and auto-restarts them if they die
#  Usage: ./start_stylehub.sh
# ============================================================

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   StyleHub Persistent Port-Forward Manager   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"

# Kill any stale port-forward processes
echo -e "\n${YELLOW}🧹 Cleaning up stale port-forwards...${NC}"
pkill -f "kubectl port-forward" 2>/dev/null && sleep 1 || true

# Stable local port assignments
FRONTEND_PORT=8088
PROMETHEUS_PORT=9090
GRAFANA_PORT=30300

echo -e "${GREEN}🚀 Starting port-forwards...${NC}\n"

# Auto-restarting port-forward function
forward() {
  local name=$1
  local svc=$2
  local ns=$3
  local localport=$4
  local remoteport=$5

  while true; do
    echo -e "  ▶ Forwarding ${name} → localhost:${localport}"
    kubectl port-forward "svc/${svc}" -n "${ns}" "${localport}:${remoteport}" \
      --pod-running-timeout=30s 2>/dev/null || true
    echo -e "  ⚠️  ${name} port-forward dropped. Restarting in 3s..."
    sleep 3
  done
}

# Launch all in background with auto-restart
forward "StyleHub Storefront" "stylehub-frontend"   "default"    $FRONTEND_PORT   80   &
forward "Prometheus"           "prometheus-server"   "monitoring" $PROMETHEUS_PORT 80   &
forward "Grafana"              "grafana-dashboard"   "monitoring" $GRAFANA_PORT    3000 &

# Wait for port-forwards to establish
sleep 3

echo -e "\n${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ✅ All Services Live!               ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  🛒 StyleHub Storefront : http://localhost:${FRONTEND_PORT}   ║${NC}"
echo -e "${GREEN}║  📊 Prometheus          : http://localhost:${PROMETHEUS_PORT}   ║${NC}"
echo -e "${GREEN}║  📈 Grafana Dashboard   : http://localhost:${GRAFANA_PORT} ║${NC}"
echo -e "${GREEN}║     Username: admin | Password: admin            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "Press Ctrl+C to stop all port-forwards."

# Wait forever — Ctrl+C kills all background jobs
trap 'echo -e "\n🛑 Stopping all port-forwards..."; kill 0' SIGINT SIGTERM
wait

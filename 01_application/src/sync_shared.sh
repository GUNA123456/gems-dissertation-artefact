#!/usr/bin/env bash
# Copies the canonical shared modules from common/ into every service directory.
# Needed because each Dockerfile builds from its own directory only (COPY . .),
# so shared code must physically exist in each build context. Run after editing
# anything in common/ — service-local copies are generated, never edit them.
set -euo pipefail
cd "$(dirname "$0")"

SERVICES=(frontend ad_service cart_service checkout_service currency_service
          email_service payment_service product_catalog_service
          recommendation_service shipping_service)

for svc in "${SERVICES[@]}"; do
  cp common/obs.py "$svc/obs.py"
done
echo "obs.py synced to ${#SERVICES[@]} services"

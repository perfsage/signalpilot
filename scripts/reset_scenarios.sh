#!/bin/bash
# Reset all SignalPilot test scenarios to a clean known-broken state.
# Usage: bash scripts/reset_scenarios.sh
set -euo pipefail

NS="signalpilot-test"
SAMPLES="$(cd "$(dirname "$0")/.." && pwd)/deploy/samples"

echo "=== Resetting SignalPilot test scenarios in namespace: $NS ==="

# Apply all sample manifests
for yaml in "$SAMPLES"/0*.yaml "$SAMPLES"/1*.yaml; do
  [[ -f "$yaml" ]] || continue
  echo "Applying $(basename "$yaml")..."
  kubectl apply -f "$yaml" -n "$NS" 2>&1 | grep -v "^E0" || true
done

echo ""
echo "Waiting 30s for pods to start failing in expected ways..."
sleep 30

echo ""
echo "=== Current pod states ==="
kubectl get pods -n "$NS" --no-headers 2>/dev/null | grep -v "^E0" | sort

echo ""
echo "Reset complete."

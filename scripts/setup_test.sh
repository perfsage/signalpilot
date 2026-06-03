#!/bin/bash
set -e

NAMESPACE="signalpilot-test"
echo "=== Setting up SignalPilot test environment ==="

# Ensure namespace exists
kubectl get ns $NAMESPACE 2>/dev/null || kubectl create ns $NAMESPACE

# Apply RBAC
kubectl apply -f deploy/signalpilot-rbac.yaml

# Deploy all scenario apps
echo "Deploying test scenarios..."
kubectl apply -f deploy/samples/04-imagepull.yaml
kubectl apply -f deploy/samples/06-unschedulable.yaml
kubectl apply -f deploy/samples/05-probe-fail.yaml
kubectl apply -f deploy/samples/03-crashloop.yaml
kubectl apply -f deploy/samples/02-cpu-throttle.yaml

# Deploy regression v1 first
echo "Deploying regression scenario v1 (healthy)..."
kubectl apply -f deploy/samples/07-regression-v1.yaml

echo "Waiting 20s for v1 to stabilize..."
sleep 20

# Roll to v2 (broken)
echo "Deploying regression scenario v2 (broken - returns 500s)..."
kubectl apply -f deploy/samples/07-regression-v2.yaml

# DNS failure
kubectl apply -f deploy/samples/09-dns-failure.yaml

echo "Waiting for rollout..."
kubectl rollout status deployment/sp-test-regression -n $NAMESPACE --timeout=120s 2>/dev/null || true
kubectl rollout status deployment/sp-test-crash -n $NAMESPACE --timeout=60s 2>/dev/null || true

echo "=== Pod status ==="
kubectl get pods -n $NAMESPACE

echo "=== Setup complete ==="
echo "Run: signalpilot analyze $NAMESPACE --output report.html"
echo "Or:  python3 scripts/run_e2e.sh"

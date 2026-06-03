#!/bin/bash
set -e

NAMESPACE="signalpilot-test"
PYTHON="/Users/aashu/.local/bin/python3.12"
PASS=0
FAIL=0

run_test() {
  local name="$1"
  local deployment="$2"
  local expected_rule="$3"
  
  echo ""
  echo "--- TEST: $name ---"
  
  output=$($PYTHON -m signalpilot analyze "$NAMESPACE" --deployment "$deployment" --quiet 2>&1 || true)
  
  if echo "$output" | grep -qi "$expected_rule" 2>/dev/null; then
    echo "✅ PASS: $name"
    PASS=$((PASS+1))
  else
    # Also check via Python directly
    check=$($PYTHON -c "
from signalpilot.cli import _run_analysis
from signalpilot.config import get_settings
from kubernetes import config as kc
try:
    kc.load_kube_config()
    a = _run_analysis('$NAMESPACE', '$deployment', None, False, None, True)
    rules = [f.rule_id for f in a.findings]
    print(','.join(rules))
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1)
    
    if echo "$check" | grep -q "$expected_rule"; then
      echo "✅ PASS: $name (rule: $expected_rule found in: $check)"
      PASS=$((PASS+1))
    else
      echo "❌ FAIL: $name - expected rule '$expected_rule', got: $check"
      FAIL=$((FAIL+1))
    fi
  fi
}

echo "=== SignalPilot E2E Test Suite ==="
echo "Namespace: $NAMESPACE"
echo ""

# Wait for pods to reach broken state
echo "Waiting 30s for pods to enter broken states..."
sleep 30

run_test "ImagePull scenario" "sp-test-imagepull" "image_pull_error"
run_test "CrashLoop scenario" "sp-test-crash" "crash_loop"
run_test "Probe failure scenario" "sp-test-probe" "probe_failure"
run_test "Unschedulable scenario" "sp-test-unschedulable" "pending_unschedulable"
run_test "Regression v2 scenario" "sp-test-regression" "code_regression"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
exit $FAIL

#!/bin/bash
# Capture HTML report, JSON dump, console output, and timing for every scenario.
# Usage: bash scripts/capture_all_evidence.sh [--skip-wait]
set -euo pipefail

PYTHON="/Users/aashu/.local/bin/python3.12"
NS="signalpilot-test"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE_DIR="$REPO_ROOT/evidence"
mkdir -p "$EVIDENCE_DIR"

SKIP_WAIT="${1:-}"

capture() {
  local name="$1"
  local deployment="$2"
  shift 2
  local extra_args=("$@")

  echo ""
  echo "========================================="
  echo "Capturing: $name  →  $deployment"
  echo "========================================="

  local start=$SECONDS

  set +e
  "$PYTHON" -m signalpilot analyze "$NS" \
    --deployment "$deployment" \
    --output "$EVIDENCE_DIR/${name}_report.html" \
    --json-out "$EVIDENCE_DIR/${name}_analysis.json" \
    "${extra_args[@]}" \
    2>&1 | tee "$EVIDENCE_DIR/${name}_console.txt"
  local rc=$?
  set -e

  local elapsed=$((SECONDS - start))
  echo "scenario: $name" > "$EVIDENCE_DIR/${name}_timing.txt"
  echo "deployment: $deployment" >> "$EVIDENCE_DIR/${name}_timing.txt"
  echo "detection_time_s: $elapsed" >> "$EVIDENCE_DIR/${name}_timing.txt"
  echo "exit_code: $rc" >> "$EVIDENCE_DIR/${name}_timing.txt"

  if [[ $rc -eq 0 ]]; then
    echo "✅  $name captured in ${elapsed}s"
  else
    echo "⚠️   $name exited $rc (still saved)"
  fi
}

echo "=== SignalPilot Evidence Capture Campaign ==="
echo "Namespace : $NS"
echo "Output    : $EVIDENCE_DIR"
echo ""

if [[ "$SKIP_WAIT" != "--skip-wait" ]]; then
  echo "Waiting 20s for all pods to reach stable broken state..."
  sleep 20
fi

# ── Core scenarios ──────────────────────────────────────────────────────────
capture "imagepull"          "sp-test-imagepull"
capture "crashloop"          "sp-test-crash"
capture "probe_fail"         "sp-test-probe"
capture "unschedulable"      "sp-test-unschedulable"
capture "regression_500"     "sp-test-regression"
capture "dns_failure"        "sp-test-dns"
capture "memory_leak"        "sp-test-memory-leak"
capture "cascading_failure"  "sp-test-cascading"
capture "configmap_missing"  "sp-test-configmap-missing"
capture "init_fail"          "sp-test-init-fail"
capture "latency_prometheus" "sp-test-latency"

# ── Git-correlation demo (uses local repo for commit linkage) ───────────────
capture "git_correlation"    "sp-test-git-demo" "--git-repo" "$REPO_ROOT"

echo ""
echo "=== Evidence capture complete ==="
echo "Reports:"
ls -lh "$EVIDENCE_DIR"/*.html 2>/dev/null || echo "  (none generated)"
echo ""
echo "Run audit:"
echo "  $PYTHON scripts/audit_evidence.py"

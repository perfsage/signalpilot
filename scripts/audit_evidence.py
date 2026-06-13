#!/usr/bin/env python3.12
"""
Audit the evidence/ directory: parse each *_analysis.json and check
that every scenario meets the quality bar required for marketing use.

Quality bar per scenario:
  ✅  top finding confidence >= 0.75
  ✅  evidence has >= 2 items
  ✅  at least 1 fix with a kubectl_snippet
  ✅  HTML report exists
  ✅  JSON analysis exists

Exit code 0 = all pass. Non-zero = failures found.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
EVIDENCE_DIR = REPO_ROOT / "evidence"

SCENARIOS = [
    ("imagepull",          "image_pull_error"),
    ("crashloop",          "crash_loop"),
    ("probe_fail",         "probe_failure"),
    ("unschedulable",      "pending_unschedulable"),
    ("regression_500",     "code_regression"),
    ("dns_failure",        None),              # crash_loop or network_latency
    ("memory_leak",        "oom_killed"),
    ("cascading_failure",  None),              # crash_loop or code_regression
    ("configmap_missing",  "configmap_error"),
    ("init_fail",          None),              # init_container_fail or crash_loop
    ("latency_prometheus", "latency_spike"),
    ("git_correlation",    "code_regression"),
]

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "


def audit_scenario(name: str, expected_rule: str | None) -> tuple[bool, list[str]]:
    issues: list[str] = []
    html = EVIDENCE_DIR / f"{name}_report.html"
    json_path = EVIDENCE_DIR / f"{name}_analysis.json"

    if not html.exists():
        issues.append("HTML report missing")
    if not json_path.exists():
        issues.append("JSON analysis missing — scenario may not have run")
        return False, issues

    try:
        data = json.loads(json_path.read_text())
    except Exception as e:
        issues.append(f"Cannot parse JSON: {e}")
        return False, issues

    findings = data.get("findings", [])
    if not findings:
        issues.append("No findings generated")
        return False, issues

    top = findings[0]
    conf = top.get("confidence", 0)
    evidence = top.get("evidence", [])
    fixes = top.get("fixes", [])
    rule_id = top.get("rule_id", "")

    if expected_rule and rule_id != expected_rule:
        issues.append(f"Top rule_id='{rule_id}' expected='{expected_rule}'")

    if conf < 0.75:
        issues.append(f"confidence {conf:.0%} < 75%")

    if len(evidence) < 2:
        issues.append(f"evidence count {len(evidence)} < 2")

    has_kubectl = any(f.get("kubectl_snippet") for f in fixes)
    if not has_kubectl:
        issues.append("no fix has kubectl_snippet")

    return len(issues) == 0, issues


def main() -> int:
    if not EVIDENCE_DIR.exists():
        print(f"{FAIL} evidence/ directory not found. Run: bash scripts/capture_all_evidence.sh")
        return 1

    passed = 0
    failed = 0
    rows: list[str] = []

    for name, expected_rule in SCENARIOS:
        ok, issues = audit_scenario(name, expected_rule)
        icon = PASS if ok else FAIL
        if ok:
            passed += 1
            rows.append(f"  {icon}  {name:<25}  (rule: {expected_rule or 'any'})")
        else:
            failed += 1
            rows.append(f"  {icon}  {name:<25}  ISSUES: {'; '.join(issues)}")

    print("\n=== SignalPilot Evidence Quality Audit ===\n")
    for row in rows:
        print(row)
    print(f"\nResult: {passed} passed, {failed} failed out of {len(SCENARIOS)}")

    if failed == 0:
        print("\n🎉 All scenarios meet the evidence quality bar!")
    else:
        print(f"\n⚠️  {failed} scenario(s) need fixing before marketing use.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

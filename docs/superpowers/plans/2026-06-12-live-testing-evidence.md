# SignalPilot Live Testing & Evidence Campaign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Fix all SignalPilot pipeline gaps that prevent rich cross-source evidence, then run 14 live K8s failure scenarios and capture HTML reports + console output for marketing/blog use.

**Architecture:** Three layers — (1) pipeline fixes so LogCluster+GitChange evidence actually appears in findings, (2) rich scenario manifests covering 9 failure dimensions, (3) automated evidence capture generating a self-contained `evidence/` package per scenario.

**Tech Stack:** Python 3.12, K3s v1.22 (rancher-desktop), kubectl, helm, Prometheus, typer/rich CLI, Jinja2 HTML reports

---

## Failure Dimensions Covered

| # | Dimension | Scenarios |
|---|-----------|-----------|
| 1 | Application crash | crashloop (missing env), init-container failure |
| 2 | Resource exhaustion | OOM kill (hard), memory leak (gradual), CPU throttle |
| 3 | Config errors | missing ConfigMap mount, bad image tag, wrong probe path |
| 4 | Network/DNS | DNS failure loop, endpoint not ready, inter-service timeout |
| 5 | Code regression | 500 error regression (v1→v2), latency regression |
| 6 | Cascading failure | service-B depends on service-A; A goes down → B errors |
| 7 | Scheduling | unschedulable pod |
| 8 | Cross-source correlation demo | 3-way evidence: git + log cluster + metric signal |
| 9 | Prometheus-enriched | HTTP error rate + p95 latency via Prometheus RED metrics |

---

## Evidence Artifacts Per Scenario

Each scenario produces under `evidence/`:
- `SCENARIO_report.html` — self-contained HTML report
- `SCENARIO_console.txt` — Rich table + narrative captured as text
- `SCENARIO_analysis.json` — full Analysis JSON dump
- `SCENARIO_timing.txt` — seconds from deploy to detection

Marketing targets:
- **"8 seconds from deploy to root cause"** (timing_*.txt)
- **"3 independent signal sources, 1 finding"** (3way_* report)
- **"Traced the regression to commit deadbeef"** (git_correlation_* report)
- **"p95 tripled — here's exactly why"** (prometheus_latency_* report)

---

## File Structure

```
deploy/samples/
  01-oom.yaml                   (existing - keep)
  02-cpu-throttle.yaml          (existing - keep)
  03-crashloop.yaml             (existing - keep)
  04-imagepull.yaml             (existing - keep)
  05-probe-fail.yaml            (existing - keep)
  06-unschedulable.yaml         (existing - keep)
  07-regression-v1.yaml         (FIX: use ConfigMap for multi-line script)
  07-regression-v2.yaml         (FIX: same - v2 returns 500s + error logs)
  08-slow-transaction.yaml      (FIX: use ConfigMap, add /metrics endpoint)
  09-dns-failure.yaml           (FIX: use ConfigMap for stable loop)
  11-memory-leak.yaml           (NEW: gradual allocation, detectable before OOM)
  12-cascading-failure.yaml     (NEW: service-B depends on service-A, A dies)
  13-configmap-missing.yaml     (NEW: references nonexistent ConfigMap)
  14-init-container-fail.yaml   (NEW: init container fails → pod stuck)
  15-latency-prometheus.yaml    (NEW: serves /metrics, p95 spike visible in Prom)
  16-git-correlation-demo.yaml  (NEW: image tag is a git SHA, shows commit linkage)

src/signalpilot/collectors/logs.py
  + collect_raw(ns, deployment) -> dict[str, str]   (NEW method)
  + collect_previous(ns, deployment) -> str          (NEW: prev container logs)

src/signalpilot/cli.py
  _run_analysis()  — FIX: properly collect before_logs + after_logs
                   — FIX: collect_previous() for crashloop pods
                   — FIX: include deploy_change even when no prior revision

src/signalpilot/collectors/registry.py
  register_defaults()  — FIX: include PrometheusCollector + CAdvisorCollector

src/signalpilot/rca/rules.py
  rule_code_regression()  — ENHANCE: attach log clusters as evidence
  rule_crash_loop()       — ENHANCE: attach previous-log patterns as evidence

evidence/
  README.md               (scenario index with marketing angles)
  (per-scenario files generated at runtime)

scripts/
  capture_all_evidence.sh  (NEW: runs all scenarios, saves evidence package)
  reset_scenarios.sh       (NEW: clean slate - delete+redeploy all scenarios)
```

---

## Task 1: Fix `LogsCollector` — add `collect_raw()` and `collect_previous()`

**Files:**
- Modify: `src/signalpilot/collectors/logs.py`
- Test: `tests/unit/test_collectors_logs.py`

- [ ] **Step 1: Write the failing tests**

```python
# In tests/unit/test_collectors_logs.py — add to TestLogsCollector class

def test_collect_raw_returns_dict(self):
    """collect_raw returns dict with 'current' key containing log text."""
    # mock list_namespaced_pod and read_namespaced_pod_log
    ...

def test_collect_previous_returns_previous_logs(self):
    """collect_previous reads logs from last terminated container."""
    ...
```

- [ ] **Step 2: Implement `collect_raw()` in `logs.py`**

Add after `collect()` method:
```python
def collect_raw(
    self,
    namespace: str,
    deployment: Optional[str] = None,
) -> dict[str, str]:
    """
    Return raw log text per pod/container as a flat combined string.
    Used by the CLI for drain3 log clustering.
    
    Returns:
        {"current": "<all current logs concatenated>",
         "previous": "<all previous terminated container logs concatenated>"}
    """
    api = self._get_api()
    label_selector = f"app={deployment}" if deployment else None
    pod_list = api.list_namespaced_pod(
        namespace=namespace, label_selector=label_selector
    )
    current_parts: list[str] = []
    previous_parts: list[str] = []

    for pod in pod_list.items:
        pod_name = pod.metadata.name
        containers = (pod.spec.containers if pod.spec and pod.spec.containers else [])
        for container in containers:
            # Current logs
            try:
                log = api.read_namespaced_pod_log(
                    name=pod_name, namespace=namespace,
                    container=container.name, tail_lines=self._tail_lines,
                )
                if log:
                    current_parts.append(redact_secrets(log))
            except Exception:
                pass
            # Previous terminated container logs
            try:
                prev_log = api.read_namespaced_pod_log(
                    name=pod_name, namespace=namespace,
                    container=container.name, previous=True,
                    tail_lines=self._tail_lines,
                )
                if prev_log:
                    previous_parts.append(redact_secrets(prev_log))
            except Exception:
                pass

    return {
        "current": "\n".join(current_parts),
        "previous": "\n".join(previous_parts),
    }
```

- [ ] **Step 3: Run tests**
```bash
/Users/aashu/.local/bin/python3.12 -m pytest tests/unit/test_collectors_logs.py -v
```
Expected: all tests pass

- [ ] **Step 4: Commit**
```bash
git add src/signalpilot/collectors/logs.py tests/unit/test_collectors_logs.py
git commit -m "feat: add collect_raw() and collect_previous() to LogsCollector"
```

---

## Task 2: Fix `_run_analysis()` in CLI — wire log clustering properly

**Files:**
- Modify: `src/signalpilot/cli.py` (lines 85-95)

- [ ] **Step 1: Replace log collection block in `_run_analysis()`**

Replace lines 85–95 with:
```python
# 3. Collect logs for clustering (before = previous terminated, after = current)
log_collector = LogsCollector(settings)
raw = {}
try:
    raw = log_collector.collect_raw(namespace, deployment)
except Exception:
    pass
before_logs = raw.get("previous", "")
after_logs = raw.get("current", "")
log_clusters = cluster_logs(before_logs, after_logs) if (before_logs or after_logs) else []
```

- [ ] **Step 2: Verify locally**
```bash
/Users/aashu/.local/bin/python3.12 -c "
from kubernetes import config as kc; kc.load_kube_config()
from signalpilot.cli import _run_analysis
a = _run_analysis('signalpilot-test', 'sp-test-crash', None, False, None, True)
print('log_clusters:', len(a.log_clusters))
print('evidence_types:', {type(ev).__name__ for f in a.findings for ev in f.evidence})
"
```
Expected: `log_clusters: N` (>0), `evidence_types: {'Signal', 'LogCluster'}` (if new errors in current logs)

- [ ] **Step 3: Commit**
```bash
git add src/signalpilot/cli.py
git commit -m "fix: wire log clustering in _run_analysis using previous+current logs"
```

---

## Task 3: Fix `register_defaults()` — add Prometheus + cAdvisor

**Files:**
- Modify: `src/signalpilot/collectors/registry.py`

- [ ] **Step 1: Read current register_defaults()**

- [ ] **Step 2: Add PrometheusCollector and CAdvisorCollector**

In `register_defaults()`, add:
```python
from signalpilot.collectors.prometheus import PrometheusCollector
from signalpilot.collectors.cadvisor import CAdvisorCollector
from signalpilot.collectors.network import NetworkCollector

for CollectorCls in [
    KubeApiCollector, EventsCollector, MetricsServerCollector,
    LogsCollector, DeployCollector, NetworkCollector,
    CAdvisorCollector, PrometheusCollector,
]:
    c = CollectorCls(self._settings)
    if c.is_available():
        self.register(c)
```

- [ ] **Step 3: Verify sources_used includes prometheus when available**
```bash
/Users/aashu/.local/bin/python3.12 -c "
from kubernetes import config as kc; kc.load_kube_config()
from signalpilot.cli import _run_analysis
a = _run_analysis('signalpilot-test', 'sp-test-imagepull', None, False, None, True)
print('sources_used:', a.sources_used)
"
```

- [ ] **Step 4: Commit**
```bash
git add src/signalpilot/collectors/registry.py
git commit -m "fix: include PrometheusCollector and CAdvisorCollector in register_defaults"
```

---

## Task 4: Fix broken scenario manifests — regression v2 and dns-failure

**Problem:** The Python one-liner with multi-line strings in `command:` args doesn't work reliably in K8s. Use ConfigMaps instead.

**Files:**
- Modify: `deploy/samples/07-regression-v2.yaml`
- Modify: `deploy/samples/09-dns-failure.yaml`
- Modify: `deploy/samples/08-slow-transaction.yaml`

- [ ] **Step 1: Fix `07-regression-v2.yaml`**

Replace with ConfigMap-backed approach:
```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: sp-regression-v2-script
  namespace: signalpilot-test
data:
  app.py: |
    import http.server, sys

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                raise ValueError("NullPointerException: order is None at payments.Service.processOrder line 142")
            except Exception as e:
                print(f"ERROR {e}", flush=True)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Internal Server Error")
        def log_message(self, *args): pass

    http.server.HTTPServer(("", 8080), Handler).serve_forever()
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sp-test-regression
  namespace: signalpilot-test
  labels:
    app: sp-test-regression
    app.kubernetes.io/version: "v2.0.0"
    git-commit: "deadbeef1234567890deadbeef1234567890dead"
spec:
  replicas: 2
  selector:
    matchLabels:
      app: sp-test-regression
  template:
    metadata:
      labels:
        app: sp-test-regression
        app.kubernetes.io/version: "v2.0.0"
        git-commit: "deadbeef1234567890deadbeef1234567890dead"
    spec:
      volumes:
      - name: script
        configMap:
          name: sp-regression-v2-script
      containers:
      - name: app
        image: python:3.11-slim
        command: ["python3", "/scripts/app.py"]
        volumeMounts:
        - name: script
          mountPath: /scripts
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: "50m"
            memory: "64Mi"
          limits:
            cpu: "500m"
            memory: "128Mi"
---
apiVersion: v1
kind: Service
metadata:
  name: sp-test-regression
  namespace: signalpilot-test
spec:
  selector:
    app: sp-test-regression
  ports:
  - port: 8080
    targetPort: 8080
```

- [ ] **Step 2: Fix `09-dns-failure.yaml`** — similar ConfigMap approach

- [ ] **Step 3: Fix `08-slow-transaction.yaml`** — add `/metrics` endpoint for Prometheus scraping

- [ ] **Step 4: Apply and verify pods run (not crash)**
```bash
kubectl apply -f deploy/samples/07-regression-v2.yaml -n signalpilot-test
kubectl rollout status deployment/sp-test-regression -n signalpilot-test --timeout=60s
kubectl logs -l app=sp-test-regression -n signalpilot-test | head -5
```
Expected: pods Running, logs show `ERROR NullPointerException...`

- [ ] **Step 5: Commit**
```bash
git add deploy/samples/07-regression-v2.yaml deploy/samples/09-dns-failure.yaml deploy/samples/08-slow-transaction.yaml
git commit -m "fix: use ConfigMap-backed scripts for regression/dns/slow scenarios"
```

---

## Task 5: Add new high-value scenarios

**Files:**
- Create: `deploy/samples/11-memory-leak.yaml`
- Create: `deploy/samples/12-cascading-failure.yaml`
- Create: `deploy/samples/13-configmap-missing.yaml`
- Create: `deploy/samples/14-init-container-fail.yaml`
- Create: `deploy/samples/15-latency-prometheus.yaml`
- Create: `deploy/samples/16-git-correlation-demo.yaml`

- [ ] **Step 1: Create `11-memory-leak.yaml`**

A script that allocates 10MB every 5 seconds — hits 64Mi limit in ~35s:
```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: sp-memory-leak-script
  namespace: signalpilot-test
data:
  app.py: |
    import time, sys
    leak = []
    while True:
        leak.append(b'x' * 10 * 1024 * 1024)  # 10MB every 5s
        used = sum(len(b) for b in leak)
        print(f"INFO allocated {used // (1024*1024)}MB total", flush=True)
        time.sleep(5)
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sp-test-memory-leak
  namespace: signalpilot-test
  labels:
    app: sp-test-memory-leak
    scenario: memory-leak
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sp-test-memory-leak
  template:
    metadata:
      labels:
        app: sp-test-memory-leak
    spec:
      volumes:
      - name: script
        configMap:
          name: sp-memory-leak-script
      containers:
      - name: app
        image: python:3.11-slim
        command: ["python3", "/scripts/app.py"]
        volumeMounts:
        - name: script
          mountPath: /scripts
        resources:
          requests:
            memory: "32Mi"
            cpu: "10m"
          limits:
            memory: "64Mi"   # tight limit → OOM in ~35s
            cpu: "100m"
```

- [ ] **Step 2: Create `12-cascading-failure.yaml`**

Service B depends on Service A. Deploy A (healthy), then B (depends on A). Then kill A. B shows connection errors.

- [ ] **Step 3: Create `13-configmap-missing.yaml`**

References a ConfigMap that doesn't exist → pod stuck in `CreateContainerConfigError`:
```yaml
volumes:
- name: config
  configMap:
    name: sp-nonexistent-config-99999
```

- [ ] **Step 4: Create `14-init-container-fail.yaml`**

Init container fails with non-zero exit → pod stuck in `Init:Error`:
```yaml
initContainers:
- name: init-checker
  image: python:3.11-slim
  command: ["python3", "-c", "import sys; sys.exit(1)"]
```

- [ ] **Step 5: Create `15-latency-prometheus.yaml`**

A service that serves both HTTP traffic and `/metrics` (prometheus_client), with artificial latency that makes p95 spike:
```python
# Uses prometheus_client to expose:
# http_request_duration_seconds_bucket{} histogram
# Adds 2-second delay to 20% of requests
```

- [ ] **Step 6: Create `16-git-correlation-demo.yaml`**

Uses the local SignalPilot git repo SHA as the image label. When run with `--git-repo .`, SignalPilot traces the regression to a real commit.

- [ ] **Step 7: Apply all new scenarios**
```bash
kubectl apply -f deploy/samples/11-memory-leak.yaml
kubectl apply -f deploy/samples/12-cascading-failure.yaml
kubectl apply -f deploy/samples/13-configmap-missing.yaml
kubectl apply -f deploy/samples/14-init-container-fail.yaml
kubectl apply -f deploy/samples/15-latency-prometheus.yaml
kubectl apply -f deploy/samples/16-git-correlation-demo.yaml
```

- [ ] **Step 8: Commit**
```bash
git add deploy/samples/1*.yaml deploy/samples/16-git-correlation-demo.yaml
git commit -m "feat: add memory-leak, cascading-failure, configmap-missing, init-fail, latency-prom, git-demo scenarios"
```

---

## Task 6: Add new RCA rules for new scenarios

**Files:**
- Modify: `src/signalpilot/rca/rules.py`
- Modify: `src/signalpilot/models.py` (add SignalKind.CONFIGMAP_ERROR, INIT_ERROR if needed)

- [ ] **Step 1: Add `rule_configmap_error`**

Triggered by K8s event `CreateContainerConfigError`:
```python
def rule_configmap_error(ctx: RcaContext) -> list[Finding]:
    """Missing/invalid ConfigMap or Secret mount → pod stuck."""
    event_sigs = [s for s in ctx.signals_by_kind(SignalKind.EVENT)
                  if any(kw in s.message for kw in ("ConfigError", "CreateContainerConfigError", "configmap", "secret"))]
    ...
```

- [ ] **Step 2: Add `rule_init_container_fail`**

Triggered by pod in `Init:Error` / `Init:CrashLoopBackOff` phase.

- [ ] **Step 3: Enhance `rule_code_regression` to attach log cluster evidence**

Currently LogCluster evidence isn't attached. Add:
```python
# attach the new_error_clusters directly as evidence
evidence: list = list(new_error_clusters[:3])
```

- [ ] **Step 4: Add unit tests for new rules**

- [ ] **Step 5: Run unit tests**
```bash
/Users/aashu/.local/bin/python3.12 -m pytest tests/unit/ -q
```
Expected: all pass

- [ ] **Step 6: Commit**
```bash
git add src/signalpilot/rca/rules.py tests/unit/test_rca_rules.py
git commit -m "feat: add configmap-error and init-fail rules; attach LogCluster to code_regression evidence"
```

---

## Task 7: Evidence capture infrastructure

**Files:**
- Create: `scripts/capture_all_evidence.sh`
- Create: `scripts/reset_scenarios.sh`
- Create: `evidence/README.md`
- Modify: `src/signalpilot/cli.py` — add `--json-out` flag to `analyze` command

- [ ] **Step 1: Add `--json-out` flag to `analyze` command in `cli.py`**

```python
json_out: Optional[Path] = typer.Option(None, "--json-out", help="Write JSON analysis dump to this path"),
```

In `analyze()` body:
```python
if json_out:
    json_out.write_text(analysis.model_dump_json(indent=2))
```

- [ ] **Step 2: Create `scripts/capture_all_evidence.sh`**

```bash
#!/bin/bash
set -e
PYTHON="/Users/aashu/.local/bin/python3.12"
NS="signalpilot-test"
EVIDENCE_DIR="$(pwd)/evidence"
mkdir -p "$EVIDENCE_DIR"

capture() {
  local name="$1"
  local deployment="$2"
  local extra_args="${3:-}"
  
  echo ""
  echo "========================================="
  echo "Capturing: $name ($deployment)"
  echo "========================================="
  
  local start=$SECONDS
  
  $PYTHON -m signalpilot analyze "$NS" \
    --deployment "$deployment" \
    --output "$EVIDENCE_DIR/${name}_report.html" \
    --json-out "$EVIDENCE_DIR/${name}_analysis.json" \
    $extra_args \
    2>&1 | tee "$EVIDENCE_DIR/${name}_console.txt"
  
  local elapsed=$((SECONDS - start))
  echo "Detection time: ${elapsed}s" > "$EVIDENCE_DIR/${name}_timing.txt"
  echo "✅ $name: captured in ${elapsed}s"
}

echo "=== SignalPilot Evidence Capture ==="
echo "Namespace: $NS"
echo "Output: $EVIDENCE_DIR"
echo ""

# Wait for scenarios to settle
echo "Waiting 15s for all pods to reach stable broken state..."
sleep 15

capture "imagepull"           "sp-test-imagepull"
capture "crashloop"           "sp-test-crash"
capture "probe_fail"          "sp-test-probe"
capture "unschedulable"       "sp-test-unschedulable"
capture "regression_500"      "sp-test-regression"
capture "dns_failure"         "sp-test-dns"
capture "memory_leak"         "sp-test-memory-leak"
capture "cascading_failure"   "sp-test-cascading"
capture "configmap_missing"   "sp-test-configmap-missing"
capture "init_fail"           "sp-test-init-fail"
capture "latency_prometheus"  "sp-test-latency"

# Git correlation demo (uses local repo as git source)
capture "git_correlation"     "sp-test-git-demo" "--git-repo ."

echo ""
echo "=== Evidence capture complete ==="
echo "Reports: $EVIDENCE_DIR/"
ls -lh "$EVIDENCE_DIR/"*.html 2>/dev/null
```

- [ ] **Step 3: Create `evidence/README.md`** — scenario index

- [ ] **Step 4: Add `evidence/` to `.gitignore` (large HTML files)**

- [ ] **Step 5: Commit**
```bash
git add scripts/capture_all_evidence.sh scripts/reset_scenarios.sh evidence/README.md .gitignore
git commit -m "feat: evidence capture infrastructure - scripts and evidence directory"
```

---

## Task 8: Dev→Test→Dev loop — run all scenarios and fix gaps

**This is an iterative task. For each scenario, run → check finding accuracy + evidence richness → fix if wrong → re-run.**

- [ ] **Step 1: Reset all scenarios to clean state**
```bash
bash scripts/reset_scenarios.sh
sleep 60
```

- [ ] **Step 2: Run evidence capture**
```bash
bash scripts/capture_all_evidence.sh
```

- [ ] **Step 3: Verify each scenario**

For each scenario, check:
```python
# Run this audit script
python3 scripts/audit_evidence.py
```

Required quality bar per scenario:
- ✅ Top finding matches expected rule_id
- ✅ confidence >= 0.75
- ✅ evidence has >= 2 items
- ✅ at least 1 fix with kubectl_snippet
- ✅ HTML report opens and looks beautiful

- [ ] **Step 4: Fix any failing scenarios** (up to 3 retries per scenario)

- [ ] **Step 5: Run full unit test suite to ensure no regressions**
```bash
/Users/aashu/.local/bin/python3.12 -m pytest tests/unit/ tests/e2e/ -q
```

- [ ] **Step 6: Final commit**
```bash
git add -A
git commit -m "fix: all 12 scenarios pass evidence quality bar"
```

---

## Scenario Quick-Reference

| # | Scenario name | Deployment | Expected top rule | Expected evidence types |
|---|---------------|-----------|-------------------|------------------------|
| 1 | imagepull | sp-test-imagepull | image_pull_error | Signal (K8s event + kube_api) |
| 2 | crashloop | sp-test-crash | crash_loop | Signal + LogCluster (previous logs) |
| 3 | probe_fail | sp-test-probe | probe_failure | Signal (kube_api + events) |
| 4 | unschedulable | sp-test-unschedulable | pending_unschedulable | Signal (kube_api + events) |
| 5 | regression_500 | sp-test-regression | code_regression | Signal + LogCluster (new 500 errors) |
| 6 | dns_failure | sp-test-dns | crash_loop / network_latency | Signal + LogCluster |
| 7 | memory_leak | sp-test-memory-leak | oom_killed | Signal (OOMKilled + mem working-set) |
| 8 | cascading | sp-test-cascading | crash_loop / code_regression | Signal + LogCluster (conn refused) |
| 9 | configmap_missing | sp-test-configmap-missing | crash_loop (configmap_error) | Signal (event: CreateContainerConfigError) |
| 10 | init_fail | sp-test-init-fail | crash_loop | Signal (init error) |
| 11 | latency_prom | sp-test-latency | cpu_throttled / code_regression | Signal + Prometheus (p95 spike) |
| 12 | git_demo | sp-test-git-demo | code_regression | Signal + LogCluster + **GitChange** |

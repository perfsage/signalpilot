# ⚡ PerfSage SignalPilot

> **Open-source Kubernetes RCA copilot** — answers *"why are errors and performance degradation happening after my last deployment?"* by correlating evidence across every signal source into ranked findings with concrete fixes.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![K8s 1.22+](https://img.shields.io/badge/k8s-1.22+-blue.svg)](https://kubernetes.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## How it works

SignalPilot runs a `observe → correlate → explain → recommend → verify → learn` loop:

1. **Observe** — attaches to all available signal sources in parallel: K8s API (pods/events/deployments), metrics-server, container logs, cAdvisor/kubelet (CPU throttling, memory working-set), Prometheus (RED metrics, p95/p99, CFS throttle), network/DNS, and your app's git history.

2. **Correlate** — a deterministic rule engine fuses cross-source evidence. Each finding cites *multiple* signal types (e.g., "OOMKilled + memory working-set at 94% of limit + git commit touching heap allocator = undersized memory limit, 97% confidence").

3. **Explain** — plain-English narrative + per-finding explanations. Optional LLM polish (OpenAI/Anthropic) grounds the narrative in the actual findings.

4. **Recommend** — every finding comes with ranked, copy-paste `kubectl` fixes.

5. **Verify** — save a baseline before a fix, compare after next deploy. "Fixed" vs "Regressed" vs "Unchanged" verdict.

6. **Learn** — revision-keyed historical record in `.signalpilot/`.

## Signal sources (what it attaches to)

| Tier | Source | Always-on? |
|------|--------|-----------|
| 0 | Deploy diff (image/env/resources/probes/configmap) | ✅ |
| 0 | Git repo correlation (commit SHA → changed files → suspect commits) | Optional (`--git-repo`) |
| 1 | K8s API: restarts, OOMKilled, CrashLoopBackOff, ImagePullBackOff, probe failures, pending pods | ✅ |
| 1 | K8s Events: FailedScheduling, BackOff, Unhealthy | ✅ |
| 1 | metrics-server: CPU/memory usage vs limits (saturation) | ✅ |
| 1 | Container logs: drain3 clustering, new-error detection, stacktrace extraction | ✅ |
| 2 | kubelet/cAdvisor: CPU CFS throttling, memory working-set, disk pressure | ✅ |
| 2 | Network: endpoint readiness, DNS failures | ✅ |
| 3 | TCP packet analysis: retransmits, resets, RTT (on-demand tcpdump pod) | `--deep-network` |
| 4 | Prometheus: p95/p99, error rate, CFS throttle ratio, historical baselines | Auto-detect |
| 4 | Loki, OTel/Jaeger traces | Auto-detect |

## RCA rules (what it finds)

| Rule | Trigger signals | Typical fix |
|------|----------------|-------------|
| `oom_killed` | OOMKilled + mem working-set near limit | Raise memory limit |
| `cpu_throttled` | CFS throttle ratio > 30% ± latency regression | Raise CPU limit/request |
| `crash_loop` | CrashLoopBackOff + log patterns + config diff | Check env vars, rollback |
| `image_pull_error` | ImagePullBackOff / ErrImagePull | Fix image tag, rollback |
| `probe_failure` | Readiness/liveness probe failing | Fix probe path/port/timing |
| `pending_unschedulable` | Pending pod + FailedScheduling events | Reduce requests, add capacity |
| `code_regression` | New log fingerprints after deploy ± git suspect commit | Rollback, investigate commit |
| `network_latency` | TCP retransmits + DNS failures | Investigate network policy, CoreDNS |

## Quick start

```bash
git clone https://github.com/perfsage/signalpilot
cd signalpilot
bash install.sh          # creates .venv/, upgrades pip, installs SignalPilot
```

> **`bash install.sh --dev`** also installs test/lint dependencies.
> **`bash install.sh --no-venv`** installs into the currently active environment.

The installer automatically: finds Python 3.12+, creates a virtual environment,
upgrades pip to a version that supports `pyproject.toml` (≥ 21.3), and verifies
the CLI works — with a clear error message and fix instruction if anything goes wrong.

```bash
# Activate the venv on subsequent sessions
source .venv/bin/activate

# Apply RBAC (one-time, read-only cluster access)
kubectl apply -f deploy/signalpilot-rbac.yaml

# Analyze a namespace
signalpilot analyze my-namespace

# Analyze a specific deployment with HTML report
signalpilot analyze my-namespace --deployment my-app --output report.html

# With git correlation
signalpilot analyze my-namespace --deployment my-app --git-repo https://github.com/org/app

# CI/CD gate (exit 1 if HIGH+ findings)
signalpilot gate my-namespace --deployment my-app --junit-xml results.xml

# Start web dashboard
signalpilot serve

# Watch for deploys (auto-analyze)
signalpilot watch my-namespace --output-dir ./reports/
```

## Prerequisites

- Python 3.12+ (`brew install python@3.12` / `sudo apt install python3.12`)
- `kubectl` configured with cluster access
- RBAC: `kubectl apply -f deploy/signalpilot-rbac.yaml`
- Optional: Prometheus (auto-detected at `prometheus-operated:9090` and common cluster URLs)

## Configuration

All settings via env vars (`SIGNALPILOT_*`) or `.env` file:

```bash
SIGNALPILOT_PROMETHEUS_URL=http://prometheus:9090  # explicit Prometheus URL
SIGNALPILOT_LLM_PROVIDER=openai                    # "openai" or "anthropic"
SIGNALPILOT_LLM_API_KEY=sk-...                     # LLM API key for narrative polish
SIGNALPILOT_SLACK_WEBHOOK_URL=https://hooks.slack.com/...
SIGNALPILOT_GATE_SEVERITY_THRESHOLD=high           # CI gate threshold
SIGNALPILOT_BASELINE_WINDOW_S=1800                 # 30 min baseline before deploy
SIGNALPILOT_DATA_DIR=.signalpilot                  # where to store analyses
```

## Architecture

```
signalpilot analyze [namespace] [deployment]
           │
    ┌──────▼──────┐
    │  Collectors  │  K8s API · logs · metrics · cAdvisor · Prometheus · git
    └──────┬──────┘
    ┌──────▼──────┐
    │  Timeline   │  Normalized Signal store (Parquet)
    └──────┬──────┘
    ┌──────▼───────────────┐
    │  Analysis Layer       │
    │  ├─ Regression detect │  IQR + z-score change detection
    │  ├─ Log clustering    │  drain3 fingerprinting, new-error detection
    │  ├─ Topology graph    │  networkx: Deployment→RS→Pod→Service
    │  └─ Git correlation   │  commit SHA → file diff → suspect commits
    └──────┬───────────────┘
    ┌──────▼──────┐
    │  RCA Engine  │  8 deterministic rules, cross-source evidence fusion
    └──────┬──────┘
    ┌──────▼──────┐
    │  Output     │  CLI table · HTML report · Slack · JUnit XML · Web dashboard
    └─────────────┘
```

## Development

```bash
bash install.sh --dev            # creates .venv/ with dev dependencies
source .venv/bin/activate

pytest tests/unit/               # 340 unit tests (no cluster needed)
pytest tests/e2e/                # E2E tests (requires kubectl + sample apps)
bash scripts/reset_scenarios.sh  # deploy 16 test scenarios to signalpilot-test ns
bash scripts/capture_all_evidence.sh  # generate HTML/JSON evidence for all 12 scenarios
python scripts/audit_evidence.py      # verify evidence quality bar
```

## Installing Prometheus (optional, enriches findings)

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --version 45.31.1 \
  --set alertmanager.enabled=false \
  --set grafana.enabled=false \
  --set prometheusOperator.admissionWebhooks.enabled=false \
  --set prometheusOperator.tls.enabled=false \
  --set kubeControllerManager.enabled=false \
  --set kubeScheduler.enabled=false
```

## License

MIT © PerfSage

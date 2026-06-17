# PerfSage SignalPilot

> **Deploy went fine. Errors didn't.**  
> Open-source Kubernetes RCA that answers *"why did errors spike after my last deploy?"* in under five minutes — by correlating deploy diffs, events, metrics, logs, and git into ranked findings with copy-paste `kubectl` fixes.

[![PyPI](https://img.shields.io/pypi/v/perfsage-signalpilot.svg)](https://pypi.org/project/perfsage-signalpilot/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![K8s 1.22+](https://img.shields.io/badge/k8s-1.22+-blue.svg)](https://kubernetes.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Landing page:** [perfsage.com/signalpilot](https://perfsage.com/signalpilot/) · **Sample report:** [examples/sample-report.html](examples/sample-report.html)

---

## Quick start

```bash
pip install perfsage-signalpilot
```

If PyPI is not yet available in your region, install from the [v1.0.0 release](https://github.com/perfsage/signalpilot/releases/tag/v1.0.0):

```bash
pip install https://github.com/perfsage/signalpilot/releases/download/v1.0.0/perfsage_signalpilot-1.0.0-py3-none-any.whl
```

Then:

```bash
kubectl apply -f deploy/signalpilot-rbac.yaml

signalpilot analyze my-namespace --deployment my-app --output report.html
```

**CI gate** (exit 1 on HIGH+ findings):

```bash
signalpilot gate my-namespace --deployment my-app --junit-xml results.xml
```

From source:

```bash
git clone https://github.com/perfsage/signalpilot
cd signalpilot && pip install -e .
```

---

## Why SignalPilot?

| | kubectl | Grafana / APM | SignalPilot |
|---|---------|---------------|-------------|
| **Deploy context** | One object at a time | Metrics without diff | Deploy diff fused into every finding |
| **Cross-source evidence** | Manual tab-switching | Separate dashboards | Events + metrics + logs + git in one report |
| **Actionable output** | Raw YAML/events | Charts | Ranked findings + copy-paste `kubectl` fixes |
| **Post-deploy RCA time** | Hours (typical war room) | Still manual correlation | Under 5 minutes for typical regressions |
| **Cluster agents** | N/A | Often required | Read-only RBAC only — no app pod agents |
| **Cost** | Free | Enterprise tiers | MIT open source |

Not another dashboard. **Analysis you can act on.** Core RCA uses deterministic rules — optional LLM polish only if you want it.

---

## How it works

SignalPilot runs `observe → correlate → explain → recommend → verify → learn`:

1. **Observe** — parallel collectors across K8s API, metrics-server, logs, cAdvisor, Prometheus, network, and optional git
2. **Correlate** — deterministic rules fuse cross-source evidence (e.g. OOMKilled + memory at 94% of limit + git commit touching heap code → undersized memory limit)
3. **Explain** — plain-English narrative per finding; optional LLM polish
4. **Recommend** — ranked, copy-paste `kubectl` fixes
5. **Verify** — baseline before fix, compare after next deploy: Fixed / Regressed / Unchanged
6. **Learn** — revision-keyed history in `.signalpilot/`

---

## Signal sources

| Tier | Source | Always-on? |
|------|--------|-----------|
| 0 | Deploy diff (image/env/resources/probes/configmap) | Yes |
| 0 | Git repo correlation (commit SHA → suspect commits) | Optional (`--git-repo`) |
| 1 | K8s API: restarts, OOMKilled, CrashLoopBackOff, probes | Yes |
| 1 | K8s Events: FailedScheduling, BackOff, Unhealthy | Yes |
| 1 | metrics-server: CPU/memory saturation vs limits | Yes |
| 1 | Container logs: drain3 clustering, new-error detection | Yes |
| 2 | kubelet/cAdvisor: CPU throttling, memory working-set | Yes |
| 2 | Network: endpoint readiness, DNS failures | Yes |
| 4 | Prometheus: p95/p99, error rate, CFS throttle | Auto-detect |
| 4 | Loki, OTel/Jaeger traces | Auto-detect |

---

## RCA rules

| Rule | Trigger signals | Typical fix |
|------|----------------|-------------|
| `oom_killed` | OOMKilled + mem working-set near limit | Raise memory limit |
| `cpu_throttled` | CFS throttle ratio > 30% ± latency regression | Raise CPU limit/request |
| `crash_loop` | CrashLoopBackOff + log patterns + config diff | Check env vars, rollback |
| `image_pull_error` | ImagePullBackOff / ErrImagePull | Fix image tag, rollback |
| `probe_failure` | Readiness/liveness probe failing | Fix probe path/port/timing |
| `pending_unschedulable` | Pending pod + FailedScheduling events | Reduce requests, add capacity |
| `code_regression` | New log fingerprints after deploy ± git suspect | Rollback, investigate commit |
| `network_latency` | TCP retransmits + DNS failures | Investigate network policy, CoreDNS |

---

## More commands

```bash
# Git correlation
signalpilot analyze my-namespace --deployment my-app --git-repo https://github.com/org/app

# Web dashboard
signalpilot serve

# Watch for deploys (auto-analyze)
signalpilot watch my-namespace --output-dir ./reports/
```

---

## Prerequisites

- Python 3.12+
- `kubectl` configured with cluster access
- RBAC: `kubectl apply -f deploy/signalpilot-rbac.yaml`
- Optional: Prometheus (auto-detected at common cluster URLs)

---

## Configuration

All settings via env vars (`SIGNALPILOT_*`) or `.env` file:

```bash
SIGNALPILOT_PROMETHEUS_URL=http://prometheus:9090
SIGNALPILOT_LLM_PROVIDER=openai                    # optional
SIGNALPILOT_LLM_API_KEY=sk-...                     # optional
SIGNALPILOT_SLACK_WEBHOOK_URL=https://hooks.slack.com/...
SIGNALPILOT_GATE_SEVERITY_THRESHOLD=high
SIGNALPILOT_BASELINE_WINDOW_S=1800
SIGNALPILOT_DATA_DIR=.signalpilot
```

---

## PerfSage product ladder

1. **[PerfSage Reveal](https://perfsage.com/reveal/)** — JMeter JTL analysis in the lab
2. **[SLO Reporter](https://perfsage.com/slo-plugin/)** — CI gates on load tests
3. **SignalPilot** — post-deploy RCA in production (this repo)

---

## Development

```bash
bash install.sh --dev
source .venv/bin/activate
pytest tests/unit/
pytest tests/e2e/                # requires kubectl + sample apps
bash scripts/reset_scenarios.sh   # deploy 16 test scenarios
```

---

## License

MIT © [PerfSage](https://perfsage.com)

# PerfSage SignalPilot

An open-source Kubernetes RCA (Root Cause Analysis) copilot that answers:

> **"Why are errors / performance regressions happening after the last deployment?"**

## How it works

SignalPilot correlates signals across multiple data sources — deploy diffs, K8s events, metrics, Prometheus, logs, traces, network captures, and git history — to produce ranked **Findings** with concrete **Fixes**.

```
observe → correlate → explain → recommend → verify → learn
```

## Signal sources

| Source | What it collects |
|---|---|
| Kubernetes API | Pod restarts, OOMKills, CrashLoops, probe failures |
| K8s Events | Warning events, node pressure, scheduling failures |
| Metrics Server | CPU/memory resource usage |
| cAdvisor | Container-level resource metrics |
| Prometheus | Custom metrics, error rates, latency percentiles |
| OTel / Jaeger | Distributed traces, span errors |
| Loki | Structured log aggregation |
| Git | Commits, changed files, authors |
| Network | TCP retransmits, DNS latency, packet captures |

## Quick start

```bash
pip install signalpilot
signalpilot analyze --namespace my-app --since 1h
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

Apache 2.0

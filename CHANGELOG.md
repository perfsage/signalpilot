# Changelog

All notable changes to PerfSage SignalPilot are documented here.

## [1.0.0] - 2026-06-17

### Added

- **Launch release** — open-source Kubernetes post-deploy RCA copilot
- `signalpilot analyze` — HTML/CLI report with ranked findings and copy-paste `kubectl` fixes
- `signalpilot gate` — CI gate with JUnit XML export (exit non-zero on HIGH+ findings)
- `signalpilot serve` — web dashboard for interactive RCA
- `signalpilot watch` — auto-analyze on deploy events
- Observe → correlate → explain → recommend → verify → learn loop
- 8 deterministic RCA rules: `oom_killed`, `cpu_throttled`, `crash_loop`, `image_pull_error`, `probe_failure`, `pending_unschedulable`, `code_regression`, `network_latency`
- Parallel collectors: K8s API, events, metrics-server, logs, cAdvisor, network, Prometheus (auto-detect), git (optional)
- Read-only RBAC manifest at `deploy/signalpilot-rbac.yaml` — no agents in app pods
- Optional LLM narrative polish (OpenAI/Anthropic) — core RCA runs without any API key
- 16 deploy sample scenarios under `deploy/samples/` for local testing
- Sample HTML report at `examples/sample-report.html`

### Install

```bash
pip install perfsage-signalpilot
```

PyPI package: [`perfsage-signalpilot`](https://pypi.org/project/perfsage-signalpilot/) · CLI command: `signalpilot`

[1.0.0]: https://github.com/perfsage/signalpilot/releases/tag/v1.0.0

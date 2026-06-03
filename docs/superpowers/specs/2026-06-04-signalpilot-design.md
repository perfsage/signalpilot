# PerfSage SignalPilot — Design Specification

**Date:** 2026-06-04  
**Status:** Implemented  

## Goal

Answer "why are errors/performance-degradation happening after the last deployment?" by correlating K8s signals into ranked RCA findings with concrete fixes.

## Core loop

`observe → correlate → explain → recommend → verify → learn`

## Architecture decisions

1. **Deterministic-first**: All findings produced by rule-based engine, no LLM dependency. LLM is optional narrative polish only.
2. **Read-only safety**: SignalPilot never mutates user workloads. All fixes are suggestions only. Capture pods (tcpdump) are time-boxed and cleaned up.
3. **Tiered collection**: Tier 0 (deploy diff) → Tier 1 (native K8s) → Tier 2 (cAdvisor/kubelet) → Tier 3 (network/packets, on-demand) → Tier 4 (Prometheus/OTel, auto-detect). Each tier enriches findings but is optional.
4. **Cross-source corroboration**: Confidence score = evidence_strength × temporal_proximity × corroborating_source_count. A finding backed by 3 sources ranks higher than one with 1.
5. **Parquet timeline**: All normalized signals stored as Polars DataFrame → Parquet for fast windowing (before/after deploy).

## Data model

- `Signal` — atomic observation from any source (ts, source, kind, severity, target, value, message)
- `LogCluster` — drain3 log template with before/after counts and is_new flag
- `GitChange` — commit range, suspect commits, suspect files
- `Evidence = Signal | LogCluster | GitChange` — discriminated union
- `Finding` — title, severity, confidence, blast_radius, evidence list, fixes list
- `Analysis` — container for all findings, narrative, sources_used

## RCA rule library

8 seed rules: `oom_killed`, `cpu_throttled`, `crash_loop`, `image_pull_error`, `probe_failure`, `pending_unschedulable`, `code_regression`, `network_latency`. Extensible via `ALL_RULES` list in `rca/rules.py`.

## Testing

- 329 unit tests (fixture-based, no cluster)
- 5 E2E tests (live K3s cluster, `signalpilot-test` namespace)
- 9 test scenarios: imagepull, crashloop, probe-fail, unschedulable, regression-500, slow-transaction, dns-failure, oom, cpu-throttle
- Prometheus (kube-prometheus-stack 45.31.1) installed in `monitoring` namespace

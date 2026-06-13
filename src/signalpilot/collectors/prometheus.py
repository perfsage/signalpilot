"""
Prometheus adapter for PerfSage SignalPilot.

Auto-detects Prometheus by trying SIGNALPILOT_PROMETHEUS_URL env var,
then common cluster addresses (prometheus-operated:9090, prometheus:9090,
kube-prometheus-stack-prometheus:9090, etc.).

Collects:
- HTTP request rate, error rate (request_total, if metric exists)
- Latency p95/p99 (histogram_quantile)
- CPU throttle ratio (container_cpu_cfs_throttled_seconds_total)
- Memory working set (container_memory_working_set_bytes)
- Pod restart rate
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from signalpilot.collectors.base import BaseCollector
from signalpilot.config import get_settings
from signalpilot.models import Severity, Signal, SignalKind, SignalSource, Target

COMMON_PROMETHEUS_URLS = [
    "http://prometheus-operated:9090",
    "http://prometheus:9090",
    "http://prometheus-server:9090",
    "http://kube-prometheus-stack-prometheus:9090",
    "http://monitoring-prometheus:9090",
]


class PrometheusCollector(BaseCollector):
    """Collect enriched metrics from Prometheus."""

    name = "prometheus"

    def __init__(self, settings=None):
        self._settings = settings or get_settings()
        self._base_url: Optional[str] = None

    def is_available(self) -> bool:
        """Check if Prometheus is reachable. Cache the URL."""
        urls = []
        if self._settings.prometheus_url:
            urls.append(self._settings.prometheus_url)
        urls.extend(COMMON_PROMETHEUS_URLS)

        for url in urls:
            try:
                r = httpx.get(f"{url}/api/v1/query", params={"query": "up"}, timeout=3.0)
                if r.status_code == 200:
                    self._base_url = url
                    return True
            except Exception:
                continue
        return False

    def collect(
        self, namespace: str, deployment: Optional[str] = None, since_ts: Optional[float] = None
    ) -> list[Signal]:
        if not self._base_url and not self.is_available():
            return []

        signals = []
        signals.extend(self._collect_cpu_throttle(namespace, deployment))
        signals.extend(self._collect_mem_working_set(namespace, deployment))
        signals.extend(self._collect_error_rate(namespace, deployment))
        signals.extend(self._collect_latency(namespace, deployment))
        return signals

    def query(self, promql: str) -> list[dict]:
        """Execute a PromQL instant query. Returns list of result dicts."""
        try:
            r = httpx.get(
                f"{self._base_url}/api/v1/query",
                params={"query": promql},
                timeout=self._settings.prometheus_timeout_s,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("result", [])
        except Exception:
            return []

    def _collect_cpu_throttle(self, namespace: str, deployment: Optional[str]) -> list[Signal]:
        ns_filter = f'namespace="{namespace}"'
        if deployment:
            ns_filter += f', pod=~"{deployment}-.*"'

        results = self.query(
            f'rate(container_cpu_cfs_throttled_seconds_total{{{ns_filter}}}[5m]) / '
            f'rate(container_cpu_cfs_periods_total{{{ns_filter}}}[5m])'
        )

        signals = []
        now = datetime.now(timezone.utc)
        for r in results:
            metric = r.get("metric", {})
            value = float(r.get("value", [0, "0"])[1])
            if value < 0.01:
                continue
            severity = Severity.HIGH if value > 0.3 else Severity.MEDIUM if value > 0.1 else Severity.INFO
            signals.append(Signal(
                type="signal", ts=now,
                source=SignalSource.PROMETHEUS, kind=SignalKind.CPU_THROTTLED,
                severity=severity,
                target=Target(
                    kind="Pod", namespace=namespace,
                    name=metric.get("pod", "unknown"),
                    container=metric.get("container"),
                ),
                value=value,
                message=f"CPU throttle ratio: {value:.1%}",
            ))
        return signals

    def _collect_mem_working_set(self, namespace: str, deployment: Optional[str]) -> list[Signal]:
        ns_filter = f'namespace="{namespace}"'
        if deployment:
            ns_filter += f', pod=~"{deployment}-.*"'

        results = self.query(f'container_memory_working_set_bytes{{{ns_filter}}}')
        signals = []
        now = datetime.now(timezone.utc)
        for r in results:
            metric = r.get("metric", {})
            if not metric.get("container"):
                continue
            value = float(r.get("value", [0, "0"])[1])
            signals.append(Signal(
                type="signal", ts=now,
                source=SignalSource.PROMETHEUS, kind=SignalKind.MEM_WORKING_SET,
                severity=Severity.INFO,
                target=Target(
                    kind="Pod", namespace=namespace,
                    name=metric.get("pod", "unknown"),
                    container=metric.get("container"),
                ),
                value=value,
                message=f"Memory working set: {value / (1024**2):.1f}MB",
            ))
        return signals

    def _collect_error_rate(self, namespace: str, deployment: Optional[str]) -> list[Signal]:
        """Collect HTTP error rate if application metrics exist."""
        ns_filter = f'namespace="{namespace}"'
        queries = [
            f'rate(http_requests_total{{status=~"5..",{ns_filter}}}[5m]) / rate(http_requests_total{{{ns_filter}}}[5m])',
            f'rate(requests_total{{status=~"5..",{ns_filter}}}[5m]) / rate(requests_total{{{ns_filter}}}[5m])',
        ]
        signals = []
        now = datetime.now(timezone.utc)
        for q in queries:
            results = self.query(q)
            for r in results:
                metric = r.get("metric", {})
                value = float(r.get("value", [0, "0"])[1])
                if value < 0.01:
                    continue
                severity = Severity.CRITICAL if value > 0.5 else Severity.HIGH if value > 0.1 else Severity.MEDIUM
                signals.append(Signal(
                    type="signal", ts=now,
                    source=SignalSource.PROMETHEUS, kind=SignalKind.ERROR_RATE,
                    severity=severity,
                    target=Target(
                        kind="Deployment", namespace=namespace,
                        name=metric.get("deployment") or metric.get("pod", "").rsplit("-", 2)[0] or "unknown",
                    ),
                    value=value,
                    message=f"HTTP error rate: {value:.1%}",
                ))
            if signals:
                break
        return signals

    def _collect_latency(self, namespace: str, deployment: Optional[str]) -> list[Signal]:
        """Collect p95/p99 latency if histogram metrics exist."""
        ns_filter = f'namespace="{namespace}"'
        signals = []
        now = datetime.now(timezone.utc)

        for quantile, kind in [("0.95", SignalKind.LATENCY_P95), ("0.99", SignalKind.LATENCY_P99)]:
            queries = [
                f'histogram_quantile({quantile}, rate(http_request_duration_seconds_bucket{{{ns_filter}}}[5m]))',
                f'histogram_quantile({quantile}, rate(request_duration_seconds_bucket{{{ns_filter}}}[5m]))',
            ]
            for q in queries:
                results = self.query(q)
                for r in results:
                    metric = r.get("metric", {})
                    value = float(r.get("value", [0, "0"])[1])
                    if value <= 0:
                        continue
                    severity = Severity.HIGH if value > 1.0 else Severity.MEDIUM if value > 0.5 else Severity.INFO
                    signals.append(Signal(
                        type="signal", ts=now,
                        source=SignalSource.PROMETHEUS, kind=kind,
                        severity=severity,
                        target=Target(
                            kind="Deployment", namespace=namespace,
                            name=metric.get("deployment") or "unknown",
                        ),
                        value=value,
                        message=f"Latency p{'95' if quantile == '0.95' else '99'}: {value*1000:.0f}ms",
                    ))
                if signals:
                    break
        return signals

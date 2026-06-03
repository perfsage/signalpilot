"""Prometheus metrics collector.

Full implementation will:
- Query Prometheus ``/api/v1/query_range`` for a configurable set of PromQL expressions
- Support error rate, latency percentiles (p95/p99), and custom metric families
- Emit typed Signal objects with time-series values for regression detection
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class PrometheusCollector(BaseCollector):
    """Collects metrics from a Prometheus endpoint via HTTP."""

    source = SignalSource.PROMETHEUS

    def __init__(self, url: str, namespace: str, timeout_s: float = 10.0) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

    async def query_range(self, promql: str, start: datetime, end: datetime, step: str = "30s") -> list[dict]:
        """Execute a PromQL range query and return raw result dicts."""
        raise NotImplementedError

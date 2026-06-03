"""Kubernetes Metrics Server collector (``metrics.k8s.io/v1beta1``).

Full implementation will:
- Query the Metrics API for per-pod and per-container CPU/memory usage
- Compare usage against resource limits to detect over-utilisation
- Emit CPU_USAGE and MEM_USAGE Signals
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class MetricsServerCollector(BaseCollector):
    """Collects CPU and memory usage from the Kubernetes Metrics Server."""

    source = SignalSource.METRICS_SERVER

    def __init__(self, namespace: str) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

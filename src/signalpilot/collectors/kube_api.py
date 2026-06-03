"""Kubernetes API collector – pod restarts, OOMKills, CrashLoops, probe failures.

Full implementation will:
- Use the ``kubernetes`` Python client to list pods/containers across a namespace
- Detect restart count deltas, last-termination reasons, and readiness probe failures
- Map each anomaly to a typed Signal with severity derived from restart count
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class KubeApiCollector(BaseCollector):
    """Collects pod-level health signals via the Kubernetes REST API."""

    source = SignalSource.KUBE_API

    def __init__(self, namespace: str) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

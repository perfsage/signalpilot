"""Network signal collector.

Full implementation will:
- Parse ``/proc/net/tcp`` snapshots from node agents for socket queue backlog
- Query Prometheus for TCP retransmit and DNS latency metrics
- Optionally trigger ephemeral tcpdump captures via the deepdive module
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class NetworkCollector(BaseCollector):
    """Collects network-level signals: TCP retransmits, DNS latency."""

    source = SignalSource.NETWORK

    def __init__(self, namespace: str, prometheus_url: str | None = None) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

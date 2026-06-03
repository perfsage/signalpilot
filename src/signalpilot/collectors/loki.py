"""Grafana Loki log collector.

Full implementation will:
- Query Loki ``/loki/api/v1/query_range`` with label selectors for the namespace
- Return structured log entries grouped by stream labels
- Feed log lines to the log analysis module for drain3 clustering
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class LokiCollector(BaseCollector):
    """Collects log streams from a Grafana Loki instance."""

    source = SignalSource.LOKI

    def __init__(self, loki_url: str, namespace: str) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

    async def raw_lines(self, label_selector: str, start: datetime, end: datetime) -> list[str]:
        """Return raw log lines for a Loki label selector."""
        raise NotImplementedError

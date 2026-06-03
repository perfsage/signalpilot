"""Container log collector via the Kubernetes pod log API.

Full implementation will:
- Stream or tail the last N lines of logs for each container in the namespace
- Identify error/exception lines using regex and heuristics
- Pass raw log lines to the log analysis module for drain3 clustering
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class LogsCollector(BaseCollector):
    """Collects raw container logs and emits LOG_ERROR_RATE signals."""

    source = SignalSource.LOGS

    def __init__(self, namespace: str, tail_lines: int = 5000) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

    async def raw_lines(self, pod: str, container: str) -> list[str]:
        """Return raw log lines for a specific pod/container pair."""
        raise NotImplementedError

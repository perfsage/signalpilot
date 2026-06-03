"""cAdvisor container metrics collector.

Full implementation will:
- Scrape cAdvisor endpoints on each node (typically port 4194 or via Prometheus)
- Collect container CPU, memory, and filesystem metrics at high resolution
- Detect CPU throttling ratios and memory working-set growth
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class CadvisorCollector(BaseCollector):
    """Collects container resource metrics from cAdvisor."""

    source = SignalSource.CADVISOR

    def __init__(self, namespace: str, prometheus_url: str | None = None) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

"""Auto-detection and registry of available collectors.

Full implementation will:
- Probe the cluster to detect which optional data sources are available
  (Prometheus, Loki, Jaeger, Metrics Server, cAdvisor)
- Return a list of instantiated collectors that are confirmed reachable
- Allow callers to override the auto-detected set via config
"""

from __future__ import annotations

from signalpilot.collectors.base import BaseCollector
from signalpilot.config import Settings


async def auto_detect_collectors(namespace: str, settings: Settings) -> list[BaseCollector]:
    """Probe the cluster and return a list of reachable, instantiated collectors.

    Always includes KubeApiCollector and EventsCollector.
    Optionally includes Prometheus, Loki, OTel, cAdvisor, and Network collectors
    when the corresponding URLs are configured and reachable.
    """
    raise NotImplementedError

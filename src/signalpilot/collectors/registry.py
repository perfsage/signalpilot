"""Auto-detect and run all available collectors."""

from __future__ import annotations

from typing import Optional

from signalpilot.collectors.base import BaseCollector
from signalpilot.collectors.cadvisor import CAdvisorCollector
from signalpilot.collectors.events import EventsCollector
from signalpilot.collectors.kube_api import KubeApiCollector
from signalpilot.collectors.logs import LogsCollector
from signalpilot.collectors.metrics_server import MetricsServerCollector
from signalpilot.collectors.network import NetworkCollector
from signalpilot.collectors.prometheus import PrometheusCollector
from signalpilot.models import Signal


class CollectorRegistry:
    """Manages a set of collectors and runs them in concert."""

    def __init__(self, settings=None) -> None:
        self._settings = settings
        self._collectors: list[BaseCollector] = []

    def register(self, collector: BaseCollector) -> None:
        """Add *collector* to the registry unconditionally."""
        self._collectors.append(collector)

    def register_defaults(self) -> None:
        """Instantiate all built-in collectors and register available ones.

        KubeApiCollector and EventsCollector are always included if the
        Kubernetes API is reachable. Optional collectors (MetricsServer,
        Logs, Network, cAdvisor, Prometheus) are included when available.
        """
        candidates: list[BaseCollector] = [
            KubeApiCollector(self._settings),
            EventsCollector(self._settings),
            MetricsServerCollector(self._settings),
            LogsCollector(self._settings),
            NetworkCollector(self._settings),
            CAdvisorCollector(self._settings),
            PrometheusCollector(self._settings),
        ]
        for collector in candidates:
            try:
                if collector.is_available():
                    self._collectors.append(collector)
            except Exception:
                pass

    def available_collector_names(self) -> list[str]:
        """Return names of registered collectors that report as available."""
        return [c.name for c in self._collectors if c.is_available()]

    def collect_all(
        self,
        namespace: str,
        deployment: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> list[Signal]:
        """Run all registered collectors and return combined signals."""
        signals: list[Signal] = []
        for collector in self._collectors:
            try:
                signals.extend(
                    collector.collect(
                        namespace=namespace,
                        deployment=deployment,
                        since_ts=since_ts,
                    )
                )
            except Exception:
                pass
        return signals

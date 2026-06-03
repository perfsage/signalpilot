"""Abstract base class for all signal collectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from signalpilot.models import Signal


class BaseCollector(ABC):
    """Abstract base for all SignalPilot collectors."""

    name: str = ""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this collector's data source is reachable."""
        ...

    @abstractmethod
    def collect(
        self,
        namespace: str,
        deployment: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> list[Signal]:
        """Collect and return normalized Signals from this source.

        Args:
            namespace: Kubernetes namespace to query.
            deployment: Optional deployment name to scope the query.
            since_ts: Unix timestamp lower bound; only signals after this time.

        Returns:
            List of Signal objects from this source.
        """
        ...

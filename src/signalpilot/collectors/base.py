"""Abstract base class for all signal collectors.

Every collector must implement ``collect()`` and declare which
``SignalSource`` it represents.  The base class handles lifecycle hooks
(startup/teardown) and optional caching.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from signalpilot.models import Signal, SignalSource


class BaseCollector(ABC):
    """Abstract collector.  Subclass and implement ``collect()``."""

    source: SignalSource

    async def startup(self) -> None:
        """Optional async initialisation (load kubeconfig, open connections)."""

    async def teardown(self) -> None:
        """Optional async cleanup."""

    @abstractmethod
    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        """Collect and return signals for the given UTC time window.

        Args:
            start: Inclusive window start (UTC).
            end: Exclusive window end (UTC).

        Returns:
            Unsorted list of Signal objects observed in the window.
        """
        raise NotImplementedError

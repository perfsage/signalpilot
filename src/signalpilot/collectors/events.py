"""Kubernetes Events collector.

Full implementation will:
- Stream or list K8s Events (``v1/events``) filtered by namespace and time window
- Surface Warning-type events as Signals with severity mapped from reason codes
- Deduplicate repeated events using the event ``count`` field
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class EventsCollector(BaseCollector):
    """Collects Kubernetes Warning events as Signals."""

    source = SignalSource.EVENTS

    def __init__(self, namespace: str) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

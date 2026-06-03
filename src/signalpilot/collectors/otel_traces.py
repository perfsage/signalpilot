"""OpenTelemetry / Jaeger trace collector.

Full implementation will:
- Query the Jaeger HTTP API (or OTLP endpoint) for traces in the analysis window
- Identify high-error-rate or high-latency operations
- Emit LATENCY_P95, LATENCY_P99, and ERROR_RATE Signals per service/operation
"""

from __future__ import annotations

from datetime import datetime

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import Signal, SignalSource


class OtelTracesCollector(BaseCollector):
    """Collects distributed trace data from a Jaeger-compatible backend."""

    source = SignalSource.OTEL_TRACES

    def __init__(self, jaeger_url: str, namespace: str) -> None:
        raise NotImplementedError

    async def collect(self, start: datetime, end: datetime) -> list[Signal]:
        raise NotImplementedError

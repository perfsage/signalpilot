"""Signal timeline store backed by Parquet files.

Full implementation will:
- Persist collected Signals to timestamped Parquet files under ``data_dir``
- Support time-range queries and incremental append via Polars
- Provide a replay mechanism for offline analysis
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Sequence

from signalpilot.models import Signal


class TimelineStore:
    """Append-only Parquet-backed store for Signal objects."""

    def __init__(self, data_dir: str | Path) -> None:
        raise NotImplementedError

    def append(self, signals: Sequence[Signal]) -> None:
        """Persist a batch of signals to the store."""
        raise NotImplementedError

    def query(self, start: datetime, end: datetime) -> list[Signal]:
        """Return all signals within the given UTC time window."""
        raise NotImplementedError

    def latest_deploy_window(self, namespace: str) -> tuple[datetime, datetime] | None:
        """Return (baseline_start, analysis_end) around the most recent deploy."""
        raise NotImplementedError

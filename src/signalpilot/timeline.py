"""Signal timeline store backed by Polars DataFrames and Parquet files."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import polars as pl

from signalpilot.config import get_settings
from signalpilot.models import Analysis, Severity, Signal, SignalKind, SignalSource, Target

SCHEMA = pl.Schema({
    "id": pl.String,
    "ts": pl.Datetime("us", "UTC"),
    "source": pl.String,
    "kind": pl.String,
    "severity": pl.String,
    "target_kind": pl.String,
    "target_namespace": pl.String,
    "target_name": pl.String,
    "target_container": pl.String,
    "value": pl.Float64,
    "message": pl.String,
})


class SignalTimeline:
    """Normalized, persisted store for Signal objects.

    Signals are held in a Polars DataFrame in memory and flushed to a
    Parquet file under ``{data_dir}/timelines/{run_id}.parquet`` on persist().
    """

    def __init__(self, run_id: Optional[str] = None, data_dir: Optional[Path] = None) -> None:
        settings = get_settings()
        self.run_id = run_id or str(uuid.uuid4())
        self._data_dir = data_dir or Path(settings.data_dir)
        self._df: pl.DataFrame = pl.DataFrame(schema=SCHEMA)

    def add(self, signals: list[Signal]) -> None:
        """Append signals to the in-memory timeline."""
        if not signals:
            return
        rows = [_signal_to_row(s) for s in signals]
        new_df = pl.DataFrame(rows, schema=SCHEMA)
        self._df = pl.concat([self._df, new_df])

    def signals(
        self,
        namespace: Optional[str] = None,
        target_name: Optional[str] = None,
        kind: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[Signal]:
        """Return filtered signals as Signal objects, sorted by ts ascending."""
        df = self._df

        if namespace is not None:
            df = df.filter(pl.col("target_namespace") == namespace)
        if target_name is not None:
            df = df.filter(pl.col("target_name") == target_name)
        if kind is not None:
            df = df.filter(pl.col("kind") == kind)
        if since is not None:
            since_utc = _ensure_utc(since)
            df = df.filter(pl.col("ts") >= since_utc)
        if until is not None:
            until_utc = _ensure_utc(until)
            df = df.filter(pl.col("ts") <= until_utc)

        df = df.sort("ts")
        return [_row_to_signal(row) for row in df.iter_rows(named=True)]

    def window(
        self,
        deploy_time: datetime,
        baseline_s: int,
        analysis_s: int,
    ) -> tuple[list[Signal], list[Signal]]:
        """Split timeline into (before_signals, after_signals) relative to deploy_time.

        before_signals: signals from [deploy_time - baseline_s, deploy_time)
        after_signals:  signals from [deploy_time, deploy_time + analysis_s]
        """
        deploy_utc = _ensure_utc(deploy_time)
        window_start = deploy_utc - timedelta(seconds=baseline_s)
        window_end = deploy_utc + timedelta(seconds=analysis_s)

        before_df = self._df.filter(
            (pl.col("ts") >= window_start) & (pl.col("ts") < deploy_utc)
        ).sort("ts")

        after_df = self._df.filter(
            (pl.col("ts") >= deploy_utc) & (pl.col("ts") <= window_end)
        ).sort("ts")

        before = [_row_to_signal(row) for row in before_df.iter_rows(named=True)]
        after = [_row_to_signal(row) for row in after_df.iter_rows(named=True)]
        return before, after

    def persist(self) -> Path:
        """Write timeline to Parquet. Returns the file path."""
        out_dir = self._data_dir / "timelines"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{self.run_id}.parquet"
        self._df.write_parquet(out_path)
        return out_path

    @classmethod
    def load(cls, path: Path) -> "SignalTimeline":
        """Load a previously persisted timeline from Parquet."""
        tl = cls()
        tl._df = pl.read_parquet(path)
        return tl

    def __len__(self) -> int:
        return len(self._df)

    def to_dataframe(self) -> pl.DataFrame:
        """Return a copy of the underlying DataFrame."""
        return self._df.clone()


def _signal_to_row(s: Signal) -> dict:
    """Convert a Signal to a flat dict matching SCHEMA."""
    return {
        "id": str(uuid.uuid4()),
        "ts": s.ts,
        "source": s.source.value,
        "kind": s.kind.value,
        "severity": s.severity.value,
        "target_kind": s.target.kind,
        "target_namespace": s.target.namespace,
        "target_name": s.target.name,
        "target_container": s.target.container or "",
        "value": s.value,
        "message": s.message,
    }


def _row_to_signal(row: dict) -> Signal:
    """Reconstruct a Signal from a flat schema row dict."""
    container = row["target_container"] or None
    return Signal(
        type="signal",
        ts=row["ts"],
        source=SignalSource(row["source"]),
        kind=SignalKind(row["kind"]),
        severity=Severity(row["severity"]),
        target=Target(
            kind=row["target_kind"],
            namespace=row["target_namespace"],
            name=row["target_name"],
            container=container,
        ),
        value=row["value"],
        message=row["message"],
    )


def _ensure_utc(dt: datetime) -> datetime:
    """Return dt with UTC tzinfo; assume UTC if naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

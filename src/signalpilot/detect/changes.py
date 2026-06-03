"""Change-point detection for time-series signals.

Full implementation will:
- Apply CUSUM or PELT (ruptures library) change-point algorithms to metric series
- Identify the precise timestamp where a metric shifted
- Correlate detected change-points with the deployment timestamp
"""

from __future__ import annotations

from datetime import datetime


def detect_change_point(
    timestamps: list[datetime],
    values: list[float],
) -> datetime | None:
    """Return the most significant change-point timestamp in the series.

    Returns ``None`` if no statistically significant change is detected.
    """
    raise NotImplementedError


def correlate_with_deploy(
    change_point: datetime,
    deploy_time: datetime,
    window_s: int = 300,
) -> bool:
    """Return True if *change_point* falls within *window_s* of *deploy_time*."""
    raise NotImplementedError

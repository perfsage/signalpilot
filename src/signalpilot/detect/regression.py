"""Statistical metric regression detection.

Full implementation will:
- Accept time-series data (Polars DataFrame or list of floats) for a metric
- Compute mean/std for the baseline and analysis windows
- Calculate z-score and percentage change
- Return a RegressionWindow indicating whether a regression occurred
"""

from __future__ import annotations

from signalpilot.models import RegressionWindow


def detect_regression(
    metric: str,
    before_values: list[float],
    after_values: list[float],
    z_threshold: float = 2.0,
    min_pct_change: float = 0.20,
) -> RegressionWindow:
    """Detect a statistical regression between two value series.

    Args:
        metric: Human-readable metric name for reporting.
        before_values: Metric samples from the baseline window.
        after_values: Metric samples from the analysis window.
        z_threshold: Z-score threshold above which a regression is flagged.
        min_pct_change: Minimum absolute percentage change to flag.

    Returns:
        A RegressionWindow with ``is_regression=True`` when both thresholds
        are exceeded.
    """
    raise NotImplementedError


def detect_all_regressions(
    signals_by_metric: dict[str, tuple[list[float], list[float]]],
    z_threshold: float = 2.0,
    min_pct_change: float = 0.20,
) -> list[RegressionWindow]:
    """Run regression detection across all provided metrics.

    Args:
        signals_by_metric: Map from metric name to (before_values, after_values).

    Returns:
        List of RegressionWindow objects, filtered to ``is_regression=True`` only.
    """
    raise NotImplementedError

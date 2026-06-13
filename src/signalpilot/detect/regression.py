"""Statistical metric regression detection between before/after signal windows.

Uses IQR-filtered means and z-score analysis to detect regressions in
numeric metrics across two windows of Signal observations.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from signalpilot.config import get_settings
from signalpilot.models import RegressionWindow, Signal, SignalKind

_NUMERIC_KINDS: frozenset[SignalKind] = frozenset(
    {
        SignalKind.CPU_USAGE,
        SignalKind.CPU_THROTTLED,
        SignalKind.MEM_USAGE,
        SignalKind.MEM_WORKING_SET,
        SignalKind.LOG_ERROR_RATE,
        SignalKind.LATENCY_P95,
        SignalKind.LATENCY_P99,
        SignalKind.ERROR_RATE,
        SignalKind.DNS_LATENCY,
        SignalKind.TCP_RETRANSMIT,
        SignalKind.PSI_PRESSURE,
    }
)


def _iqr_filtered_values(signals: list[Signal], kind: SignalKind) -> list[float]:
    """Extract non-None values for kind, filter outliers via 1.5×IQR fence."""
    values = [s.value for s in signals if s.kind == kind and s.value is not None]
    if len(values) < 2:
        return values
    arr = np.array(values, dtype=float)
    q1, q3 = np.percentile(arr, 25), np.percentile(arr, 75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return arr[(arr >= lower) & (arr <= upper)].tolist()


def compute_z_score(before_values: list[float], after_values: list[float]) -> float:
    """Compute z-score of after_mean relative to before distribution.

    z = (after_mean - before_mean) / before_std

    Returns 0.0 if before_std is near-zero (stable baseline) or either
    list is empty.
    """
    if not before_values or not after_values:
        return 0.0
    before_mean = float(np.mean(before_values))
    before_std = float(np.std(before_values, ddof=1)) if len(before_values) > 1 else 0.0
    after_mean = float(np.mean(after_values))
    if before_std < 1e-9:
        return 0.0
    return (after_mean - before_mean) / before_std


def detect_regressions(
    before_signals: list[Signal],
    after_signals: list[Signal],
    target_name: Optional[str] = None,
) -> list[RegressionWindow]:
    """Detect regressions between two windows of signals.

    For each numeric SignalKind that appears in both windows, computes
    IQR-filtered means and a z-score. Returns all RegressionWindow objects
    sorted by abs(pct_change) descending; callers may filter by is_regression.

    Args:
        before_signals: Signals from the baseline window.
        after_signals: Signals from the analysis window.
        target_name: If provided, only consider signals where
            signal.target.name == target_name.
    """
    settings = get_settings()
    z_threshold = settings.regression_z_score_threshold
    min_pct = settings.regression_min_pct_change

    if target_name is not None:
        before_signals = [s for s in before_signals if s.target.name == target_name]
        after_signals = [s for s in after_signals if s.target.name == target_name]

    windows: list[RegressionWindow] = []

    for kind in _NUMERIC_KINDS:
        before_vals = _iqr_filtered_values(before_signals, kind)
        after_vals = _iqr_filtered_values(after_signals, kind)

        if not before_vals or not after_vals:
            continue

        before_mean = float(np.mean(before_vals))
        after_mean = float(np.mean(after_vals))
        pct_change = (after_mean - before_mean) / max(abs(before_mean), 1e-9)
        z_score = compute_z_score(before_vals, after_vals)
        is_regression = abs(z_score) >= z_threshold and abs(pct_change) >= min_pct

        windows.append(
            RegressionWindow(
                metric=kind.value,
                before_mean=before_mean,
                after_mean=after_mean,
                pct_change=pct_change,
                z_score=z_score,
                is_regression=is_regression,
            )
        )

    windows.sort(key=lambda w: abs(w.pct_change), reverse=True)
    return windows

"""Change-point detection for time-series signals.

Uses CUSUM (cumulative sum) or ruptures PELT to find the most significant
shift timestamp in a sequence of metric Signal observations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np

from signalpilot.models import Signal, SignalKind


def detect_change_point(
    signals: list[Signal],
    kind: SignalKind,
    min_samples: int = 5,
) -> Optional[datetime]:
    """Find the most significant change point in a time-ordered series of signals.

    Tries ruptures PELT (model="rbf") first; falls back to CUSUM if ruptures
    is unavailable or returns no internal change point.

    Args:
        signals: All signals to inspect (will be filtered by kind and sorted by ts).
        kind: The SignalKind to analyse.
        min_samples: Minimum number of non-None samples required; returns None
            if the series is shorter.

    Returns:
        The timestamp of the most significant change point, or None.
    """
    candidates = sorted(
        [s for s in signals if s.kind == kind and s.value is not None],
        key=lambda s: s.ts,
    )
    if len(candidates) < min_samples:
        return None

    arr = np.array([s.value for s in candidates], dtype=float)

    # Attempt ruptures PELT
    try:
        import ruptures  # type: ignore[import]

        model = ruptures.Pelt(model="rbf").fit(arr.reshape(-1, 1))
        breakpoints = model.predict(pen=3)
        # breakpoints[-1] is always len(arr); we want an interior index
        interior = [bp for bp in breakpoints if 0 < bp < len(arr)]
        if interior:
            idx = interior[0] - 1  # last sample before the break
            return candidates[idx].ts
    except Exception:  # noqa: BLE001
        pass

    # CUSUM fallback
    mean = arr.mean()
    cusum = np.cumsum(arr - mean)
    idx = int(np.argmax(np.abs(cusum)))
    return candidates[idx].ts

from datetime import datetime, timedelta, timezone

from signalpilot.detect.changes import detect_change_point
from signalpilot.models import Severity, Signal, SignalKind, SignalSource, Target

T0 = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)


def make_signal(value: float, offset_s: int = 0) -> Signal:
    return Signal(
        type="signal",
        ts=T0 + timedelta(seconds=offset_s),
        source=SignalSource.METRICS_SERVER,
        kind=SignalKind.CPU_USAGE,
        severity=Severity.INFO,
        target=Target(kind="Pod", namespace="ns", name="api"),
        value=value,
        message="m",
    )


class TestDetectChangePoint:
    def test_returns_none_for_fewer_than_min_samples(self):
        signals = [make_signal(float(i), i * 10) for i in range(4)]
        result = detect_change_point(signals, SignalKind.CPU_USAGE, min_samples=5)
        assert result is None

    def test_returns_none_for_empty_signals(self):
        result = detect_change_point([], SignalKind.CPU_USAGE)
        assert result is None

    def test_finds_change_point_in_step_function(self):
        # 5 samples at ~10, then 5 samples at ~90 — clear step up
        low = [make_signal(10.0 + i * 0.1, i * 10) for i in range(5)]
        high = [make_signal(90.0 + i * 0.1, (5 + i) * 10) for i in range(5)]
        signals = low + high
        cp = detect_change_point(signals, SignalKind.CPU_USAGE)
        assert cp is not None
        # Change point should be somewhere after the first sample
        assert cp > T0

    def test_returns_datetime_for_sufficient_samples(self):
        signals = [make_signal(float(i), i * 10) for i in range(10)]
        cp = detect_change_point(signals, SignalKind.CPU_USAGE)
        assert isinstance(cp, datetime)

    def test_filters_by_kind(self):
        # Mix CPU and MEM signals; detect_change_point should only use CPU
        cpu_signals = [make_signal(float(i), i * 10) for i in range(5)]
        mem_signals = [
            Signal(
                type="signal",
                ts=T0 + timedelta(seconds=i * 10),
                source=SignalSource.METRICS_SERVER,
                kind=SignalKind.MEM_USAGE,
                severity=Severity.INFO,
                target=Target(kind="Pod", namespace="ns", name="api"),
                value=float(i * 100),
                message="m",
            )
            for i in range(3)
        ]
        all_signals = cpu_signals + mem_signals
        cp = detect_change_point(all_signals, SignalKind.CPU_USAGE)
        assert cp is not None

    def test_flat_series_returns_timestamp(self):
        # Flat series: no real change point, but CUSUM still returns a timestamp
        signals = [make_signal(50.0, i * 10) for i in range(10)]
        cp = detect_change_point(signals, SignalKind.CPU_USAGE)
        assert cp is not None  # Returns the max-abs-CUSUM index (often index 0)

    def test_change_point_respects_min_samples_boundary(self):
        signals = [make_signal(float(i), i * 10) for i in range(5)]
        # Exactly at boundary — should succeed
        cp = detect_change_point(signals, SignalKind.CPU_USAGE, min_samples=5)
        assert cp is not None
        # One below boundary — should fail
        cp_none = detect_change_point(signals[:4], SignalKind.CPU_USAGE, min_samples=5)
        assert cp_none is None

    def test_ignores_none_values(self):
        signals = [make_signal(float(i), i * 10) for i in range(5)]
        # Add a signal with None value — should not count toward min_samples
        signals.append(Signal(
            type="signal",
            ts=T0 + timedelta(seconds=999),
            source=SignalSource.METRICS_SERVER,
            kind=SignalKind.CPU_USAGE,
            severity=Severity.INFO,
            target=Target(kind="Pod", namespace="ns", name="api"),
            value=None,
            message="m",
        ))
        cp = detect_change_point(signals, SignalKind.CPU_USAGE, min_samples=5)
        assert cp is not None

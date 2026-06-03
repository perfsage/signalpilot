import pytest
from datetime import datetime, timezone, timedelta
from signalpilot.detect.regression import (
    detect_regressions, _iqr_filtered_values, compute_z_score
)
from signalpilot.models import Signal, SignalSource, SignalKind, Severity, Target

T0 = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)


def make_signal(kind, value, offset_s=0):
    return Signal(
        type="signal", ts=T0 + timedelta(seconds=offset_s),
        source=SignalSource.METRICS_SERVER, kind=kind, severity=Severity.INFO,
        target=Target(kind="Pod", namespace="ns", name="api"),
        value=value, message="m",
    )


class TestIqrFiltered:
    def test_removes_outliers(self):
        signals = [make_signal(SignalKind.CPU_USAGE, v) for v in [10, 11, 10, 12, 11, 100]]
        result = _iqr_filtered_values(signals, SignalKind.CPU_USAGE)
        assert 100 not in result
        assert len(result) == 5

    def test_returns_all_when_no_outliers(self):
        signals = [make_signal(SignalKind.CPU_USAGE, v) for v in [10, 11, 12, 11]]
        result = _iqr_filtered_values(signals, SignalKind.CPU_USAGE)
        assert len(result) == 4

    def test_single_value_returned_as_is(self):
        signals = [make_signal(SignalKind.CPU_USAGE, 42.0)]
        result = _iqr_filtered_values(signals, SignalKind.CPU_USAGE)
        assert result == [42.0]

    def test_empty_signals_returns_empty(self):
        assert _iqr_filtered_values([], SignalKind.CPU_USAGE) == []

    def test_none_values_excluded(self):
        signals = [make_signal(SignalKind.CPU_USAGE, None), make_signal(SignalKind.CPU_USAGE, 5.0)]
        result = _iqr_filtered_values(signals, SignalKind.CPU_USAGE)
        assert result == [5.0]


class TestComputeZScore:
    def test_large_increase_zero_std_returns_zero(self):
        before = [10.0] * 10
        after = [50.0] * 5
        z = compute_z_score(before, after)
        assert z == 0.0

    def test_with_variance(self):
        before = [10.0, 12.0, 11.0, 10.0, 13.0]
        after = [25.0, 26.0, 24.0]
        z = compute_z_score(before, after)
        assert z > 5.0

    def test_empty_before(self):
        assert compute_z_score([], [1.0, 2.0]) == 0.0

    def test_empty_after(self):
        assert compute_z_score([1.0, 2.0], []) == 0.0

    def test_negative_z_for_decrease(self):
        before = [50.0, 52.0, 51.0, 50.0, 53.0]
        after = [10.0, 11.0, 10.0]
        z = compute_z_score(before, after)
        assert z < -5.0


class TestDetectRegressions:
    def test_cpu_regression_detected(self):
        before = [make_signal(SignalKind.CPU_USAGE, v) for v in [10.0, 11.0, 10.0, 12.0, 11.0]]
        after = [make_signal(SignalKind.CPU_USAGE, v) for v in [80.0, 82.0, 79.0, 81.0]]
        windows = detect_regressions(before, after)
        regressions = [w for w in windows if w.is_regression]
        assert any(w.metric == SignalKind.CPU_USAGE.value for w in regressions)

    def test_no_regression_stable_metric(self):
        signals = [make_signal(SignalKind.CPU_USAGE, v) for v in [10.0, 11.0, 10.0]]
        windows = detect_regressions(signals, signals[:])
        regressions = [w for w in windows if w.is_regression]
        assert len(regressions) == 0

    def test_target_filter(self):
        sig_api = make_signal(SignalKind.CPU_USAGE, 80.0)
        sig_other = Signal(
            type="signal", ts=T0, source=SignalSource.METRICS_SERVER,
            kind=SignalKind.CPU_USAGE, severity=Severity.INFO,
            target=Target(kind="Pod", namespace="ns", name="other"),
            value=80.0, message="m",
        )
        before = [make_signal(SignalKind.CPU_USAGE, v) for v in [10.0, 11.0, 10.0, 10.0, 11.0]]
        after_mixed = [sig_api, sig_other] * 3
        windows_all = detect_regressions(before, after_mixed)
        windows_api = detect_regressions(before, after_mixed, target_name="api")
        assert len(windows_api) <= len(windows_all)

    def test_multiple_metrics(self):
        before = (
            [make_signal(SignalKind.CPU_USAGE, v) for v in [10.0, 11.0, 10.0, 10.0, 11.0]] +
            [make_signal(SignalKind.MEM_USAGE, v) for v in [100.0, 105.0, 100.0, 102.0, 103.0]]
        )
        after = (
            [make_signal(SignalKind.CPU_USAGE, v) for v in [80.0, 82.0, 79.0, 81.0]] +
            [make_signal(SignalKind.MEM_USAGE, v) for v in [101.0, 103.0, 100.0]]
        )
        windows = detect_regressions(before, after)
        kinds = {w.metric for w in windows}
        assert SignalKind.CPU_USAGE.value in kinds
        assert SignalKind.MEM_USAGE.value in kinds

    def test_sorted_by_abs_pct_change(self):
        before_cpu = [make_signal(SignalKind.CPU_USAGE, v) for v in [10.0] * 5]
        before_mem = [make_signal(SignalKind.MEM_USAGE, v) for v in [100.0] * 5]
        after_cpu = [make_signal(SignalKind.CPU_USAGE, v) for v in [100.0] * 4]
        after_mem = [make_signal(SignalKind.MEM_USAGE, v) for v in [110.0] * 4]
        windows = detect_regressions(before_cpu + before_mem, after_cpu + after_mem)
        if len(windows) >= 2:
            assert abs(windows[0].pct_change) >= abs(windows[1].pct_change)

    def test_empty_windows_return_empty(self):
        assert detect_regressions([], []) == []

    def test_returns_regression_window_fields(self):
        before = [make_signal(SignalKind.CPU_USAGE, v) for v in [10.0, 11.0, 10.0, 10.0, 11.0]]
        after = [make_signal(SignalKind.CPU_USAGE, v) for v in [80.0, 82.0, 79.0, 81.0]]
        windows = detect_regressions(before, after)
        assert len(windows) >= 1
        w = next(x for x in windows if x.metric == SignalKind.CPU_USAGE.value)
        assert isinstance(w.before_mean, float)
        assert isinstance(w.after_mean, float)
        assert isinstance(w.pct_change, float)
        assert isinstance(w.z_score, float)
        assert isinstance(w.is_regression, bool)

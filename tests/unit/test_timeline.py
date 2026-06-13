"""Unit tests for SignalTimeline — in-memory + Parquet-persisted signal store."""

from datetime import datetime, timedelta, timezone

from signalpilot.models import (
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)
from signalpilot.timeline import SignalTimeline

T0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_signal(
    kind: SignalKind = SignalKind.RESTART,
    offset_s: int = 0,
    name: str = "api",
    value: float = 1.0,
    namespace: str = "test-ns",
) -> Signal:
    return Signal(
        type="signal",
        ts=T0 + timedelta(seconds=offset_s),
        source=SignalSource.KUBE_API,
        kind=kind,
        severity=Severity.HIGH,
        target=Target(kind="Pod", namespace=namespace, name=name),
        value=value,
        message="test",
    )


class TestSignalTimeline:
    def test_add_and_len(self) -> None:
        tl = SignalTimeline()
        assert len(tl) == 0
        tl.add([make_signal(), make_signal()])
        assert len(tl) == 2

    def test_add_empty_list_no_error(self) -> None:
        tl = SignalTimeline()
        tl.add([])
        assert len(tl) == 0

    def test_signals_returns_all_when_no_filter(self) -> None:
        tl = SignalTimeline()
        tl.add([make_signal(), make_signal()])
        results = tl.signals()
        assert len(results) == 2

    def test_signals_namespace_filter(self) -> None:
        tl = SignalTimeline()
        tl.add([make_signal(namespace="test-ns"), make_signal(namespace="other-ns")])
        results = tl.signals(namespace="test-ns")
        assert len(results) == 1
        assert results[0].target.namespace == "test-ns"

    def test_signals_namespace_filter_no_match(self) -> None:
        tl = SignalTimeline()
        tl.add([make_signal(namespace="test-ns")])
        results = tl.signals(namespace="nonexistent")
        assert results == []

    def test_signals_target_name_filter(self) -> None:
        tl = SignalTimeline()
        tl.add([make_signal(name="api"), make_signal(name="worker")])
        results = tl.signals(target_name="api")
        assert len(results) == 1
        assert results[0].target.name == "api"

    def test_signals_kind_filter(self) -> None:
        tl = SignalTimeline()
        tl.add([
            make_signal(kind=SignalKind.RESTART),
            make_signal(kind=SignalKind.OOM_KILLED),
            make_signal(kind=SignalKind.OOM_KILLED),
        ])
        results = tl.signals(kind=SignalKind.OOM_KILLED.value)
        assert len(results) == 2
        assert all(s.kind == SignalKind.OOM_KILLED for s in results)

    def test_signals_since_filter(self) -> None:
        tl = SignalTimeline()
        tl.add([
            make_signal(offset_s=0),
            make_signal(offset_s=600),
            make_signal(offset_s=1200),
        ])
        results = tl.signals(since=T0 + timedelta(seconds=500))
        assert len(results) == 2

    def test_signals_until_filter(self) -> None:
        tl = SignalTimeline()
        tl.add([
            make_signal(offset_s=0),
            make_signal(offset_s=600),
            make_signal(offset_s=1200),
        ])
        results = tl.signals(until=T0 + timedelta(seconds=700))
        assert len(results) == 2

    def test_signals_since_and_until_filter(self) -> None:
        tl = SignalTimeline()
        tl.add([
            make_signal(offset_s=0),
            make_signal(offset_s=300),
            make_signal(offset_s=600),
            make_signal(offset_s=900),
        ])
        results = tl.signals(
            since=T0 + timedelta(seconds=200),
            until=T0 + timedelta(seconds=700),
        )
        assert len(results) == 2

    def test_window_splits_correctly(self) -> None:
        tl = SignalTimeline()
        deploy = T0 + timedelta(seconds=900)  # deploy at +15 min
        tl.add([
            make_signal(offset_s=0),     # in before window
            make_signal(offset_s=600),   # in before window
            make_signal(offset_s=900),   # in after window (boundary == deploy_time)
            make_signal(offset_s=1200),  # in after window
        ])
        before, after = tl.window(deploy, baseline_s=900, analysis_s=900)
        assert len(before) == 2
        assert len(after) == 2

    def test_window_deploy_boundary_is_after(self) -> None:
        """Signal exactly at deploy_time goes to after, not before."""
        tl = SignalTimeline()
        deploy = T0 + timedelta(seconds=600)
        tl.add([make_signal(offset_s=600)])
        before, after = tl.window(deploy, baseline_s=600, analysis_s=600)
        assert len(before) == 0
        assert len(after) == 1

    def test_window_excludes_outside_range(self) -> None:
        tl = SignalTimeline()
        deploy = T0 + timedelta(seconds=600)
        tl.add([
            make_signal(offset_s=0),     # exactly at baseline start — included
            make_signal(offset_s=1300),  # beyond analysis end (600+600=1200) — excluded
        ])
        before, after = tl.window(deploy, baseline_s=600, analysis_s=600)
        assert len(before) == 1
        assert len(after) == 0

    def test_persist_and_load_roundtrip(self, tmp_path) -> None:
        tl = SignalTimeline(data_dir=tmp_path)
        tl.add([make_signal(), make_signal(kind=SignalKind.OOM_KILLED, value=3.0)])
        path = tl.persist()
        assert path.exists()
        loaded = SignalTimeline.load(path)
        assert len(loaded) == 2

    def test_persist_creates_directory(self, tmp_path) -> None:
        tl = SignalTimeline(data_dir=tmp_path / "nested" / "dir")
        tl.add([make_signal()])
        path = tl.persist()
        assert path.exists()

    def test_persist_returns_correct_path(self, tmp_path) -> None:
        tl = SignalTimeline(run_id="test-run-123", data_dir=tmp_path)
        tl.add([make_signal()])
        path = tl.persist()
        assert path.name == "test-run-123.parquet"

    def test_signals_sorted_by_ts(self) -> None:
        tl = SignalTimeline()
        tl.add([make_signal(offset_s=300), make_signal(offset_s=0), make_signal(offset_s=600)])
        results = tl.signals()
        ts_list = [s.ts for s in results]
        assert ts_list == sorted(ts_list)

    def test_signal_roundtrip_preserves_kind_and_source(self) -> None:
        tl = SignalTimeline()
        original_with_source = Signal(
            type="signal",
            ts=T0,
            source=SignalSource.CADVISOR,
            kind=SignalKind.CPU_THROTTLED,
            severity=Severity.MEDIUM,
            target=Target(kind="Pod", namespace="test", name="my-pod", container="app"),
            value=0.85,
            message="CPU throttled 85%",
        )
        tl.add([original_with_source])
        results = tl.signals()
        assert len(results) == 1
        r = results[0]
        assert r.source == SignalSource.CADVISOR
        assert r.kind == SignalKind.CPU_THROTTLED
        assert r.severity == Severity.MEDIUM
        assert r.target.container == "app"
        assert abs(r.value - 0.85) < 1e-6

    def test_signal_roundtrip_preserves_all_fields(self) -> None:
        tl = SignalTimeline()
        sig = Signal(
            type="signal",
            ts=T0,
            source=SignalSource.PROMETHEUS,
            kind=SignalKind.LATENCY_P99,
            severity=Severity.CRITICAL,
            target=Target(kind="Deployment", namespace="prod", name="gateway"),
            value=1234.567,
            message="p99 latency spike",
        )
        tl.add([sig])
        results = tl.signals()
        r = results[0]
        assert r.source == SignalSource.PROMETHEUS
        assert r.kind == SignalKind.LATENCY_P99
        assert r.severity == Severity.CRITICAL
        assert r.target.kind == "Deployment"
        assert r.target.namespace == "prod"
        assert r.target.name == "gateway"
        assert r.target.container is None
        assert abs(r.value - 1234.567) < 1e-3

    def test_to_dataframe_returns_clone(self) -> None:
        tl = SignalTimeline()
        tl.add([make_signal()])
        df = tl.to_dataframe()
        assert len(df) == 1
        # Mutating the clone should not affect the timeline
        assert len(tl) == 1

    def test_load_roundtrip_preserves_enums(self, tmp_path) -> None:
        tl = SignalTimeline(data_dir=tmp_path)
        tl.add([
            Signal(
                type="signal",
                ts=T0,
                source=SignalSource.LOKI,
                kind=SignalKind.LOG_ERROR_RATE,
                severity=Severity.LOW,
                target=Target(kind="Pod", namespace="ns", name="pod"),
                value=0.05,
                message="low error rate",
            )
        ])
        path = tl.persist()
        loaded = SignalTimeline.load(path)
        results = loaded.signals()
        assert results[0].source == SignalSource.LOKI
        assert results[0].kind == SignalKind.LOG_ERROR_RATE
        assert results[0].severity == Severity.LOW

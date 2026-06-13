"""Unit tests for KubeApiCollector using recorded K8s fixture data."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from signalpilot.collectors.kube_api import KubeApiCollector
from signalpilot.models import Severity, SignalKind
from tests.unit.conftest_k8s import make_pod_list

FIXTURES = Path(__file__).parent.parent / "fixtures" / "k8s"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_collector_with_mock(fixture_name: str) -> tuple[KubeApiCollector, MagicMock]:
    collector = KubeApiCollector()
    mock_api = MagicMock()
    mock_api.list_namespaced_pod.return_value = make_pod_list(load(fixture_name))
    collector._api = mock_api
    return collector, mock_api


class TestKubeApiCollector:
    def test_healthy_pods_no_signals(self):
        collector, _ = _make_collector_with_mock("pods_healthy.json")
        signals = collector.collect("default")
        # Healthy pods: no restarts, running – expect zero signals
        assert signals == []

    def test_crashloop_detected(self):
        collector, _ = _make_collector_with_mock("pods_crashloop.json")
        signals = collector.collect("default")
        kinds = [s.kind for s in signals]
        assert SignalKind.CRASH_LOOP in kinds

    def test_crashloop_severity_critical(self):
        collector, _ = _make_collector_with_mock("pods_crashloop.json")
        signals = collector.collect("default")
        crash = next(s for s in signals if s.kind == SignalKind.CRASH_LOOP)
        assert crash.severity == Severity.CRITICAL

    def test_restart_detected_on_crashloop(self):
        """CrashLoop pod also has restart_count=5 → RESTART signal emitted."""
        collector, _ = _make_collector_with_mock("pods_crashloop.json")
        signals = collector.collect("default")
        kinds = [s.kind for s in signals]
        assert SignalKind.RESTART in kinds

    def test_restart_value_matches_fixture(self):
        collector, _ = _make_collector_with_mock("pods_crashloop.json")
        signals = collector.collect("default")
        restart = next(s for s in signals if s.kind == SignalKind.RESTART)
        assert restart.value == 5.0

    def test_oom_detected(self):
        collector, _ = _make_collector_with_mock("pods_oom.json")
        signals = collector.collect("default")
        kinds = [s.kind for s in signals]
        assert SignalKind.OOM_KILLED in kinds

    def test_oom_severity(self):
        collector, _ = _make_collector_with_mock("pods_oom.json")
        signals = collector.collect("default")
        oom = next(s for s in signals if s.kind == SignalKind.OOM_KILLED)
        assert oom.severity == Severity.CRITICAL

    def test_imagepull_detected(self):
        collector, _ = _make_collector_with_mock("pods_imagepull.json")
        signals = collector.collect("default")
        kinds = [s.kind for s in signals]
        assert SignalKind.IMAGE_PULL_ERROR in kinds

    def test_imagepull_message_contains_reason(self):
        collector, _ = _make_collector_with_mock("pods_imagepull.json")
        signals = collector.collect("default")
        img_sig = next(s for s in signals if s.kind == SignalKind.IMAGE_PULL_ERROR)
        assert "ImagePullBackOff" in img_sig.message

    def test_pending_pod_detected(self):
        collector, _ = _make_collector_with_mock("pods_pending.json")
        signals = collector.collect("default")
        kinds = [s.kind for s in signals]
        assert SignalKind.PENDING_POD in kinds

    def test_pending_pod_severity_high(self):
        collector, _ = _make_collector_with_mock("pods_pending.json")
        signals = collector.collect("default")
        pending = next(s for s in signals if s.kind == SignalKind.PENDING_POD)
        assert pending.severity == Severity.HIGH

    def test_probe_failure_detected(self):
        collector, _ = _make_collector_with_mock("pods_probe_fail.json")
        signals = collector.collect("default")
        kinds = [s.kind for s in signals]
        assert SignalKind.PROBE_FAILURE in kinds

    def test_probe_failure_target_has_no_container(self):
        """PROBE_FAILURE targets the pod, not a specific container."""
        collector, _ = _make_collector_with_mock("pods_probe_fail.json")
        signals = collector.collect("default")
        probe = next(s for s in signals if s.kind == SignalKind.PROBE_FAILURE)
        assert probe.target.container is None

    def test_deployment_label_selector_passed(self):
        """When deployment is specified, label_selector is forwarded to the API."""
        collector, mock_api = _make_collector_with_mock("pods_healthy.json")
        collector.collect("default", deployment="api-server")
        mock_api.list_namespaced_pod.assert_called_once_with(
            namespace="default", label_selector="app=api-server"
        )

    def test_source_is_kube_api(self):
        from signalpilot.models import SignalSource
        collector, _ = _make_collector_with_mock("pods_crashloop.json")
        signals = collector.collect("default")
        assert all(s.source == SignalSource.KUBE_API for s in signals)

    def test_is_available_returns_false_on_exception(self):
        collector = KubeApiCollector()
        mock_api = MagicMock()
        mock_api.list_namespace.side_effect = Exception("connection refused")
        collector._api = mock_api
        assert collector.is_available() is False

    def test_is_available_returns_true_on_success(self):
        collector = KubeApiCollector()
        mock_api = MagicMock()
        mock_api.list_namespace.return_value = MagicMock()
        collector._api = mock_api
        assert collector.is_available() is True

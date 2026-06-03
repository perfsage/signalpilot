"""Unit tests for MetricsServerCollector using recorded fixture data."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from signalpilot.collectors.metrics_server import (
    MetricsServerCollector,
    _parse_cpu,
    _parse_memory,
)
from signalpilot.models import SignalKind, SignalSource, Severity

from tests.unit.conftest_k8s import make_pod_list

FIXTURES = Path(__file__).parent.parent / "fixtures" / "k8s"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_collector(metrics_data: dict, pod_data: dict | None = None) -> MetricsServerCollector:
    collector = MetricsServerCollector()
    mock_custom = MagicMock()
    mock_core = MagicMock()
    mock_custom.list_namespaced_custom_object.return_value = metrics_data
    if pod_data:
        mock_core.list_namespaced_pod.return_value = make_pod_list(pod_data)
    else:
        mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])
    collector._custom_api = mock_custom
    collector._core_api = mock_core
    return collector


class TestParseCpu:
    def test_millicores(self):
        assert _parse_cpu("150m") == 150.0

    def test_full_cores(self):
        assert _parse_cpu("1") == 1000.0

    def test_fractional_cores(self):
        assert _parse_cpu("0.5") == 500.0

    def test_nanocores(self):
        assert _parse_cpu("500000000n") == pytest.approx(500.0)


class TestParseMemory:
    def test_mebibytes(self):
        assert _parse_memory("128Mi") == 128 * 1024 * 1024

    def test_gibibytes(self):
        assert _parse_memory("1Gi") == 1024 * 1024 * 1024

    def test_kibibytes(self):
        assert _parse_memory("512Ki") == 512 * 1024

    def test_plain_bytes(self):
        assert _parse_memory("1024") == 1024.0


class TestMetricsServerCollector:
    def test_signals_emitted_for_each_container(self):
        data = load("metrics_pods.json")
        collector = _make_collector(data)
        signals = collector.collect("default")
        # 2 pods × 1 container × 2 signal types (CPU + MEM) = 4
        assert len(signals) == 4

    def test_cpu_usage_signal_present(self):
        data = load("metrics_pods.json")
        collector = _make_collector(data)
        signals = collector.collect("default")
        kinds = [s.kind for s in signals]
        assert SignalKind.CPU_USAGE in kinds

    def test_mem_usage_signal_present(self):
        data = load("metrics_pods.json")
        collector = _make_collector(data)
        signals = collector.collect("default")
        kinds = [s.kind for s in signals]
        assert SignalKind.MEM_USAGE in kinds

    def test_source_is_metrics_server(self):
        data = load("metrics_pods.json")
        collector = _make_collector(data)
        signals = collector.collect("default")
        assert all(s.source == SignalSource.METRICS_SERVER for s in signals)

    def test_cpu_value_in_millicores(self):
        data = load("metrics_pods.json")
        collector = _make_collector(data)
        signals = collector.collect("default")
        cpu_signals = [s for s in signals if s.kind == SignalKind.CPU_USAGE]
        # Fixture: 320m and 450m
        cpu_values = {s.value for s in cpu_signals}
        assert 320.0 in cpu_values
        assert 450.0 in cpu_values

    def test_mem_value_in_bytes(self):
        data = load("metrics_pods.json")
        collector = _make_collector(data)
        signals = collector.collect("default")
        mem_signals = [s for s in signals if s.kind == SignalKind.MEM_USAGE]
        # 210Mi in bytes
        expected_bytes = 210 * 1024 * 1024
        mem_values = {s.value for s in mem_signals}
        assert expected_bytes in mem_values

    def test_high_saturation_severity(self):
        """CPU usage at 90% of limit → HIGH severity."""
        metrics = {
            "items": [
                {
                    "metadata": {"name": "api-server-abc", "namespace": "default"},
                    "containers": [
                        {"name": "api-server", "usage": {"cpu": "450m", "memory": "100Mi"}}
                    ],
                }
            ]
        }
        # Pod with cpu limit 500m so 450/500 = 90% > 80% → HIGH
        pod_data = {
            "items": [
                {
                    "metadata": {
                        "name": "api-server-abc",
                        "namespace": "default",
                        "creation_timestamp": "2024-06-01T10:00:00Z",
                        "labels": {},
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "api-server",
                                "image": "test:latest",
                                "resources": {
                                    "limits": {"cpu": "500m", "memory": "512Mi"},
                                    "requests": {"cpu": "200m", "memory": "256Mi"},
                                },
                                "env": [],
                            }
                        ]
                    },
                    "status": {
                        "phase": "Running",
                        "conditions": [],
                        "container_statuses": [],
                    },
                }
            ]
        }
        collector = _make_collector(metrics, pod_data)
        signals = collector.collect("default")
        cpu_sig = next(s for s in signals if s.kind == SignalKind.CPU_USAGE)
        assert cpu_sig.severity == Severity.HIGH

    def test_medium_saturation_severity(self):
        """CPU usage at 70% of limit → MEDIUM severity."""
        metrics = {
            "items": [
                {
                    "metadata": {"name": "api-server-abc", "namespace": "default"},
                    "containers": [
                        {"name": "api-server", "usage": {"cpu": "350m", "memory": "100Mi"}}
                    ],
                }
            ]
        }
        pod_data = {
            "items": [
                {
                    "metadata": {
                        "name": "api-server-abc",
                        "namespace": "default",
                        "creation_timestamp": "2024-06-01T10:00:00Z",
                        "labels": {},
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "api-server",
                                "image": "test:latest",
                                "resources": {
                                    "limits": {"cpu": "500m", "memory": "512Mi"},
                                    "requests": {"cpu": "200m", "memory": "256Mi"},
                                },
                                "env": [],
                            }
                        ]
                    },
                    "status": {
                        "phase": "Running",
                        "conditions": [],
                        "container_statuses": [],
                    },
                }
            ]
        }
        collector = _make_collector(metrics, pod_data)
        signals = collector.collect("default")
        cpu_sig = next(s for s in signals if s.kind == SignalKind.CPU_USAGE)
        assert cpu_sig.severity == Severity.MEDIUM

    def test_is_available_false_on_api_404(self):
        from kubernetes.client.exceptions import ApiException

        collector = MetricsServerCollector()
        mock_custom = MagicMock()
        mock_custom.list_namespaced_custom_object.side_effect = ApiException(status=404)
        collector._custom_api = mock_custom
        collector._core_api = MagicMock()
        assert collector.is_available() is False

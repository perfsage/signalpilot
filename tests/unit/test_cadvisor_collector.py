from unittest.mock import MagicMock

from signalpilot.collectors.cadvisor import (
    CAdvisorCollector,
    _parse_kubelet_metrics,
    _throttle_ratio,
)

SAMPLE_SUMMARY = {
    "pods": [{
        "podRef": {"namespace": "test-ns", "name": "api-pod-abc"},
        "containers": [{
            "name": "app",
            "memory": {"workingSetBytes": 134217728},  # 128 MB
            "cpu": {"usageNanoCores": 500000000},       # 500 m CPU
        }],
    }],
}


class TestCAdvisorCollector:
    def test_parse_stats_memory_signal(self):
        c = CAdvisorCollector(MagicMock())
        sigs = c._parse_stats(SAMPLE_SUMMARY, "test-ns", None, "node1")
        mem_sigs = [s for s in sigs if s.kind.value == "mem_working_set"]
        assert len(mem_sigs) == 1
        assert mem_sigs[0].value == 134217728.0

    def test_parse_stats_cpu_signal(self):
        c = CAdvisorCollector(MagicMock())
        sigs = c._parse_stats(SAMPLE_SUMMARY, "test-ns", None, "node1")
        cpu_sigs = [s for s in sigs if s.kind.value == "cpu_usage"]
        assert len(cpu_sigs) == 1
        # 500_000_000 nanocores / 1e6 = 500 millicores
        assert abs(cpu_sigs[0].value - 500.0) < 0.1

    def test_parse_stats_namespace_filter(self):
        c = CAdvisorCollector(MagicMock())
        sigs = c._parse_stats(SAMPLE_SUMMARY, "other-ns", None, "node1")
        assert len(sigs) == 0

    def test_parse_stats_deployment_filter(self):
        c = CAdvisorCollector(MagicMock())
        # Pod name starts with "api-pod" — deployment filter "other" should exclude it
        sigs = c._parse_stats(SAMPLE_SUMMARY, "test-ns", "other", "node1")
        assert len(sigs) == 0

    def test_parse_stats_deployment_filter_matches(self):
        c = CAdvisorCollector(MagicMock())
        sigs = c._parse_stats(SAMPLE_SUMMARY, "test-ns", "api-pod", "node1")
        assert len(sigs) > 0


class TestParseKubeletMetrics:
    def test_parses_cfs_metrics(self):
        text = """\
# HELP container_cpu_cfs_throttled_seconds_total
# TYPE container_cpu_cfs_throttled_seconds_total counter
container_cpu_cfs_throttled_seconds_total{container="app",namespace="ns"} 12.5
container_cpu_cfs_periods_total{container="app",namespace="ns"} 1000"""
        result = _parse_kubelet_metrics(text)
        assert "container_cpu_cfs_throttled_seconds_total" in result
        assert "container_cpu_cfs_periods_total" in result

    def test_ignores_non_cfs_lines(self):
        text = 'container_memory_usage_bytes{container="app"} 1024\n'
        result = _parse_kubelet_metrics(text)
        assert result == {}

    def test_ignores_comment_lines(self):
        text = "# HELP container_cpu_cfs_periods_total\n"
        result = _parse_kubelet_metrics(text)
        assert result == {}


class TestThrottleRatio:
    def test_correct_ratio(self):
        assert abs(_throttle_ratio(100.0, 1000.0) - 0.1) < 1e-6

    def test_zero_periods(self):
        assert _throttle_ratio(10.0, 0.0) == 0.0

    def test_max_one(self):
        assert _throttle_ratio(2000.0, 100.0) == 1.0

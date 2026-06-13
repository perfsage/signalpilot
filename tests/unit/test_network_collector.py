from unittest.mock import MagicMock, patch

from signalpilot.collectors.network import NetworkCollector
from signalpilot.models import Severity, SignalKind


class TestNetworkCollector:
    def test_not_ready_endpoint_emits_signal(self):
        collector = NetworkCollector(MagicMock())
        mock_ep = MagicMock()
        mock_ep.metadata.name = "my-service"
        mock_subset = MagicMock()
        mock_subset.not_ready_addresses = [MagicMock(), MagicMock()]
        mock_ep.subsets = [mock_subset]

        mock_eps = MagicMock()
        mock_eps.items = [mock_ep]

        with patch("signalpilot.collectors.network.client") as mock_client:
            mock_client.CoreV1Api.return_value.list_namespaced_endpoints.return_value = mock_eps
            sigs = collector._collect_endpoint_readiness("test-ns")

        assert len(sigs) == 1
        assert sigs[0].kind == SignalKind.PROBE_FAILURE
        assert sigs[0].value == 2.0

    def test_ready_endpoint_no_signal(self):
        collector = NetworkCollector(MagicMock())
        mock_ep = MagicMock()
        mock_ep.metadata.name = "healthy-service"
        mock_subset = MagicMock()
        mock_subset.not_ready_addresses = None
        mock_ep.subsets = [mock_subset]

        mock_eps = MagicMock()
        mock_eps.items = [mock_ep]

        with patch("signalpilot.collectors.network.client") as mock_client:
            mock_client.CoreV1Api.return_value.list_namespaced_endpoints.return_value = mock_eps
            sigs = collector._collect_endpoint_readiness("test-ns")

        assert len(sigs) == 0

    def test_is_available_always_true(self):
        collector = NetworkCollector(MagicMock())
        assert collector.is_available() is True

    def test_collect_delegates_to_endpoint_readiness(self):
        collector = NetworkCollector(MagicMock())
        mock_eps = MagicMock()
        mock_eps.items = []

        with patch("signalpilot.collectors.network.client") as mock_client:
            mock_client.CoreV1Api.return_value.list_namespaced_endpoints.return_value = mock_eps
            sigs = collector.collect("test-ns")

        assert sigs == []

    def test_api_exception_returns_empty(self):
        collector = NetworkCollector(MagicMock())
        with patch("signalpilot.collectors.network.client") as mock_client:
            mock_client.CoreV1Api.return_value.list_namespaced_endpoints.side_effect = Exception("api down")
            sigs = collector._collect_endpoint_readiness("test-ns")

        assert sigs == []

    def test_severity_is_high(self):
        collector = NetworkCollector(MagicMock())
        mock_ep = MagicMock()
        mock_ep.metadata.name = "svc"
        mock_subset = MagicMock()
        mock_subset.not_ready_addresses = [MagicMock()]
        mock_ep.subsets = [mock_subset]
        mock_eps = MagicMock()
        mock_eps.items = [mock_ep]

        with patch("signalpilot.collectors.network.client") as mock_client:
            mock_client.CoreV1Api.return_value.list_namespaced_endpoints.return_value = mock_eps
            sigs = collector._collect_endpoint_readiness("ns")

        assert sigs[0].severity == Severity.HIGH

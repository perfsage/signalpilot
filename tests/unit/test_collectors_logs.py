"""Unit tests for LogsCollector and redact_secrets()."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from signalpilot.collectors.logs import LogsCollector, redact_secrets
from signalpilot.models import Severity, SignalKind, SignalSource

# ---------------------------------------------------------------------------
# redact_secrets – direct function tests
# ---------------------------------------------------------------------------

class TestRedactSecrets:
    def test_authorization_bearer_redacted(self):
        raw = "GET /api Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.secret.token\n200 OK"
        redacted = redact_secrets(raw)
        assert "eyJhbGciOiJSUzI1NiJ9" not in redacted
        assert "[REDACTED]" in redacted

    def test_password_equals_redacted(self):
        raw = "Connecting with password=supersecret123 to db"
        redacted = redact_secrets(raw)
        assert "supersecret123" not in redacted
        assert "[REDACTED]" in redacted

    def test_token_colon_redacted(self):
        raw = "Loaded token: mysupersecrettoken123456"
        redacted = redact_secrets(raw)
        assert "mysupersecrettoken123456" not in redacted
        assert "[REDACTED]" in redacted

    def test_secret_equals_redacted(self):
        raw = "Using secret=abc123xyz456 for encryption"
        redacted = redact_secrets(raw)
        assert "abc123xyz456" not in redacted
        assert "[REDACTED]" in redacted

    def test_api_key_redacted(self):
        raw = "api_key=sk-12345678901234567890"
        redacted = redact_secrets(raw)
        assert "sk-12345678901234567890" not in redacted
        assert "[REDACTED]" in redacted

    def test_short_value_not_redacted(self):
        """Values shorter than 6 chars are not redacted."""
        raw = "password=abc"
        redacted = redact_secrets(raw)
        # "abc" is only 3 chars – below the threshold, should not be redacted
        assert "abc" in redacted

    def test_preserves_non_secrets(self):
        raw = "INFO Starting server on port 8080"
        redacted = redact_secrets(raw)
        assert redacted == raw

    def test_preserves_normal_log_lines(self):
        raw = "2024-06-01 12:00:00 INFO Request completed in 45ms"
        redacted = redact_secrets(raw)
        assert redacted == raw

    def test_multiple_secrets_in_one_line(self):
        raw = "user=admin password=hunter2secret token=abcdefghijklmn"
        redacted = redact_secrets(raw)
        assert "hunter2secret" not in redacted
        assert "abcdefghijklmn" not in redacted
        assert redacted.count("[REDACTED]") >= 2

    def test_authorization_header_key_preserved(self):
        raw = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig"
        redacted = redact_secrets(raw)
        assert "Authorization:" in redacted
        assert "Bearer" in redacted


# ---------------------------------------------------------------------------
# LogsCollector.collect() – integration-style unit tests with mocks
# ---------------------------------------------------------------------------

def _make_pod_with_container(pod_name: str, container_name: str, namespace: str = "default"):
    container = SimpleNamespace(name=container_name)
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name=pod_name, namespace=namespace, creation_timestamp=None),
        spec=SimpleNamespace(containers=[container]),
        status=SimpleNamespace(phase="Running"),
    )
    return pod


class TestLogsCollector:
    def _make_collector(self, pod_names: list[str], log_map: dict[str, str]) -> LogsCollector:
        collector = LogsCollector()
        mock_api = MagicMock()
        pods = [_make_pod_with_container(name, "app") for name in pod_names]
        mock_api.list_namespaced_pod.return_value = SimpleNamespace(items=pods)

        def _read_log(name, namespace, container, tail_lines):
            return log_map.get(name, "")

        mock_api.read_namespaced_pod_log.side_effect = _read_log
        collector._api = mock_api
        return collector

    def test_one_signal_per_pod_container(self):
        collector = self._make_collector(
            ["pod-a", "pod-b"],
            {"pod-a": "INFO ok\n", "pod-b": "INFO ok\n"},
        )
        signals = collector.collect("default")
        assert len(signals) == 2

    def test_error_count_in_value(self):
        log = "\n".join(["ERROR something went wrong"] * 3 + ["INFO ok"])
        collector = self._make_collector(["pod-a"], {"pod-a": log})
        signals = collector.collect("default")
        assert signals[0].value == 3.0

    def test_kind_log_error_rate(self):
        collector = self._make_collector(["pod-a"], {"pod-a": "INFO ok\n"})
        signals = collector.collect("default")
        assert signals[0].kind == SignalKind.LOG_ERROR_RATE

    def test_source_is_logs(self):
        collector = self._make_collector(["pod-a"], {"pod-a": "INFO ok\n"})
        signals = collector.collect("default")
        assert signals[0].source == SignalSource.LOGS

    def test_secrets_redacted_in_message(self):
        log = "Connecting with password=supersecret123 to db\nINFO ok"
        collector = self._make_collector(["pod-a"], {"pod-a": log})
        signals = collector.collect("default")
        assert "supersecret123" not in signals[0].message
        assert "[REDACTED]" in signals[0].message

    def test_empty_log_skipped(self):
        collector = self._make_collector(["pod-a"], {"pod-a": ""})
        signals = collector.collect("default")
        assert signals == []

    def test_pod_log_exception_skipped(self):
        """If reading a pod's log raises an exception, skip that pod gracefully."""
        collector = LogsCollector()
        mock_api = MagicMock()
        pods = [_make_pod_with_container("pod-a", "app")]
        mock_api.list_namespaced_pod.return_value = SimpleNamespace(items=pods)
        mock_api.read_namespaced_pod_log.side_effect = Exception("pod not found")
        collector._api = mock_api
        signals = collector.collect("default")
        assert signals == []

    def test_high_error_count_severity(self):
        log = "\n".join(["ERROR critical failure"] * 60)
        collector = self._make_collector(["pod-a"], {"pod-a": log})
        signals = collector.collect("default")
        assert signals[0].severity == Severity.HIGH

    def test_medium_error_count_severity(self):
        log = "\n".join(["ERROR minor issue"] * 20)
        collector = self._make_collector(["pod-a"], {"pod-a": log})
        signals = collector.collect("default")
        assert signals[0].severity == Severity.MEDIUM

    def test_target_container_set(self):
        collector = self._make_collector(["pod-a"], {"pod-a": "INFO ok\n"})
        signals = collector.collect("default")
        assert signals[0].target.container == "app"

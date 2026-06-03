"""Unit tests for EventsCollector using recorded K8s fixture data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from signalpilot.collectors.events import EventsCollector
from signalpilot.models import SignalKind, SignalSource, Severity

from tests.unit.conftest_k8s import make_event_list

FIXTURES = Path(__file__).parent.parent / "fixtures" / "k8s"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_collector(fixture_name: str) -> tuple[EventsCollector, MagicMock]:
    collector = EventsCollector()
    mock_api = MagicMock()
    mock_api.list_namespaced_event.return_value = make_event_list(load(fixture_name))
    collector._api = mock_api
    return collector, mock_api


class TestEventsCollector:
    def test_four_signals_emitted(self):
        collector, _ = _make_collector("events_warnings.json")
        # since_ts in the far past so all 4 events pass the time filter
        since = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        signals = collector.collect("default", since_ts=since)
        assert len(signals) == 4

    def test_all_signals_kind_event(self):
        collector, _ = _make_collector("events_warnings.json")
        since = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        signals = collector.collect("default", since_ts=since)
        assert all(s.kind == SignalKind.EVENT for s in signals)

    def test_warning_events_severity_high(self):
        collector, _ = _make_collector("events_warnings.json")
        since = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        signals = collector.collect("default", since_ts=since)
        warning_signals = [s for s in signals if s.message.split(": ")[0] in {"FailedScheduling", "BackOff", "Unhealthy"}]
        assert all(s.severity == Severity.HIGH for s in warning_signals)

    def test_source_is_events(self):
        collector, _ = _make_collector("events_warnings.json")
        since = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        signals = collector.collect("default", since_ts=since)
        assert all(s.source == SignalSource.EVENTS for s in signals)

    def test_message_format_reason_colon_message(self):
        collector, _ = _make_collector("events_warnings.json")
        since = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        signals = collector.collect("default", since_ts=since)
        reasons = {"FailedScheduling", "BackOff", "Unhealthy", "Pulled"}
        for sig in signals:
            assert ": " in sig.message
            reason = sig.message.split(": ")[0]
            assert reason in reasons

    def test_time_filter_excludes_old_events(self):
        """Events older than since_ts must not appear."""
        collector, _ = _make_collector("events_warnings.json")
        # since_ts = far future → no events pass the cutoff
        future = datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp()
        signals = collector.collect("default", since_ts=future)
        assert signals == []

    def test_default_1h_window_excludes_old_events(self):
        """Without since_ts, events older than 1 hour should be excluded."""
        from unittest.mock import patch
        from datetime import timedelta

        now = datetime(2024, 6, 1, 14, 0, 0, tzinfo=timezone.utc)
        with patch("signalpilot.collectors.events.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromtimestamp.side_effect = datetime.fromtimestamp
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            collector, _ = _make_collector("events_warnings.json")
            # All fixture events have last_timestamp around 11:30-11:40, i.e. 2+ hours ago
            signals = collector.collect("default")
        assert signals == []

    def test_deployment_field_selector_forwarded(self):
        collector, mock_api = _make_collector("events_warnings.json")
        since = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        collector.collect("default", deployment="api-server", since_ts=since)
        call_kwargs = mock_api.list_namespaced_event.call_args[1]
        assert call_kwargs.get("field_selector") == "involvedObject.name=api-server"

    def test_normal_events_severity_info(self):
        """Normal events must produce Severity.INFO signals (not be dropped)."""
        collector, _ = _make_collector("events_warnings.json")
        since = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        signals = collector.collect("default", since_ts=since)
        normal_signals = [s for s in signals if s.message.startswith("Pulled:")]
        assert len(normal_signals) == 1
        assert normal_signals[0].severity == Severity.INFO

    def test_is_available_returns_false_on_exception(self):
        collector = EventsCollector()
        mock_api = MagicMock()
        mock_api.list_namespace.side_effect = Exception("no cluster")
        collector._api = mock_api
        assert collector.is_available() is False

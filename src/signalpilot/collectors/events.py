"""Kubernetes Events collector – surfaces Warning events as Signals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from kubernetes import client

from signalpilot.collectors.base import BaseCollector
from signalpilot.collectors.kube_api import _load_kube_config, _parse_ts
from signalpilot.models import (
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)


class EventsCollector(BaseCollector):
    """Collects Kubernetes events as Signals (Warning → HIGH, Normal → INFO)."""

    name = "events"

    def __init__(self, settings=None) -> None:
        self._settings = settings
        self._api: Optional[client.CoreV1Api] = None

    def _get_api(self) -> client.CoreV1Api:
        if self._api is None:
            _load_kube_config(self._settings)
            self._api = client.CoreV1Api()
        return self._api

    def is_available(self) -> bool:
        try:
            self._get_api().list_namespace(limit=1)
            return True
        except Exception:
            return False

    def collect(
        self,
        namespace: str,
        deployment: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> list[Signal]:
        api = self._get_api()

        field_selector: Optional[str] = None
        if deployment:
            field_selector = f"involvedObject.name={deployment}"

        event_list = api.list_namespaced_event(
            namespace=namespace,
            field_selector=field_selector,
        )

        now = datetime.now(timezone.utc)
        cutoff = (
            datetime.fromtimestamp(since_ts, tz=timezone.utc)
            if since_ts
            else now - timedelta(hours=1)
        )

        signals: list[Signal] = []
        for event in event_list.items:
            event_type = getattr(event, "type", "Normal") or "Normal"
            severity = Severity.HIGH if event_type == "Warning" else Severity.INFO

            # Resolve best available timestamp
            event_ts = (
                getattr(event, "last_timestamp", None)
                or getattr(event, "event_time", None)
                or getattr(event, "first_timestamp", None)
            )
            event_ts = _parse_ts(event_ts)

            if event_ts < cutoff:
                continue

            reason = getattr(event, "reason", "") or ""
            message = getattr(event, "message", "") or ""

            involved = getattr(event, "involved_object", None)
            obj_kind = getattr(involved, "kind", "Unknown") if involved else "Unknown"
            obj_name = getattr(involved, "name", "") if involved else ""

            target = Target(kind=obj_kind, namespace=namespace, name=obj_name)

            signals.append(
                Signal(
                    ts=event_ts,
                    source=SignalSource.EVENTS,
                    kind=SignalKind.EVENT,
                    severity=severity,
                    target=target,
                    message=f"{reason}: {message}",
                )
            )

        return signals

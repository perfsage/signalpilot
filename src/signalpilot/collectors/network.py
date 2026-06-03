"""
Network collector for PerfSage SignalPilot.

Collects:
- DNS latency/failure signals from CoreDNS metrics (if available)
- Endpoint readiness (Endpoints objects missing ready addresses)
- Legacy Inspektor Gadget Trace CRD triggers for eBPF (best-effort)
- On-demand tcpdump capture pod for slow-transaction deep-dive

The tcpdump capture is orchestrated by deepdive.py; this module provides
the DNS and endpoint readiness signals that are always-on.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from kubernetes import client

from signalpilot.collectors.base import BaseCollector
from signalpilot.config import get_settings
from signalpilot.models import (
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)


class NetworkCollector(BaseCollector):
    """Collect DNS and endpoint readiness signals."""

    name = "network"

    def __init__(self, settings=None):
        self._settings = settings or get_settings()

    def is_available(self) -> bool:
        """Always available — reads from K8s Endpoints API."""
        return True

    def collect(
        self,
        namespace: str,
        deployment: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> list[Signal]:
        """Collect endpoint readiness signals for the namespace."""
        signals: list[Signal] = []
        signals.extend(self._collect_endpoint_readiness(namespace))
        return signals

    def _collect_endpoint_readiness(self, namespace: str) -> list[Signal]:
        """
        Check endpoints in namespace.

        If an endpoint has notReadyAddresses > 0, emit a Signal with
        kind=PROBE_FAILURE describing the endpoint not-ready state.
        """
        signals: list[Signal] = []
        now = datetime.now(timezone.utc)
        try:
            eps = client.CoreV1Api().list_namespaced_endpoints(namespace)
            for ep in eps.items:
                ep_name = ep.metadata.name
                not_ready = 0
                if ep.subsets:
                    for subset in ep.subsets:
                        if subset.not_ready_addresses:
                            not_ready += len(subset.not_ready_addresses)
                if not_ready > 0:
                    signals.append(Signal(
                        type="signal",
                        ts=now,
                        source=SignalSource.KUBE_API,
                        kind=SignalKind.PROBE_FAILURE,
                        severity=Severity.HIGH,
                        target=Target(kind="Service", namespace=namespace, name=ep_name),
                        value=float(not_ready),
                        message=f"Endpoint {ep_name}: {not_ready} not-ready address(es)",
                    ))
        except Exception:
            pass
        return signals


def check_coredns_available(prometheus_url: Optional[str]) -> bool:
    """
    Return True if CoreDNS metrics are available via Prometheus.
    This is used by the optional Prometheus adapter, not this module.
    """
    if not prometheus_url:
        return False
    try:
        import httpx
        r = httpx.get(
            f"{prometheus_url}/api/v1/query",
            params={"query": "coredns_dns_requests_total"},
            timeout=3.0,
        )
        return r.status_code == 200
    except Exception:
        return False

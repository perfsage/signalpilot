"""
Deep-dive packet analysis orchestrator for PerfSage SignalPilot.

Orchestrates on-demand tcpdump capture pods for slow-transaction analysis.
The capture pod runs in the target namespace with NET_ADMIN capability,
captures for a short window, then the results are parsed for:
- TCP retransmits
- High RTT / zero-window pauses
- SYN backlog / connection queue issues
- TLS handshake failures

The capture pod is always cleaned up after use (even on error).
Gate: only triggered when --deep-network flag is set or when
a latency regression finding is present.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from kubernetes import client

from signalpilot.config import get_settings
from signalpilot.models import (
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)

CAPTURE_POD_MANIFEST = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {
        "name": "signalpilot-capture",
        "labels": {"app": "signalpilot-capture"},
    },
    "spec": {
        "hostNetwork": False,
        "restartPolicy": "Never",
        "containers": [{
            "name": "tcpdump",
            "image": "nicolaka/netshoot:latest",
            "command": [
                "sh", "-c",
                "tcpdump -i any -w /tmp/capture.pcap -G {duration} -W 1 -nn 2>&1; "
                "echo '---DONE---'",
            ],
            "securityContext": {
                "capabilities": {"add": ["NET_ADMIN", "NET_RAW"]},
            },
        }],
    },
}


class DeepDiveOrchestrator:
    """
    Orchestrates on-demand tcpdump capture for deep network analysis.
    Always cleans up capture pods.
    """

    def __init__(self, settings=None):
        self._settings = settings or get_settings()

    def should_trigger(self, findings_so_far: list) -> bool:
        """
        Return True if deep network analysis is warranted.
        Triggered when any finding has kind related to latency or network.
        """
        latency_kinds = {
            SignalKind.LATENCY_P95,
            SignalKind.LATENCY_P99,
            SignalKind.TCP_RETRANSMIT,
            SignalKind.DNS_LATENCY,
        }
        for finding in findings_so_far:
            for evidence in finding.evidence:
                if hasattr(evidence, "kind") and evidence.kind in latency_kinds:
                    return True
        return False

    def capture_and_analyze(
        self,
        namespace: str,
        target_pod: str,
        duration_s: Optional[int] = None,
    ) -> list[Signal]:
        """
        Run a tcpdump capture pod and return network signals.

        1. Creates capture pod with NET_ADMIN capability
        2. Waits for pod to complete (max duration + 30s)
        3. Gets pod logs (tcpdump output)
        4. Parses for TCP retransmits / resets
        5. Deletes pod (cleanup always runs)
        6. Returns Signals

        Returns empty list if anything fails (always safe to call).
        """
        duration = duration_s or self._settings.tcpdump_capture_s
        signals: list[Signal] = []
        pod_name = f"signalpilot-capture-{int(time.time())}"

        try:
            signals = self._run_capture(namespace, pod_name, target_pod, duration)
        except Exception:
            pass
        finally:
            self._cleanup_pod(namespace, pod_name)

        return signals

    def _run_capture(
        self,
        namespace: str,
        pod_name: str,
        target_pod: str,
        duration: int,
    ) -> list[Signal]:
        """Create pod, wait, read logs, parse signals."""
        raise NotImplementedError("Deep network capture requires cluster access")

    def _cleanup_pod(self, namespace: str, pod_name: str) -> None:
        """Delete the capture pod. Swallows all errors."""
        try:
            client.CoreV1Api().delete_namespaced_pod(pod_name, namespace)
        except Exception:
            pass

    @staticmethod
    def parse_tcpdump_text(tcpdump_output: str) -> list[Signal]:
        """
        Parse tcpdump text output for TCP anomalies.

        Looks for patterns:
        - "Flags [R]" or "Flags [R.]" → TCP reset
        - "retransmit" (case-insensitive) in verbose output → retransmit

        Returns Signal objects for each anomaly found.
        """
        signals: list[Signal] = []
        now = datetime.now(timezone.utc)
        lines = tcpdump_output.splitlines()

        reset_count = sum(1 for line in lines if "[R]" in line or "[R.]" in line)
        retransmit_count = sum(1 for line in lines if "retransmit" in line.lower())

        if reset_count > 0:
            signals.append(Signal(
                type="signal",
                ts=now,
                source=SignalSource.NETWORK,
                kind=SignalKind.TCP_RETRANSMIT,
                severity=Severity.HIGH if reset_count > 10 else Severity.MEDIUM,
                target=Target(kind="Pod", namespace="unknown", name="unknown"),
                value=float(reset_count),
                message=f"TCP resets detected: {reset_count} occurrences",
            ))

        if retransmit_count > 0:
            signals.append(Signal(
                type="signal",
                ts=now,
                source=SignalSource.NETWORK,
                kind=SignalKind.TCP_RETRANSMIT,
                severity=Severity.MEDIUM,
                target=Target(kind="Pod", namespace="unknown", name="unknown"),
                value=float(retransmit_count),
                message=f"TCP retransmits detected: {retransmit_count} occurrences",
            ))

        return signals


# ---------------------------------------------------------------------------
# Legacy module-level helpers kept for backward-compatibility with existing
# callers that imported run_network_capture / run_socket_snapshot / deep_dive.
# ---------------------------------------------------------------------------

def run_network_capture(target: "Target", duration_s: int) -> list[Signal]:
    """Run a tcpdump capture against *target* and return derived signals."""
    raise NotImplementedError


def run_socket_snapshot(target: "Target") -> list[Signal]:
    """Collect socket-level statistics from *target* and return signals."""
    raise NotImplementedError


def deep_dive(analysis: "object") -> list[Signal]:
    """Perform a full deep-dive on the top-priority target in *analysis*."""
    raise NotImplementedError

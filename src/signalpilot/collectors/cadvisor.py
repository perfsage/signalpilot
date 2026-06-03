"""
cAdvisor/kubelet collector for deep performance signals.

Data sources:
- kubelet /stats/summary (JSON): CPU usage/throttling, memory working-set,
  filesystem usage, network I/O per pod/container
- kubelet /metrics (Prometheus text format): container_cpu_cfs_throttled_seconds_total,
  container_cpu_cfs_periods_total (to compute throttle ratio)

Does NOT require Prometheus server — reads directly from kubelet API.
"""
from __future__ import annotations

import json
import re
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


def _parse_kubelet_metrics(metrics_text: str) -> dict[str, dict[str, float]]:
    """
    Parse Prometheus text format from /metrics.

    Returns dict: {metric_name: {label_string: value}}
    where label_string is the raw labels like 'container="app",namespace="ns"'

    Only parses lines matching container_cpu_cfs_* metrics.
    """
    result: dict[str, dict[str, float]] = {}
    for line in metrics_text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if "container_cpu_cfs" not in line:
            continue
        m = re.match(r'^(\w+)\{([^}]+)\}\s+([0-9.e+\-]+)', line)
        if m:
            name, labels, value = m.group(1), m.group(2), float(m.group(3))
            result.setdefault(name, {})[labels] = value
    return result


def _throttle_ratio(throttled_s: float, total_periods: float) -> float:
    """CPU throttle ratio: fraction of periods that were throttled."""
    if total_periods < 1:
        return 0.0
    return min(throttled_s / total_periods, 1.0)


class CAdvisorCollector(BaseCollector):
    """Collect deep CPU/memory/disk signals from kubelet cAdvisor."""

    name = "cadvisor"

    def __init__(self, settings=None):
        self._settings = settings or get_settings()

    def is_available(self) -> bool:
        """Check if kubelet API is reachable via K8s proxy."""
        try:
            nodes = client.CoreV1Api().list_node()
            if not nodes.items:
                return False
            self._kubelet_stats_summary(nodes.items[0].metadata.name)
            return True
        except Exception:
            return False

    def collect(
        self,
        namespace: str,
        deployment: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> list[Signal]:
        """
        Collect CPU throttling and memory working-set signals for pods in namespace.

        1. Get nodes via CoreV1Api().list_node()
        2. For each node, fetch /stats/summary via proxy
        3. Parse per-pod/container stats
        4. Emit signals for each container matching namespace/deployment
        """
        signals: list[Signal] = []
        try:
            nodes = client.CoreV1Api().list_node()
        except Exception:
            return signals

        for node in nodes.items:
            node_name = node.metadata.name
            try:
                summary = self._kubelet_stats_summary(node_name)
            except Exception:
                continue
            signals.extend(self._parse_stats(summary, namespace, deployment, node_name))

        return signals

    def _kubelet_stats_summary(self, node_name: str) -> dict:
        """Fetch /stats/summary from kubelet proxy for a node."""
        api = client.CoreV1Api()
        response = api.connect_get_node_proxy_with_path(
            name=node_name, path="stats/summary"
        )
        return json.loads(response)

    def _parse_stats(
        self,
        summary: dict,
        namespace: str,
        deployment: Optional[str],
        node_name: str,
    ) -> list[Signal]:
        """Extract signals from /stats/summary JSON."""
        signals: list[Signal] = []
        now = datetime.now(timezone.utc)

        for pod in summary.get("pods", []):
            pod_ns = pod.get("podRef", {}).get("namespace", "")
            pod_name = pod.get("podRef", {}).get("name", "")

            if pod_ns != namespace:
                continue
            if deployment and not pod_name.startswith(deployment):
                continue

            for container in pod.get("containers", []):
                container_name = container.get("name", "")
                target = Target(
                    kind="Pod",
                    namespace=namespace,
                    name=pod_name,
                    container=container_name,
                )

                mem = container.get("memory", {})
                working_set = mem.get("workingSetBytes", 0)
                if working_set:
                    signals.append(Signal(
                        type="signal",
                        ts=now,
                        source=SignalSource.CADVISOR,
                        kind=SignalKind.MEM_WORKING_SET,
                        severity=Severity.INFO,
                        target=target,
                        value=float(working_set),
                        message=f"Memory working set: {working_set / (1024**2):.1f}MB",
                    ))

                cpu = container.get("cpu", {})
                cpu_nano = cpu.get("usageNanoCores", 0)
                if cpu_nano:
                    signals.append(Signal(
                        type="signal",
                        ts=now,
                        source=SignalSource.CADVISOR,
                        kind=SignalKind.CPU_USAGE,
                        severity=Severity.INFO,
                        target=target,
                        value=cpu_nano / 1e6,
                        message=f"CPU usage: {cpu_nano / 1e6:.1f}m",
                    ))

                fs = container.get("rootfs", {})
                used_bytes = fs.get("usedBytes", 0)
                capacity_bytes = fs.get("capacityBytes", 0)
                if capacity_bytes > 0:
                    ratio = used_bytes / capacity_bytes
                    if ratio > 0.8:
                        signals.append(Signal(
                            type="signal",
                            ts=now,
                            source=SignalSource.CADVISOR,
                            kind=SignalKind.DISK_PRESSURE,
                            severity=Severity.HIGH,
                            target=target,
                            value=ratio,
                            message=f"Disk usage: {ratio * 100:.1f}% of capacity",
                        ))

        return signals

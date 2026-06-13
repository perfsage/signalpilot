"""Kubernetes Metrics Server collector (``metrics.k8s.io/v1beta1``)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from signalpilot.collectors.base import BaseCollector
from signalpilot.collectors.kube_api import _load_kube_config
from signalpilot.models import (
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)


def _parse_cpu(cpu_str: str) -> float:
    """Parse Kubernetes CPU string to millicores (float).

    Examples: "150m" -> 150.0, "1" -> 1000.0, "0.5" -> 500.0
    """
    cpu_str = cpu_str.strip()
    if cpu_str.endswith("m"):
        return float(cpu_str[:-1])
    if cpu_str.endswith("n"):
        return float(cpu_str[:-1]) / 1_000_000
    return float(cpu_str) * 1000


def _parse_memory(mem_str: str) -> float:
    """Parse Kubernetes memory string to bytes (float).

    Examples: "128Mi" -> 134217728.0, "1Gi" -> 1073741824.0, "500k" -> 500000.0
    """
    mem_str = mem_str.strip()
    suffixes = [
        ("Ki", 1024),
        ("Mi", 1024**2),
        ("Gi", 1024**3),
        ("Ti", 1024**4),
        ("Pi", 1024**5),
        ("Ei", 1024**6),
        ("k", 1000),
        ("M", 1000**2),
        ("G", 1000**3),
        ("T", 1000**4),
        ("P", 1000**5),
        ("E", 1000**6),
    ]
    for suffix, multiplier in suffixes:
        if mem_str.endswith(suffix):
            return float(mem_str[: -len(suffix)]) * multiplier
    return float(mem_str)


def _saturation_severity(ratio: float) -> Severity:
    if ratio > 0.80:
        return Severity.HIGH
    if ratio > 0.60:
        return Severity.MEDIUM
    return Severity.INFO


class MetricsServerCollector(BaseCollector):
    """Collects CPU and memory usage from the Kubernetes Metrics Server."""

    name = "metrics_server"

    def __init__(self, settings=None) -> None:
        self._settings = settings
        self._custom_api: Optional[client.CustomObjectsApi] = None
        self._core_api: Optional[client.CoreV1Api] = None

    def _get_apis(self) -> tuple[client.CustomObjectsApi, client.CoreV1Api]:
        if self._custom_api is None:
            _load_kube_config(self._settings)
            self._custom_api = client.CustomObjectsApi()
            self._core_api = client.CoreV1Api()
        return self._custom_api, self._core_api

    def is_available(self) -> bool:
        try:
            custom_api, _ = self._get_apis()
            custom_api.list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace="default",
                plural="pods",
            )
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            return False
        except Exception:
            return False

    def collect(
        self,
        namespace: str,
        deployment: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> list[Signal]:
        custom_api, core_api = self._get_apis()
        now = datetime.now(timezone.utc)

        # Fetch metrics
        metrics_resp = custom_api.list_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="pods",
        )

        # Build limit lookup from pod specs: {(pod_name, container_name): (cpu_limit_mc, mem_limit_bytes)}
        limits: dict[tuple[str, str], tuple[Optional[float], Optional[float]]] = {}
        try:
            pod_list = core_api.list_namespaced_pod(namespace=namespace)
            for pod in pod_list.items:
                pod_name = pod.metadata.name
                containers = (
                    pod.spec.containers if (pod.spec and pod.spec.containers) else []
                )
                for c in containers:
                    cpu_limit: Optional[float] = None
                    mem_limit: Optional[float] = None
                    res_limits = (
                        c.resources.limits
                        if (c.resources and c.resources.limits)
                        else None
                    )
                    if res_limits is not None:
                        cpu_str = (
                            res_limits.get("cpu")
                            if isinstance(res_limits, dict)
                            else getattr(res_limits, "cpu", None)
                        )
                        mem_str = (
                            res_limits.get("memory")
                            if isinstance(res_limits, dict)
                            else getattr(res_limits, "memory", None)
                        )
                        if cpu_str:
                            cpu_limit = _parse_cpu(cpu_str)
                        if mem_str:
                            mem_limit = _parse_memory(mem_str)
                    limits[(pod_name, c.name)] = (cpu_limit, mem_limit)
        except Exception:
            pass

        signals: list[Signal] = []
        for pod_metrics in metrics_resp.get("items", []):
            pod_name = pod_metrics["metadata"]["name"]

            # Skip if scoped to a specific deployment (label-based heuristic)
            if deployment and not pod_name.startswith(deployment):
                continue

            for container in pod_metrics.get("containers", []):
                container_name = container["name"]
                usage = container.get("usage", {})

                cpu_mc = _parse_cpu(usage["cpu"]) if "cpu" in usage else 0.0
                mem_bytes = _parse_memory(usage["memory"]) if "memory" in usage else 0.0

                target = Target(
                    kind="Pod",
                    namespace=namespace,
                    name=pod_name,
                    container=container_name,
                )

                # CPU usage signal
                cpu_limit_mc, mem_limit_bytes = limits.get(
                    (pod_name, container_name), (None, None)
                )

                cpu_sev = Severity.INFO
                if cpu_limit_mc and cpu_limit_mc > 0:
                    cpu_sev = _saturation_severity(cpu_mc / cpu_limit_mc)

                signals.append(
                    Signal(
                        ts=now,
                        source=SignalSource.METRICS_SERVER,
                        kind=SignalKind.CPU_USAGE,
                        severity=cpu_sev,
                        target=target,
                        value=cpu_mc,
                        message=f"CPU usage {cpu_mc:.1f}m",
                    )
                )

                # Memory usage signal
                mem_sev = Severity.INFO
                if mem_limit_bytes and mem_limit_bytes > 0:
                    mem_sev = _saturation_severity(mem_bytes / mem_limit_bytes)

                signals.append(
                    Signal(
                        ts=now,
                        source=SignalSource.METRICS_SERVER,
                        kind=SignalKind.MEM_USAGE,
                        severity=mem_sev,
                        target=target,
                        value=mem_bytes,
                        message=f"Memory usage {mem_bytes / 1024 / 1024:.1f}Mi",
                    )
                )

        return signals

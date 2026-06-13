"""Kubernetes API collector – pod restarts, OOMKills, CrashLoops, probe failures."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from kubernetes import client
from kubernetes import config as kube_config
from kubernetes.config.config_exception import ConfigException

from signalpilot.collectors.base import BaseCollector
from signalpilot.models import (
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)


def _parse_ts(ts) -> datetime:
    """Coerce various timestamp representations to an aware datetime."""
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _load_kube_config(settings=None) -> None:
    """Load kubeconfig from settings path, in-cluster env, or default location."""
    if settings and getattr(settings, "kubeconfig", None):
        kube_config.load_kube_config(
            config_file=settings.kubeconfig,
            context=getattr(settings, "kube_context", None),
        )
        return
    try:
        kube_config.load_incluster_config()
    except ConfigException:
        kube_config.load_kube_config(
            context=getattr(settings, "kube_context", None) if settings else None
        )


class KubeApiCollector(BaseCollector):
    """Collects pod-level health signals via the Kubernetes REST API."""

    name = "kube_api"

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
        label_selector = f"app={deployment}" if deployment else None
        pod_list = api.list_namespaced_pod(
            namespace=namespace, label_selector=label_selector
        )

        signals: list[Signal] = []
        datetime.now(timezone.utc)

        for pod in pod_list.items:
            pod_name = pod.metadata.name
            pod_ts = _parse_ts(pod.metadata.creation_timestamp)
            target = Target(kind="Pod", namespace=namespace, name=pod_name)

            # Pending pods
            phase = (pod.status.phase if pod.status else None) or ""
            if phase == "Pending":
                signals.append(
                    Signal(
                        ts=pod_ts,
                        source=SignalSource.KUBE_API,
                        kind=SignalKind.PENDING_POD,
                        severity=Severity.HIGH,
                        target=target,
                        message=f"Pod {pod_name} is in Pending state",
                    )
                )
                # Emit a second corroborating signal from pod resource requests
                containers = getattr(pod.spec, "containers", []) or []
                total_cpu_req = 0.0
                total_mem_req = 0
                for c in containers:
                    res = getattr(c, "resources", None)
                    reqs = getattr(res, "requests", None) if res else None
                    if reqs:
                        try:
                            cpu_str = reqs.get("cpu", "0")
                            total_cpu_req += _parse_cpu_req(cpu_str)
                        except Exception:
                            pass
                        try:
                            mem_str = reqs.get("memory", "0")
                            total_mem_req += _parse_mem_req(mem_str)
                        except Exception:
                            pass
                if total_cpu_req > 0 or total_mem_req > 0:
                    signals.append(Signal(
                        ts=pod_ts,
                        source=SignalSource.KUBE_API,
                        kind=SignalKind.NODE_CONDITION,
                        severity=Severity.HIGH,
                        target=target,
                        value=total_cpu_req,
                        message=(
                            f"Pod {pod_name} requests "
                            f"{total_cpu_req:.0f}m CPU, {total_mem_req // (1024**2):.0f}Mi memory — "
                            "pod is unschedulable (no node has capacity)"
                        ),
                    ))

            # Probe failures from pod conditions
            conditions = (pod.status.conditions if pod.status else None) or []
            for cond in conditions:
                if cond.type == "ContainersReady" and cond.status == "False":
                    reason = getattr(cond, "reason", None) or "unknown"
                    signals.append(
                        Signal(
                            ts=pod_ts,
                            source=SignalSource.KUBE_API,
                            kind=SignalKind.PROBE_FAILURE,
                            severity=Severity.HIGH,
                            target=target,
                            message=f"ContainersReady=False reason={reason}",
                        )
                    )
                    break

            # Per-container status checks
            cs_list = (pod.status.container_statuses if pod.status else None) or []
            for cs in cs_list:
                ct = Target(
                    kind="Pod",
                    namespace=namespace,
                    name=pod_name,
                    container=cs.name,
                )

                # Restart count
                restart_count = getattr(cs, "restart_count", 0) or 0
                if restart_count > 0:
                    if restart_count >= 10:
                        sev = Severity.CRITICAL
                    elif restart_count >= 5:
                        sev = Severity.HIGH
                    else:
                        sev = Severity.MEDIUM
                    signals.append(
                        Signal(
                            ts=pod_ts,
                            source=SignalSource.KUBE_API,
                            kind=SignalKind.RESTART,
                            severity=sev,
                            target=ct,
                            value=float(restart_count),
                            message=f"Container {cs.name} restarted {restart_count} times",
                        )
                    )

                # Compute waiting state early (used in crash-loop heuristics below)
                _state_early = getattr(cs, "state", None)
                _waiting_early = getattr(_state_early, "waiting", None) if _state_early else None
                _waiting_reason_early = getattr(_waiting_early, "reason", "") if _waiting_early else ""

                # CrashLoop via restart history (catches brief Running phase between crashes)
                # If restart_count >= 3 and last termination was Error (not OOM), it's a crashloop
                if restart_count >= 3:
                    last_state_chk = getattr(cs, "last_state", None)
                    last_term_chk = getattr(last_state_chk, "terminated", None) if last_state_chk else None
                    last_reason = getattr(last_term_chk, "reason", "") if last_term_chk else ""
                    # Only emit CRASH_LOOP here if waiting state didn't already emit it
                    if _waiting_reason_early != "CrashLoopBackOff" and last_reason not in ("OOMKilled", "Completed"):
                        signals.append(Signal(
                            ts=pod_ts,
                            source=SignalSource.KUBE_API,
                            kind=SignalKind.CRASH_LOOP,
                            severity=Severity.CRITICAL,
                            target=ct,
                            value=float(restart_count),
                            message=f"Container {cs.name} crash-looping ({restart_count} restarts, last exit: {last_reason or 'Error'})",
                        ))

                # OOMKilled from last termination
                last_state = getattr(cs, "last_state", None)
                last_term = (
                    getattr(last_state, "terminated", None) if last_state else None
                )
                if last_term and getattr(last_term, "reason", None) == "OOMKilled":
                    signals.append(
                        Signal(
                            ts=pod_ts,
                            source=SignalSource.KUBE_API,
                            kind=SignalKind.OOM_KILLED,
                            severity=Severity.CRITICAL,
                            target=ct,
                            message=f"Container {cs.name} last terminated due to OOMKilled",
                        )
                    )

                # Waiting-state reason checks
                state = getattr(cs, "state", None)
                waiting = getattr(state, "waiting", None) if state else None
                if waiting:
                    reason = getattr(waiting, "reason", None) or ""
                    if reason == "CrashLoopBackOff":
                        signals.append(
                            Signal(
                                ts=pod_ts,
                                source=SignalSource.KUBE_API,
                                kind=SignalKind.CRASH_LOOP,
                                severity=Severity.CRITICAL,
                                target=ct,
                                message=f"Container {cs.name} is in CrashLoopBackOff",
                            )
                        )
                    elif reason in ("ImagePullBackOff", "ErrImagePull"):
                        signals.append(
                            Signal(
                                ts=pod_ts,
                                source=SignalSource.KUBE_API,
                                kind=SignalKind.IMAGE_PULL_ERROR,
                                severity=Severity.HIGH,
                                target=ct,
                                message=f"Container {cs.name}: {reason}",
                            )
                        )

            # Init container status checks — emit CRASH_LOOP with "init" context
            init_cs_list = (
                getattr(pod.status, "init_container_statuses", None)
                if pod.status else None
            ) or []
            for ics in init_cs_list:
                ics_target = Target(
                    kind="Pod",
                    namespace=namespace,
                    name=pod_name,
                    container=ics.name,
                )
                ics_state = getattr(ics, "state", None)
                ics_waiting = getattr(ics_state, "waiting", None) if ics_state else None
                ics_waiting_reason = getattr(ics_waiting, "reason", "") if ics_waiting else ""
                ics_last = getattr(ics, "last_state", None)
                ics_last_term = getattr(ics_last, "terminated", None) if ics_last else None
                ics_exit_code = getattr(ics_last_term, "exit_code", 0) if ics_last_term else 0

                if ics_waiting_reason == "CrashLoopBackOff" or ics_exit_code != 0:
                    signals.append(Signal(
                        ts=pod_ts,
                        source=SignalSource.KUBE_API,
                        kind=SignalKind.CRASH_LOOP,
                        severity=Severity.CRITICAL,
                        target=ics_target,
                        value=float(getattr(ics, "restart_count", 0) or 0),
                        message=(
                            f"Init container {ics.name} failed "
                            f"(exit_code={ics_exit_code}, reason={ics_waiting_reason or 'Error'})"
                            " [init:fail]"
                        ),
                    ))

        return signals


def _parse_cpu_req(value: str) -> float:
    """Parse Kubernetes CPU string to millicores (e.g. '500m' → 500.0, '1' → 1000.0)."""
    value = value.strip()
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


def _parse_mem_req(value: str) -> int:
    """Parse Kubernetes memory string to bytes (e.g. '128Mi' → 134217728)."""
    value = value.strip()
    units = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4, "": 1}
    for suffix, mult in sorted(units.items(), key=lambda x: -len(x[0])):
        if suffix and value.endswith(suffix):
            return int(value[: -len(suffix)]) * mult
    return int(value) if value.isdigit() else 0

"""Container log collector via the Kubernetes pod log API, with secret redaction."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from kubernetes import client

from signalpilot.collectors.base import BaseCollector
from signalpilot.collectors.kube_api import _load_kube_config
from signalpilot.models import (
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)

_ERROR_RE = re.compile(
    r"(?i)(error|exception|fatal|critical|panic|traceback)"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)(authorization:\s*\w+\s+)[^\s\r\n]+"
)
_SECRET_KV_RE = re.compile(
    r"(?i)(password|token|secret|api_key|apikey)([=:\s]+)[^\s&\r\n]{6,}"
)


def redact_secrets(log_text: str) -> str:
    """Remove sensitive values from a log string.

    Redacts:
    - ``Authorization: Bearer <TOKEN>`` style headers
    - ``password=<VALUE>``, ``token=<VALUE>``, ``secret=<VALUE>``,
      ``api_key=<VALUE>``, ``apikey=<VALUE>`` key-value pairs where the
      value is at least 6 characters long
    """
    log_text = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", log_text)
    log_text = _SECRET_KV_RE.sub(r"\1\2[REDACTED]", log_text)
    return log_text


def _make_insecure_api() -> client.CoreV1Api:
    """Create a CoreV1Api with SSL verification disabled.

    Used as a fallback when the kubelet's TLS certificate doesn't match
    the current node IP (common after Rancher Desktop network changes).
    """
    from kubernetes import config as kube_config

    cfg = client.Configuration()
    try:
        kube_config.load_kube_config(client_configuration=cfg)
    except Exception:
        try:
            kube_config.load_incluster_config()
        except Exception:
            pass
    cfg.verify_ssl = False
    cfg.ssl_ca_cert = None
    return client.CoreV1Api(api_client=client.ApiClient(configuration=cfg))


def _decode_log(raw) -> str:
    """Normalize kubernetes log API output to a plain str with real newlines.

    Some versions of the kubernetes Python client return:
    - A plain str  (ideal)
    - bytes        (decode directly)
    - A str that is the repr of a bytes literal: b"line1\\nline2"
    """
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return str(raw)
    # Detect b"..." repr strings produced by the K8s client on some backends
    stripped = raw.strip()
    if stripped.startswith(('b"', "b'")):
        try:
            import ast
            decoded = ast.literal_eval(stripped)
            if isinstance(decoded, bytes):
                return decoded.decode("utf-8", errors="replace")
        except Exception:
            pass
    return raw


def _read_pod_log_safe(
    api: client.CoreV1Api,
    insecure_api_ref: list,  # mutable singleton cache [api | None]
    pod_name: str,
    namespace: str,
    container_name: str,
    tail_lines: int,
    previous: bool = False,
) -> str:
    """Read pod log, falling back to insecure API on x509 errors."""
    kwargs = dict(
        name=pod_name,
        namespace=namespace,
        container=container_name,
        tail_lines=tail_lines,
    )
    if previous:
        kwargs["previous"] = True

    try:
        return _decode_log(api.read_namespaced_pod_log(**kwargs) or "")
    except Exception as exc:
        if "x509" not in str(exc) and "certificate" not in str(exc).lower():
            raise
    # x509/cert error — retry with insecure API (local cluster only)
    if not insecure_api_ref:
        insecure_api_ref.append(_make_insecure_api())
    insecure_api = insecure_api_ref[0]
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return _decode_log(insecure_api.read_namespaced_pod_log(**kwargs) or "")


class LogsCollector(BaseCollector):
    """Collects raw container logs and emits LOG_ERROR_RATE signals."""

    name = "logs"

    def __init__(self, settings=None, tail_lines: int = 5000) -> None:
        self._settings = settings
        self._tail_lines = tail_lines
        self._api: Optional[client.CoreV1Api] = None
        self._insecure_api: list = []  # lazy singleton for cert-fallback

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
        now = datetime.now(timezone.utc)

        for pod in pod_list.items:
            pod_name = pod.metadata.name
            containers = (
                pod.spec.containers if (pod.spec and pod.spec.containers) else []
            )

            for container in containers:
                container_name = container.name
                try:
                    raw_log = _read_pod_log_safe(
                        api, self._insecure_api,
                        pod_name, namespace, container_name, self._tail_lines,
                    )
                except Exception:
                    continue

                if not raw_log:
                    continue

                redacted = redact_secrets(raw_log)
                lines = redacted.splitlines()
                error_count = sum(1 for ln in lines if _ERROR_RE.search(ln))

                severity = (
                    Severity.HIGH
                    if error_count > 50
                    else Severity.MEDIUM
                    if error_count > 10
                    else Severity.INFO
                    if error_count > 0
                    else Severity.INFO
                )

                # Include a short snippet (first 500 chars) as the message
                snippet = redacted[:500] if len(redacted) > 500 else redacted

                target = Target(
                    kind="Pod",
                    namespace=namespace,
                    name=pod_name,
                    container=container_name,
                )

                signals.append(
                    Signal(
                        ts=now,
                        source=SignalSource.LOGS,
                        kind=SignalKind.LOG_ERROR_RATE,
                        severity=severity,
                        target=target,
                        value=float(error_count),
                        message=snippet,
                    )
                )

        return signals

    def collect_raw(
        self,
        namespace: str,
        deployment: Optional[str] = None,
    ) -> dict[str, str]:
        """
        Return raw (redacted) log text combined from all matching pods.

        Used by the CLI for drain3 log clustering. Reads both current logs
        and previous terminated container logs.

        Returns:
            {
                "current":  all current container logs joined by newline,
                "previous": all previous (terminated) container logs joined by newline,
            }
        Silently skips any pod/container that raises an exception.
        """
        api = self._get_api()
        label_selector = f"app={deployment}" if deployment else None
        try:
            pod_list = api.list_namespaced_pod(
                namespace=namespace, label_selector=label_selector
            )
        except Exception:
            return {"current": "", "previous": ""}

        current_parts: list[str] = []
        previous_parts: list[str] = []

        for pod in pod_list.items:
            pod_name = pod.metadata.name
            containers = (
                pod.spec.containers if (pod.spec and pod.spec.containers) else []
            )
            for container in containers:
                # Current logs
                try:
                    log = _read_pod_log_safe(
                        api, self._insecure_api,
                        pod_name, namespace, container.name, self._tail_lines,
                    )
                    if log:
                        current_parts.append(redact_secrets(log))
                except Exception:
                    pass
                # Previous terminated container logs (critical for crashloop RCA)
                try:
                    prev_log = _read_pod_log_safe(
                        api, self._insecure_api,
                        pod_name, namespace, container.name, self._tail_lines,
                        previous=True,
                    )
                    if prev_log:
                        previous_parts.append(redact_secrets(prev_log))
                except Exception:
                    pass

        return {
            "current": "\n".join(current_parts),
            "previous": "\n".join(previous_parts),
        }

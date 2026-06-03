"""Container log collector via the Kubernetes pod log API, with secret redaction."""

from __future__ import annotations

import re
from datetime import datetime, timezone
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


class LogsCollector(BaseCollector):
    """Collects raw container logs and emits LOG_ERROR_RATE signals."""

    name = "logs"

    def __init__(self, settings=None, tail_lines: int = 5000) -> None:
        self._settings = settings
        self._tail_lines = tail_lines
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
        now = datetime.now(timezone.utc)

        for pod in pod_list.items:
            pod_name = pod.metadata.name
            containers = (
                pod.spec.containers if (pod.spec and pod.spec.containers) else []
            )

            for container in containers:
                container_name = container.name
                try:
                    raw_log = api.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        container=container_name,
                        tail_lines=self._tail_lines,
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

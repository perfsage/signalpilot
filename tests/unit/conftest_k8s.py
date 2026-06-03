"""Shared helpers for Kubernetes collector unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def ns(d: Any) -> Any:
    """Recursively convert a dict to SimpleNamespace so attribute access works."""
    if d is None:
        return None
    if isinstance(d, dict):
        return SimpleNamespace(**{k: ns(v) for k, v in d.items()})
    if isinstance(d, list):
        return [ns(i) for i in d]
    return d


def make_pod_list(data: dict) -> SimpleNamespace:
    """Convert a pods fixture dict to a mock pod list with ``.items``."""
    return SimpleNamespace(items=[ns(pod) for pod in data["items"]])


def make_event_list(data: dict) -> SimpleNamespace:
    """Convert an events fixture dict to a mock event list with ``.items``."""
    return SimpleNamespace(items=[ns(evt) for evt in data["items"]])


def make_rs_list(data: dict) -> SimpleNamespace:
    """Convert a replicasets fixture dict to a mock RS list with ``.items``."""
    return SimpleNamespace(items=[ns(rs) for rs in data["items"]])

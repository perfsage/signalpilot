"""Deep-dive orchestrator for network and system-level captures.

Full implementation will:
- Trigger ephemeral debug containers via the K8s ephemeral container API
- Run ``tcpdump`` captures and stream results for real-time analysis
- Execute ``ss``/``netstat`` snapshots to detect socket backlog issues
- Parse and summarise capture results into Signal objects
"""

from __future__ import annotations

from signalpilot.models import Analysis, Signal, Target


def run_network_capture(target: Target, duration_s: int) -> list[Signal]:
    """Run a tcpdump capture against *target* and return derived signals."""
    raise NotImplementedError


def run_socket_snapshot(target: Target) -> list[Signal]:
    """Collect socket-level statistics from *target* and return signals."""
    raise NotImplementedError


def deep_dive(analysis: Analysis) -> list[Signal]:
    """Perform a full deep-dive on the top-priority target in *analysis*."""
    raise NotImplementedError

"""Deterministic RCA rules (pattern-matching layer).

Full implementation will define a library of named rules, each of which:
- Matches a specific pattern of signals, regressions, or deploy changes
- Produces one or more Finding objects when the pattern fires
- Is identified by a stable ``rule_id`` string

Example rules:
- ``oom_after_resource_reduction`` – OOMKill + resource limit lowered in diff
- ``crash_loop_new_image`` – CrashLoopBackOff + image tag changed
- ``latency_spike_new_dep`` – p99 latency spike + new dependency commit
- ``dns_timeout_storm`` – DNS latency spike + connection refused log cluster
"""

from __future__ import annotations

from typing import Protocol

from signalpilot.models import Analysis, Finding


class RcaRule(Protocol):
    """Protocol that every RCA rule must satisfy."""

    rule_id: str

    def match(self, analysis: Analysis) -> list[Finding]:
        """Return findings if this rule fires against *analysis*, else ``[]``."""
        ...


def load_all_rules() -> list[RcaRule]:
    """Return all built-in RCA rules, ready to be evaluated."""
    raise NotImplementedError

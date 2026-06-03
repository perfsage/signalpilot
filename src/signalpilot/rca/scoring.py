"""Finding scoring and ranking.

Full implementation will:
- Compute a composite priority score from ``severity``, ``confidence``, and
  ``blast_radius``
- Merge duplicate findings from multiple rule firings
- Sort findings so the most actionable items appear first
"""

from __future__ import annotations

from signalpilot.models import Finding, Severity

SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 1.0,
    Severity.HIGH: 0.8,
    Severity.MEDIUM: 0.5,
    Severity.LOW: 0.3,
    Severity.INFO: 0.1,
}


def priority_score(finding: Finding) -> float:
    """Return a 0-1 priority score for *finding*.

    Higher values should be displayed first.
    """
    raise NotImplementedError


def rank_findings(findings: list[Finding]) -> list[Finding]:
    """Return *findings* sorted descending by ``priority_score``."""
    raise NotImplementedError


def deduplicate(findings: list[Finding]) -> list[Finding]:
    """Merge findings with the same ``rule_id`` and ``target`` into one."""
    raise NotImplementedError

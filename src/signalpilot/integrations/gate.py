"""CI/CD quality gate integration.

Full implementation will:
- Evaluate an Analysis against a configured minimum severity threshold
- Exit non-zero (sys.exit(1)) when findings at or above the threshold exist
- Emit a JUnit XML or GitHub Actions annotation for failed findings
"""

from __future__ import annotations

import sys

from signalpilot.models import Analysis, Severity


def evaluate_gate(analysis: Analysis, threshold: Severity = Severity.HIGH) -> bool:
    """Return True if the analysis passes the quality gate.

    The gate fails (returns False) when any finding has severity >= *threshold*.
    """
    raise NotImplementedError


def run_gate(analysis: Analysis, threshold: Severity = Severity.HIGH) -> None:
    """Evaluate the gate and call ``sys.exit(1)`` on failure."""
    raise NotImplementedError

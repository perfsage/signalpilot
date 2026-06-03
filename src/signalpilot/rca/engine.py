"""RCA engine – orchestrates signal collection, analysis, and rule evaluation.

Full implementation will:
1. Run all registered collectors for the analysis window
2. Detect regressions and log cluster deltas
3. Evaluate every RCA rule against the assembled context
4. Score and de-duplicate findings
5. Optionally invoke the LLM narrative layer
6. Return a fully populated Analysis object
"""

from __future__ import annotations

from signalpilot.config import Settings
from signalpilot.models import Analysis


async def run_analysis(
    namespace: str,
    settings: Settings | None = None,
) -> Analysis:
    """Run a full RCA analysis for *namespace* and return the result.

    Args:
        namespace: Kubernetes namespace to analyse.
        settings: Optional settings override; defaults to ``get_settings()``.

    Returns:
        Populated Analysis with findings sorted by (severity, confidence).
    """
    raise NotImplementedError

"""
Scoring and deduplication for RCA Findings.

Priority score = severity_weight × confidence × (1 + blast_radius)
severity_weights: CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1, INFO=0.5
"""
from __future__ import annotations

from signalpilot.models import Finding, Severity
from signalpilot.topology import TopologyBuilder


SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 4.0,
    Severity.HIGH: 3.0,
    Severity.MEDIUM: 2.0,
    Severity.LOW: 1.0,
    Severity.INFO: 0.5,
}


def compute_blast_radius(finding: Finding, topo: TopologyBuilder | None) -> float:
    """Look up this finding's target in the topology and return blast_radius."""
    if topo is None:
        return 0.0
    node_id = topo.find_node(finding.target.kind, finding.target.name, finding.target.namespace)
    if node_id is None:
        return 0.0
    return topo.blast_radius(node_id)


def score_finding(finding: Finding) -> float:
    """Compute priority score for sorting."""
    w = SEVERITY_WEIGHT.get(finding.severity, 1.0)
    return w * finding.confidence * (1.0 + finding.blast_radius)


def deduplicate(findings: list[Finding]) -> list[Finding]:
    """
    Remove near-duplicate findings.
    Two findings are duplicates if they have the same rule_id AND same target name.
    Keep the one with higher score.
    """
    seen: dict[str, Finding] = {}
    for f in findings:
        key = f"{f.rule_id}:{f.target.namespace}/{f.target.name}"
        if key not in seen or score_finding(f) > score_finding(seen[key]):
            seen[key] = f
    return list(seen.values())


def rank_findings(
    findings: list[Finding],
    topo: TopologyBuilder | None = None,
) -> list[Finding]:
    """
    1. Compute blast_radius for each finding via topology
    2. Deduplicate
    3. Sort by priority score descending
    Returns new Finding objects with blast_radius populated.
    """
    enriched = []
    for f in findings:
        br = compute_blast_radius(f, topo)
        enriched.append(f.model_copy(update={"blast_radius": br}))

    deduped = deduplicate(enriched)
    return sorted(deduped, key=score_finding, reverse=True)

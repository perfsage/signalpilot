"""
Deterministic template-based narrative generator.

Produces a 3-5 paragraph plain-English summary that answers:
1. What happened (context: when/what was deployed)
2. What we found (N findings, their severities)
3. What to do first (top finding + fix)
"""
from __future__ import annotations
from signalpilot.models import Analysis, Severity


_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


def generate_narrative(analysis: Analysis) -> str:
    """
    Generate a deterministic narrative for the analysis.

    Structure:
    - Paragraph 1: Deploy context (when, what changed)
    - Paragraph 2: Summary of findings count/severity
    - Paragraph 3: Top finding detail + recommended first action
    - Paragraph 4 (if git present): Suspect commit info
    """
    parts = []

    # Para 1: context
    dc = analysis.deploy_change
    if dc:
        img_str = ""
        if dc.image_diffs:
            img_str = f" Image changed to {dc.image_diffs[0].to_image}."
        parts.append(
            f"Deployment '{dc.deployment}' in namespace '{dc.namespace}' was updated "
            f"at {dc.deploy_time.strftime('%Y-%m-%d %H:%M UTC')} "
            f"(revision {dc.from_revision or '?'} → {dc.to_revision}).{img_str}"
        )
    else:
        parts.append(
            f"Analysis of namespace '{analysis.namespace}' completed at "
            f"{analysis.ts.strftime('%Y-%m-%d %H:%M UTC')}."
        )

    # Para 2: summary
    if not analysis.findings:
        parts.append("No significant issues detected. The deployment appears healthy.")
        return "\n\n".join(parts)

    crit = sum(1 for f in analysis.findings if f.severity == Severity.CRITICAL)
    high = sum(1 for f in analysis.findings if f.severity == Severity.HIGH)
    total = len(analysis.findings)

    sev_summary = []
    if crit:
        sev_summary.append(f"{crit} critical")
    if high:
        sev_summary.append(f"{high} high")
    other = total - crit - high
    if other:
        sev_summary.append(f"{other} medium/low")

    parts.append(
        f"SignalPilot identified {total} finding(s): {', '.join(sev_summary)}. "
        f"Sources analyzed: {', '.join(analysis.sources_used) if analysis.sources_used else 'native K8s API'}."
        + (f" Analysis completed in {analysis.duration_s:.1f}s." if analysis.duration_s else "")
    )

    # Para 3: top finding
    top = analysis.findings[0]
    top_fix = top.fixes[0] if top.fixes else None
    fix_str = ""
    if top_fix:
        fix_str = f" Recommended first action: {top_fix.description}."
        if top_fix.kubectl_snippet:
            fix_str += f" Run: `{top_fix.kubectl_snippet}`"

    parts.append(
        f"Top finding [{top.severity.value.upper()}] '{top.title}' "
        f"(confidence {top.confidence:.0%}): {top.explanation[:300]}"
        + fix_str
    )

    # Para 4: git suspect
    if dc and dc.git and dc.git.suspect_commits:
        gc = dc.git
        s = gc.suspect_commits[0]
        parts.append(
            f"Git correlation: commit {s.sha[:8]} by {s.author} — '{s.message[:100]}' "
            f"is flagged as suspect. Diff range: {gc.from_sha[:8] if gc.from_sha else '?'} → {gc.to_sha[:8]}."
        )

    return "\n\n".join(parts)

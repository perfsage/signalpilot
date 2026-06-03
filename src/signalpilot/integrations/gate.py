"""CI/CD gate integration for SignalPilot."""
from __future__ import annotations
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from signalpilot.models import Analysis, Severity


_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


def gate_check(analysis: Analysis, threshold: Severity) -> bool:
    """
    Return True (pass) if no finding meets or exceeds the severity threshold.
    Return False (fail) if any finding is at or above the threshold.
    """
    threshold_idx = _SEVERITY_ORDER.index(threshold)
    for finding in analysis.findings:
        finding_idx = _SEVERITY_ORDER.index(finding.severity)
        if finding_idx <= threshold_idx:  # lower index = higher severity
            return False
    return True


def generate_junit_xml(analysis: Analysis, output_path: Path) -> None:
    """
    Generate a JUnit XML file for CI systems.

    Each finding becomes a test case.
    CRITICAL/HIGH findings become test failures.
    MEDIUM/LOW/INFO findings become test warnings (no failure).
    """
    suite = ET.Element("testsuite", {
        "name": f"SignalPilot-{analysis.namespace}",
        "tests": str(len(analysis.findings)),
        "failures": str(sum(1 for f in analysis.findings if f.severity in (Severity.CRITICAL, Severity.HIGH))),
        "time": str(analysis.duration_s or 0),
    })

    for finding in analysis.findings:
        case = ET.SubElement(suite, "testcase", {
            "name": finding.title,
            "classname": f"signalpilot.{finding.rule_id or 'unknown'}",
            "time": "0",
        })
        if finding.severity in (Severity.CRITICAL, Severity.HIGH):
            failure = ET.SubElement(case, "failure", {
                "message": finding.title,
                "type": finding.severity.value.upper(),
            })
            failure.text = finding.explanation[:500]

    tree = ET.ElementTree(suite)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_path), encoding="unicode", xml_declaration=True)


def generate_markdown_summary(analysis: Analysis) -> str:
    """
    Generate a Markdown summary suitable for GitHub PR comments or CI logs.
    """
    lines = [
        f"## \u26a1 SignalPilot RCA \u2014 `{analysis.namespace}`",
        "",
        f"**{len(analysis.findings)} finding(s)** | Analysis ID: `{analysis.id}`",
        "",
    ]

    if not analysis.findings:
        lines.append("\u2705 No significant issues detected.")
        return "\n".join(lines)

    for finding in analysis.findings:
        badge = "\U0001f534" if finding.severity == Severity.CRITICAL else "\U0001f7e0" if finding.severity == Severity.HIGH else "\U0001f7e1"
        lines.append(f"### {badge} [{finding.severity.value.upper()}] {finding.title}")
        lines.append("")
        lines.append(finding.explanation[:300])
        if finding.fixes:
            fix = finding.fixes[0]
            lines.append(f"\n**Fix:** {fix.description}")
            if fix.kubectl_snippet:
                lines.append(f"\n```bash\n{fix.kubectl_snippet}\n```")
        lines.append("")

    return "\n".join(lines)

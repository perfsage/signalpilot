from datetime import datetime, timezone

from signalpilot.models import Analysis, Finding, Fix, Severity, Target
from signalpilot.narrate.template import generate_narrative

T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)


def make_analysis(findings=None, deploy=None):
    return Analysis(
        id="test123", ts=T0, namespace="prod",
        deploy_change=deploy,
        findings=findings or [],
        sources_used=["kube_api", "logs"],
    )


def make_finding(sev=Severity.HIGH, title="Test finding"):
    return Finding(
        id="f1", title=title, severity=sev, confidence=0.85, blast_radius=0.3,
        target=Target(kind="Pod", namespace="prod", name="api-abc"),
        explanation="Something went wrong.",
        fixes=[Fix(description="Fix it", kind="rollback", kubectl_snippet="kubectl rollout undo deployment/api")],
    )


class TestGenerateNarrative:
    def test_no_findings_returns_healthy(self):
        analysis = make_analysis()
        n = generate_narrative(analysis)
        assert "healthy" in n.lower() or "no significant" in n.lower()

    def test_with_finding_mentions_severity(self):
        analysis = make_analysis(findings=[make_finding(Severity.CRITICAL)])
        n = generate_narrative(analysis)
        assert "critical" in n.lower()

    def test_with_finding_includes_kubectl(self):
        analysis = make_analysis(findings=[make_finding()])
        n = generate_narrative(analysis)
        assert "kubectl" in n

    def test_returns_non_empty_string(self):
        analysis = make_analysis(findings=[make_finding()])
        assert generate_narrative(analysis).strip()

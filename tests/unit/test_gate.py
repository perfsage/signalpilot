from datetime import datetime, timezone

from signalpilot.integrations.gate import gate_check, generate_junit_xml, generate_markdown_summary
from signalpilot.models import Analysis, Finding, Severity, Target

T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)


def make_analysis(findings):
    return Analysis(id="g1", ts=T0, namespace="ns", deploy_change=None, findings=findings, sources_used=[])


def make_finding(sev):
    return Finding(
        id="f1", title=f"{sev.value} issue", severity=sev, confidence=0.9, blast_radius=0.2,
        target=Target(kind="Pod", namespace="ns", name="pod"),
        explanation="desc",
    )


class TestGateCheck:
    def test_pass_when_no_findings(self):
        assert gate_check(make_analysis([]), Severity.HIGH) is True

    def test_fail_on_critical_with_high_threshold(self):
        assert gate_check(make_analysis([make_finding(Severity.CRITICAL)]), Severity.HIGH) is False

    def test_pass_on_medium_with_high_threshold(self):
        assert gate_check(make_analysis([make_finding(Severity.MEDIUM)]), Severity.HIGH) is True

    def test_fail_on_high_with_high_threshold(self):
        assert gate_check(make_analysis([make_finding(Severity.HIGH)]), Severity.HIGH) is False


class TestJUnitXml:
    def test_creates_file(self, tmp_path):
        analysis = make_analysis([make_finding(Severity.CRITICAL)])
        out = tmp_path / "results.xml"
        generate_junit_xml(analysis, out)
        assert out.exists()
        content = out.read_text()
        assert "testsuite" in content
        assert "<failure" in content

    def test_medium_finding_no_failure_element(self, tmp_path):
        analysis = make_analysis([make_finding(Severity.MEDIUM)])
        out = tmp_path / "results.xml"
        generate_junit_xml(analysis, out)
        content = out.read_text()
        assert "<failure" not in content


class TestMarkdownSummary:
    def test_contains_namespace(self):
        md = generate_markdown_summary(make_analysis([make_finding(Severity.HIGH)]))
        assert "ns" in md

    def test_no_findings_healthy(self):
        md = generate_markdown_summary(make_analysis([]))
        assert "No significant" in md

from datetime import datetime, timezone
from signalpilot.report.html import generate_html_report
from signalpilot.models import Analysis, Finding, Fix, Target, Severity

T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)


def make_analysis(findings=None):
    return Analysis(
        id="rep1", ts=T0, namespace="prod",
        deploy_change=None,
        findings=findings or [],
        sources_used=["kube_api"],
    )


def make_finding():
    return Finding(
        id="f1", title="OOM Killed", severity=Severity.CRITICAL,
        confidence=0.9, blast_radius=0.5,
        target=Target(kind="Pod", namespace="prod", name="api-abc", container="app"),
        explanation="Container killed by OOM.",
        fixes=[Fix(description="Raise limit", kind="patch", kubectl_snippet="kubectl set resources ...")],
    )


class TestHtmlReport:
    def test_returns_html_string(self):
        html = generate_html_report(make_analysis())
        assert html.strip().startswith("<!DOCTYPE html")

    def test_contains_namespace(self):
        html = generate_html_report(make_analysis())
        assert "prod" in html

    def test_finding_title_in_report(self):
        html = generate_html_report(make_analysis([make_finding()]))
        assert "OOM Killed" in html

    def test_kubectl_snippet_in_report(self):
        html = generate_html_report(make_analysis([make_finding()]))
        assert "kubectl set resources" in html

    def test_writes_to_file(self, tmp_path):
        path = tmp_path / "report.html"
        result = generate_html_report(make_analysis(), output_path=path)
        assert path.exists()
        assert "SignalPilot" in path.read_text()


class TestPrometheusCollector:
    def test_is_available_false_when_no_prometheus(self):
        from unittest.mock import patch
        from signalpilot.collectors.prometheus import PrometheusCollector
        collector = PrometheusCollector()
        collector._settings.prometheus_url = None
        with patch("signalpilot.collectors.prometheus.httpx.get", side_effect=Exception("no conn")):
            assert collector.is_available() is False

    def test_collect_returns_empty_when_unavailable(self):
        from signalpilot.collectors.prometheus import PrometheusCollector
        collector = PrometheusCollector()
        collector._base_url = None
        # Don't call is_available (would try network)
        sigs = collector.collect("test-ns")  # base_url is None → returns []
        assert isinstance(sigs, list)
